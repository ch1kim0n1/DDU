"""Abuse controls: per-IP and per-session budgets for expensive Mirror endpoints."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, Request
from slowapi import Limiter

log = logging.getLogger("ddu-mirror-intel.ratelimit")


def limits_enabled() -> bool:
    return os.environ.get("MIRROR_RATE_LIMIT", "1").lower() not in {"0", "false", "off", "no"}

# Per-session budgets (in-memory; resets with process — acceptable for demo/prod single-node).
VOICE_TURNS_PER_SESSION = 10
VISION_ANALYSES_PER_SESSION = 5
PROPOSAL_APPROVALS_PER_SESSION = 20
WS_CONNECTIONS_PER_IP = 3

_lock = threading.Lock()
_session_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_ws_by_ip: dict[str, int] = defaultdict(int)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _limiter_key(request: Request) -> str:
    return client_ip(request)


limiter = Limiter(key_func=_limiter_key, headers_enabled=True)
limiter.enabled = limits_enabled()


def ws_client_ip(websocket: Any) -> str:
    headers = {k.decode().lower(): v.decode() for k, v in websocket.headers.raw}
    forwarded = headers.get("x-forwarded-for") or headers.get("x-real-ip")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if websocket.client:
        return websocket.client.host
    return "unknown"


def _raise_429(endpoint: str, *, ip: str, session_id: str | None, detail: str) -> None:
    log.warning(
        "rate_limit_hit",
        extra={
            "ip": ip,
            "session_id": session_id or "",
            "endpoint": endpoint,
            "ts": time.time(),
        },
    )
    raise HTTPException(
        status_code=429,
        detail=detail,
        headers={
            "Retry-After": "60",
            "X-RateLimit-Limit": "0",
            "X-RateLimit-Remaining": "0",
        },
    )


def check_session_budget(
    *,
    endpoint: str,
    session_id: str,
    bucket: str,
    limit: int,
    ip: str = "unknown",
) -> None:
    if not limits_enabled():
        return
    with _lock:
        used = _session_counts[session_id][bucket]
        if used >= limit:
            _raise_429(
                endpoint,
                ip=ip,
                session_id=session_id,
                detail=f"Too many requests for this session ({bucket} limit {limit}). Please wait.",
            )
        _session_counts[session_id][bucket] = used + 1


def release_session(session_id: str) -> None:
    with _lock:
        _session_counts.pop(session_id, None)


def acquire_ws(ip: str) -> None:
    if not limits_enabled():
        return
    with _lock:
        if _ws_by_ip[ip] >= WS_CONNECTIONS_PER_IP:
            log.warning(
                "rate_limit_hit",
                extra={"ip": ip, "session_id": "", "endpoint": "ws", "ts": time.time()},
            )
            raise HTTPException(
                status_code=429,
                detail=f"Too many WebSocket connections from this IP (max {WS_CONNECTIONS_PER_IP}).",
            )
        _ws_by_ip[ip] += 1


def release_ws(ip: str) -> None:
    if not limits_enabled():
        return
    with _lock:
        if _ws_by_ip[ip] > 0:
            _ws_by_ip[ip] -= 1
        if _ws_by_ip[ip] == 0:
            _ws_by_ip.pop(ip, None)


def reset_for_tests() -> None:
    with _lock:
        _session_counts.clear()
        _ws_by_ip.clear()


def rate_limit_headers(session_id: str | None = None) -> dict[str, str]:
    """Optional response headers for remaining session budgets."""
    if not session_id:
        return {}
    with _lock:
        counts = _session_counts.get(session_id, {})
    return {
        "X-RateLimit-Voice-Remaining": str(
            max(0, VOICE_TURNS_PER_SESSION - int(counts.get("voice", 0)))
        ),
        "X-RateLimit-Vision-Remaining": str(
            max(0, VISION_ANALYSES_PER_SESSION - int(counts.get("vision", 0)))
        ),
        "X-RateLimit-Approve-Remaining": str(
            max(0, PROPOSAL_APPROVALS_PER_SESSION - int(counts.get("approve", 0)))
        ),
    }


def stats() -> dict[str, Any]:
    with _lock:
        return {
            "tracked_sessions": len(_session_counts),
            "ws_by_ip": dict(_ws_by_ip),
        }
