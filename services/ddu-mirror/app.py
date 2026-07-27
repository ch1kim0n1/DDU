"""DDU Mirror — Engineer A's trust spine and consent platform."""
from __future__ import annotations

import asyncio
import os
from typing import Any

import uvicorn
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ddu_common.app import build_scaffold_app
from ddu_common.lineage import Event, LineageEmitter, Output
from ddu_common.version import ServiceVersion, from_env
from mirror_platform import __version__
from mirror_platform.personas import PERSONAS, PERSONA_WEIGHTS
from mirror_platform.store import ReceiptSigner, TrustError, build_store, redact, receipt_for

VERSION = from_env(ServiceVersion(service="ddu-mirror", service_version=__version__, tool="ddu-mirror-trust-spine", tool_version="1.0.0"))
app = build_scaffold_app(VERSION)
store = build_store()
signer = ReceiptSigner()
lineage = LineageEmitter(VERSION)


class StartOnboarding(BaseModel):
    email: str
    adult_confirmed: bool
    persona: str = "scammer"
    guess_first: str | None = Field(default=None, max_length=500)


class VerifyCode(BaseModel):
    challenge_id: str
    code: str = Field(pattern=r"^\d{6}$")


class SessionRequest(BaseModel):
    session_id: str


class BiometricConsent(SessionRequest):
    accepted: bool


class FindingsIngest(SessionRequest):
    findings: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


def failure(exc: TrustError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.payload())


@app.middleware("http")
async def lineage_for_invocation(request: Request, call_next):
    """All Part A API invocations emit best-effort lineage without PII."""
    if not request.url.path.startswith("/v1/"):
        return await call_next(request)
    run_id = lineage.new_run_id()
    job_name = f"ddu-mirror:http:{request.method.lower()}"
    lineage.emit(Event(event_type="START", run_id=run_id, job_name=job_name))
    try:
        response = await call_next(request)
    except Exception:
        lineage.emit(Event(event_type="FAIL", run_id=run_id, job_name=job_name))
        raise
    lineage.emit(Event(
        event_type="COMPLETE" if response.status_code < 500 else "FAIL",
        run_id=run_id,
        job_name=job_name,
        outputs=[Output(namespace="ddu.mirror", name=str(response.status_code), type="DDU.HTTP_RESPONSE")],
    ))
    return response


@app.get("/v1/personas")
async def personas() -> dict[str, Any]:
    return {"personas": PERSONAS, "weights": PERSONA_WEIGHTS}


@app.post("/v1/onboarding/start")
async def onboarding_start(body: StartOnboarding) -> dict[str, Any]:
    try:
        challenge, code = store.issue_code(body.email, adult_confirmed=body.adult_confirmed, persona=body.persona, guess=body.guess_first)
    except TrustError as exc:
        raise failure(exc) from exc
    response = {"challenge_id": challenge.id, "delivery": "email", "expires_at": challenge.expires_at.isoformat(), "attempt_limit": 3}
    if os.getenv("MIRROR_EXPOSE_DEV_CODES", "true").lower() == "true":
        response["development_code"] = code
    return response


@app.post("/v1/onboarding/verify")
async def onboarding_verify(body: VerifyCode) -> dict[str, Any]:
    try:
        session = store.verify_code(body.challenge_id, body.code)
    except TrustError as exc:
        raise failure(exc) from exc
    await store.broadcast(session.id, {"event": "session.verified", "session": session.snapshot()})
    return session.snapshot()


@app.get("/v1/sessions/{session_id}")
async def session_snapshot(session_id: str) -> dict[str, Any]:
    try:
        return store.get(session_id).snapshot()
    except TrustError as exc:
        raise failure(exc) from exc


