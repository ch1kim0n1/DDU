"""ddu-mirror-intel — standalone service entry point.

Engineer A owns the DDU Mirror app skeleton and mounts ``mirror_intel.api.router``
into it. This module wraps the same router in its own app so B's slice runs and
demos independently — nobody on this team should be blocked waiting for
somebody else's server to boot.

Follows the DDU service contract from AGENTS.md: ``/healthz``, ``/versionz``,
and OpenLineage emission on invocation.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Callable

# Fail closed before the rest of the app imports identity-gated modules.
from mirror_intel.env import enforce_production_boot, mirror_env

enforce_production_boot()

import sentry_sdk
import uvicorn
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pythonjsonlogger.json import JsonFormatter
from sentry_sdk.integrations.fastapi import FastApiIntegration
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from ddu_common.app import build_scaffold_app
from ddu_common.version import ServiceVersion, from_env

from mirror_intel import __version__
from mirror_intel.api import router
from mirror_intel.llm import get_llm
from mirror_intel.events import event_bus
from mirror_intel.identity import verifier
from mirror_intel.providers import provider_status
from mirror_intel.ratelimit import client_ip, limiter
from mirror_intel.schema import CONTRACT_VERSION
from mirror_intel.session import store
from mirror_intel.workflow import runtime

MIRROR_ENV = mirror_env()


def _configure_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(session_id)s %(request_id)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return logging.getLogger("ddu-mirror-intel")


log = _configure_logging()

if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment=MIRROR_ENV,
    )

VERSION = from_env(
    ServiceVersion(
        service="ddu-mirror-intel",
        service_version=__version__,
        tool="ddu-mirror-findings-contract",
        tool_version=CONTRACT_VERSION,
    )
)

PORT = int(os.environ.get("MIRROR_INTEL_PORT", "8120"))

REQUEST_DURATION = Histogram(
    "ddu_request_duration_seconds",
    "HTTP request latency",
    ["method", "path", "status"],
)
SESSION_CREATE_TOTAL = Counter("ddu_session_create_total", "Sessions created")
PROPOSALS_APPROVED = Counter("ddu_proposals_approved_total", "Proposals approved")
PROPOSALS_REJECTED = Counter("ddu_proposals_rejected_total", "Proposals rejected")
VOICE_TURNS = Counter("ddu_voice_turns_total", "Voice turns")
VISION_ANALYSES = Counter("ddu_vision_analyses_total", "Vision analyses")
SESSIONS_ACTIVE = Gauge("ddu_sessions_active", "Active sessions")
WS_ACTIVE = Gauge("ddu_websocket_connections_active", "Active WebSocket connections")

app = build_scaffold_app(VERSION)
if MIRROR_ENV == "production":
    app.docs_url = None
    app.redoc_url = None
    app.openapi_url = None
else:
    from fastapi.openapi.utils import get_openapi

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=VERSION.service_version,
            routes=app.routes,
            description="DDU Mirror Intel API. Session endpoints require Bearer identity assertion in production.",
        )
        components = schema.setdefault("components", {})
        components.setdefault("securitySchemes", {})["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Identity assertion from the Mirror verifier",
        }
        # Document that /intel routes expect Bearer auth (enforced when identity required).
        for path, methods in schema.get("paths", {}).items():
            if not str(path).startswith("/intel"):
                continue
            for method_spec in methods.values():
                if isinstance(method_spec, dict):
                    method_spec.setdefault("security", [{"BearerAuth": []}])
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

# Replace scaffold /healthz with dependency-aware health.
app.router.routes = [
    route
    for route in app.router.routes
    if getattr(route, "path", None) != "/healthz"
]

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=os.environ.get(
        "MIRROR_UI_ORIGIN_REGEX",
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    ip = client_ip(request)
    log.warning(
        "rate_limit_hit",
        extra={
            "ip": ip,
            "session_id": "",
            "endpoint": request.url.path,
            "request_id": getattr(request.state, "request_id", ""),
        },
    )
    response = _rate_limit_exceeded_handler(request, exc)
    if isinstance(response, Response):
        return response  # type: ignore[return-value]
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests, please wait"},
        headers={"Retry-After": "60"},
    )


@app.middleware("http")
async def request_context_middleware(request: Request, call_next: Callable):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        status = getattr(response, "status_code", 500)
        path = request.url.path
        # Collapse dynamic segments for metric cardinality.
        metric_path = path
        for prefix in ("/intel/session/", "/intel/actions/", "/intel/score/", "/intel/scan/pending/"):
            if path.startswith(prefix) and path != prefix.rstrip("/"):
                metric_path = prefix + "{id}"
                break
        REQUEST_DURATION.labels(request.method, metric_path, str(status)).observe(
            duration_ms / 1000.0
        )
        log.info(
            "request",
            extra={
                "request_id": request_id,
                "session_id": "",
                "method": request.method,
                "path": path,
                "status": status,
                "duration_ms": round(duration_ms, 2),
                "ip": client_ip(request),
            },
        )
        if response is not None:
            response.headers["X-Request-ID"] = request_id
            response.headers["X-API-Version"] = CONTRACT_VERSION
            response.headers["Cache-Control"] = "no-store"


@app.get("/healthz")
async def healthz() -> dict:
    """Service contract health with optional dependency degradation."""
    deps: dict[str, str] = {}
    state = "HEALTHY"

    session_ok = store.healthy()
    deps["session_store"] = "ok" if session_ok else "unhealthy"
    if not session_ok:
        state = "UNHEALTHY"

    try:
        providers = provider_status()
        deps["llm"] = "ok" if providers.get("ready") else "degraded"
        if not providers.get("ready") and state == "HEALTHY":
            state = "DEGRADED"
    except Exception:
        deps["llm"] = "degraded"
        if state == "HEALTHY":
            state = "DEGRADED"

    if os.environ.get("ELEVENLABS_API_KEY"):
        deps["elevenlabs"] = "ok"
    else:
        deps["elevenlabs"] = "degraded"

    if os.environ.get("MIRROR_REDIS_URL"):
        deps["redis"] = "ok" if session_ok and store.backend_name.startswith("redis") else "unhealthy"
        if deps["redis"] != "ok":
            state = "UNHEALTHY"

    if MIRROR_ENV == "production" and not verifier.configured:
        deps["identity"] = "unhealthy"
        state = "UNHEALTHY"
    else:
        deps["identity"] = "ok" if (not verifier.required or verifier.configured) else "degraded"

    return {
        "state": state,
        "service": VERSION.service,
        "env": MIRROR_ENV,
        "mirror_env": MIRROR_ENV,
        "dependencies": deps,
        "api_version": CONTRACT_VERSION.split(".")[0] + ".0"
        if CONTRACT_VERSION
        else "1.0",
    }


@app.get("/metrics")
async def metrics() -> Response:
    try:
        SESSIONS_ACTIVE.set(float(store.stats().get("sessions") or 0))
    except Exception:
        pass
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/readyz")
async def readyz() -> dict:
    """Boot-time posture, in the order it matters for a demo.

    ``llm_provider == "offline"`` is the one to watch: the service is fully
    functional there, but remediation copy is canned and the UI must say so.
    """
    providers = provider_status()
    session_store_ready = store.healthy()
    event_bus_ready = await event_bus.healthy()
    ready = providers["ready"] and session_store_ready and event_bus_ready
    return {
        "state": "READY" if ready else "DEGRADED",
        "contract_version": CONTRACT_VERSION,
        "llm_provider": get_llm().provider.name,
        "hibp_key_configured": bool(os.environ.get("HIBP_API_KEY")),
        "mirror_env": MIRROR_ENV,
        "sessions": (
            store.stats()
            if session_store_ready
            else {
                "backend": store.backend_name,
                "ttl_seconds": store.ttl_seconds,
                "sessions": None,
                "findings": None,
            }
        ),
        "session_store_ready": session_store_ready,
        "event_bus": {
            "backend": event_bus.backend_name,
            "ready": event_bus_ready,
        },
        "workflow": runtime.status(),
        "identity": verifier.status(),
        "external_providers": providers,
        "design_rules_enforced": [
            "1 — no verified control, no scan (guardrails.assert_self)",
            "2 — no third-party traversal (guardrails.suppress_third_party)",
            "4 — redact at the boundary (redaction.assert_no_raw_pii)",
            "6 — untrusted text never reaches a tool-enabled model (quarantine)",
            "7 — nothing irreversible is claimed reversible (schema validator)",
        ],
    }


@app.on_event("startup")
async def startup_health_verification() -> None:
    """Fail closed when required production dependencies are missing."""
    redis_url = os.environ.get("MIRROR_REDIS_URL", "").strip()
    encryption_key = os.environ.get("MIRROR_SESSION_ENCRYPTION_KEY", "").strip()
    if MIRROR_ENV == "production":
        if not redis_url or not encryption_key:
            log.error("production requires MIRROR_REDIS_URL and MIRROR_SESSION_ENCRYPTION_KEY")
            raise SystemExit(1)
        if not verifier.configured and verifier.required:
            log.error("production identity required but verifier is not configured")
            raise SystemExit(1)
    if redis_url and not store.healthy():
        log.error("MIRROR_REDIS_URL set but Redis ping failed")
        raise SystemExit(1)

    providers = provider_status()
    log.info(
        "DDU Mirror starting in %s mode. Redis: %s. Identity: %s. LLM: %s. ElevenLabs: %s.",
        MIRROR_ENV,
        "connected" if store.backend_name.startswith("redis") else "disabled",
        "required" if verifier.required else "optional",
        get_llm().provider.name,
        "configured" if os.environ.get("ELEVENLABS_API_KEY") else "not configured",
        extra={
            "session_id": "",
            "request_id": "",
            "providers_ready": providers.get("ready"),
        },
    )


if __name__ == "__main__":
    log.info(
        "ddu-mirror-intel %s (contract %s) on :%d — provider=%s",
        __version__,
        CONTRACT_VERSION,
        PORT,
        get_llm().provider.name,
        extra={"session_id": "", "request_id": ""},
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)