@app.post("/v1/scans/authorize")
async def authorize_scan(body: SessionRequest) -> dict[str, Any]:
    """Issue the verified-identity capability. No target can be supplied."""
    try:
        session = store.authorize_scan(body.session_id)
    except TrustError as exc:
        raise failure(exc) from exc
    return {"session_id": session.id, "verified_identity": {"email": redact(session.email), "verified": True}, "authorized": True, "rule": "No verified control → no scan."}


@app.post("/v1/consent/biometric")
async def biometric_consent(body: BiometricConsent) -> dict[str, Any]:
    try:
        session = store.biometric_consent(body.session_id, body.accepted)
    except TrustError as exc:
        raise failure(exc) from exc
    await store.broadcast(session.id, {"event": "biometric.consent" if body.accepted else "biometric.skipped", "session": session.snapshot()})
    return session.snapshot()


@app.post("/v1/reverify/start")
async def reverify_start(body: SessionRequest) -> dict[str, Any]:
    try:
        challenge, code = store.issue_step_up(body.session_id)
    except TrustError as exc:
        raise failure(exc) from exc
    response = {"challenge_id": challenge.id, "delivery": "email", "expires_at": challenge.expires_at.isoformat(), "attempt_limit": 3}
    if os.getenv("MIRROR_EXPOSE_DEV_CODES", "true").lower() == "true":
        response["development_code"] = code
    return response


@app.post("/v1/reverify/confirm")
async def reverify_confirm(body: VerifyCode) -> dict[str, Any]:
    try:
        session = store.verify_code(body.challenge_id, body.code)
    except TrustError as exc:
        raise failure(exc) from exc
    return session.snapshot()


@app.post("/v1/findings")
async def findings_ingest(body: FindingsIngest) -> dict[str, Any]:
    """Part A's WebSocket gateway for the findings contract owned by Part B."""
    try:
        session = store.add_findings(body.session_id, body.findings)
    except TrustError as exc:
        raise failure(exc) from exc
    for finding in body.findings:
        await store.broadcast(session.id, {"event": "finding.new", "finding": {k: v for k, v in finding.items() if k not in {"email", "coordinates", "raw_value", "subject_ref"}}})
    return {"accepted": len(body.findings), "session_id": session.id}


@app.get("/v1/sessions/{session_id}/audit")
async def audit_log(session_id: str) -> dict[str, Any]:
    try:
        return {"session_id": session_id, "events": store.audit(session_id)}
    except TrustError as exc:
        raise failure(exc) from exc


@app.post("/v1/sessions/{session_id}/receipt")
async def consent_receipt(session_id: str) -> dict[str, Any]:
    try:
        session = store.get(session_id)
    except TrustError as exc:
        raise failure(exc) from exc
    return signer.sign(receipt_for(session))


@app.delete("/v1/sessions/{session_id}")
async def wipe_session(session_id: str) -> dict[str, Any]:
    try:
        session = store.get(session_id)
        # Subscribers must receive this while their queues still exist.  Once
        # the event is sent, the next operation destroys the queue and every
        # data-bearing value in the session.
        await store.broadcast(session_id, {"event": "session.wiped", "destroyed": {"findings": len(session.findings), "face_template": int(session.biometric_expires_at is not None)}})
        counts = store.destroy(session_id)
    except TrustError as exc:
        raise failure(exc) from exc
    return {"destroyed": counts, "message": "Session data, findings, and biometric template were destroyed."}


@app.websocket("/v1/sessions/{session_id}/events")
async def findings_stream(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        queue = store.subscribe(session_id)
    except TrustError:
        await websocket.close(code=4404)
        return
    try:
        await websocket.send_json({"event": "stream.ready", "session_id": session_id})
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        store.unsubscribe(session_id, queue)


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    backend = "Redis TTL store" if os.getenv("MIRROR_REDIS_URL") else "in-memory development TTL store"
    return {"state": "READY", "session_backend": backend, "design_rules_enforced": ["No verified control → no scan", "No free-text target field", "One active scan per verified identity", "Ephemeral sessions with explicit wipe", "Separate biometric consent and skip path"]}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8130")))
