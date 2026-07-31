"""FastAPI router — Engineer B's surface for A, C, and D.

Mountable, not an app: Engineer A owns the app skeleton, so this exposes an
``APIRouter`` that mounts at ``/intel``. ``app.py`` also wraps it in a
standalone app so B is never blocked on A's service landing.

The shape of this surface is the Track 3 argument made concrete:

    POST /intel/scan/plan            → agent drafts proposals (nothing runs)
    GET  /intel/scan/pending         → what's awaiting a human
    POST /intel/scan/approve         → human says yes  → work runs
    POST /intel/scan/edit            → human amends    → work runs
    POST /intel/scan/reject          → human says no   → nothing runs
    POST /intel/scan/cancel          → kill switch
    GET  /intel/actions              → the append-only log

There is no endpoint that runs discovery directly, and no ``target`` parameter
anywhere in this file. Both absences are load-bearing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import secrets
from contextvars import ContextVar
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from . import actionlog as A
from . import orchestrator as orch
from .events import event_bus
from .guardrails import TargetRefusedError, VerifiedIdentity
from .identity import IdentityVerificationError, verifier
from .llm import get_llm
from .mock import demo_identity, generate
from .personas import PERSONAS, load_persona_weights
from .providers import provider_status
from .quarantine import classify_injection, parse_untrusted
from .audit_persist import append_action, read_audit_log
from .env import is_production, refuse_dev_session_features
from .lineage_hooks import lineage_run
from .ratelimit import (
    PROPOSAL_APPROVALS_PER_SESSION,
    VOICE_TURNS_PER_SESSION,
    acquire_ws,
    check_session_budget,
    client_ip,
    limiter,
    limits_enabled,
    release_session,
    release_ws,
    ws_client_ip,
)
from .records import jurisdictions, personalize
from .remediation import build_checklist
from .schema import CONTRACT_VERSION, Finding, Origin, SessionSnapshot
from .session import SessionConflictError, store
from .vision.routes import cleanup_session_vision, router as vision_router
from .voice import VoiceConfigurationError, answer_turn
from .workflow import WorkflowDecisionError, runtime

log = logging.getLogger("mirror-intel.api")

router = APIRouter(prefix="/intel", tags=["mirror-intel"])
router.include_router(vision_router)

load_persona_weights()
_suppress_broadcast: ContextVar[bool] = ContextVar(
    "mirror_suppress_broadcast", default=False
)


# ── request models ───────────────────────────────────────────────────────
# Note what none of these have: a free-text target. A session is created from
# an already-verified identity set handed over by Engineer A's identity gate.


class SessionCreate(BaseModel):
    session_id: str | None = Field(
        default=None,
        description="Optional client-supplied session id; server may replace it.",
        examples=["sess_demo_abc123"],
    )
    emails: list[str] = Field(
        default_factory=list,
        description="Verified emails the subject controls.",
        examples=[["you@example.com"]],
    )
    handles: list[str] = Field(
        default_factory=list,
        description="Verified social handles without leading @.",
        examples=[["alice"]],
    )
    account_urls: list[str] = Field(
        default_factory=list,
        description="Verified profile URLs.",
        examples=[["https://linkedin.com/in/you"]],
    )
    persona: str = Field(
        default="scammer",
        description="Threat model persona key.",
        examples=["scammer"],
    )
    #: Populate the graph with mock findings so C and D can build against a
    #: full scene without waiting for real discovery.
    seed_mock_findings: bool = Field(
        default=False,
        description="Seed mock findings (blocked in production).",
        examples=[True],
    )


class PlanRequest(BaseModel):
    session_id: str = Field(..., description="Active session id", examples=["sess_demo_abc123"])
    #: Context the human supplied in onboarding — jurisdiction for the records
    #: advisor, a pasted bio for the quarantine demo.
    state: str | None = Field(default=None, description="US state code", examples=["TX"])
    county: str | None = Field(default=None, description="County name", examples=["Travis"])
    scraped_bio: str | None = Field(default=None, description="Optional pasted bio for quarantine demo")
    bio_source: str | None = Field(default=None, description="Source label for scraped_bio")


class DecisionRequest(BaseModel):
    session_id: str = Field(..., description="Active session id", examples=["sess_demo_abc123"])
    proposal_id: str = Field(..., description="Proposal awaiting approval", examples=["prop_1"])
    reason: str | None = Field(default=None, description="Optional human reason for reject/edit")


class EditRequest(DecisionRequest):
    changes: dict[str, Any] = Field(default_factory=dict)


class FindingIngest(BaseModel):
    """Findings produced outside the discovery workers — Engineer C's vision layer.

    Note there is no approval gate on this path, and that is deliberate rather
    than an oversight. The human chose the file and pressed upload; that *is*
    the consent act. Making them approve a second time before we read EXIF
    from a photo they just handed us is ceremony, not control — and Track 3
    is worth more when the gates are where decisions actually are. Every
    ingested finding is still individually rejectable through the correction
    loop, and still fails closed on `subject_ref`.
    """

    session_id: str
    #: Schema-valid Finding payloads. Validated against the contract on the
    #: way in, so a producer drifting from the schema fails loudly here rather
    #: than silently corrupting the graph.
    findings: list[dict[str, Any]] = Field(default_factory=list)
    #: reveal_token -> raw value, for the session vault. Producers hand raw
    #: values over here so the vault stays the only place they live.
    raw_values: dict[str, str] = Field(default_factory=dict)
    producer: str = "unknown"


class FindingDecision(BaseModel):
    session_id: str
    finding_id: str
    reason: str | None = None


class FindingEdit(FindingDecision):
    changes: dict[str, str] = Field(default_factory=dict)


class PersonaRequest(BaseModel):
    session_id: str
    persona: str


class SimulateRequest(BaseModel):
    session_id: str
    fixed_finding_ids: list[str] = Field(default_factory=list)


class RevealRequest(BaseModel):
    session_id: str
    finding_id: str
    evidence_key: str
    reveal_token: str


class QuarantineRequest(BaseModel):
    text: str
    #: False sends the payload to the tool-less model anyway, to show on stage
    #: that it holds the line too.
    skip_model_on_injection: bool = True


class RecordsRequest(BaseModel):
    state: str
    county: str | None = None
    persona: str = "scammer"


class VoiceTurnRequest(BaseModel):
    session_id: str
    transcript: str | None = None
    audio_base64: str | None = None
    mime_type: str = "audio/webm"
    mode: str = "question"


def _session(session_id: str):
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
    return session


def _persist(session) -> None:
    try:
        store.persist(session)
    except SessionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _broadcast(
    session_id: str,
    event: str,
    *,
    session=None,
    payload: dict[str, Any] | None = None,
    request_id: str = "",
) -> None:
    if _suppress_broadcast.get():
        return
    current = session or store.get(session_id)
    snapshot = current.snapshot().model_dump(mode="json") if current else None
    await event_bus.publish(
        session_id,
        event,
        snapshot=snapshot,
        payload=payload,
        request_id=request_id,
    )


def _bearer(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


# ── contract & metadata ──────────────────────────────────────────────────


@router.get("/contract")
async def contract() -> dict[str, Any]:
    """The locked findings contract. C and D validate against this."""
    return {
        "contract_version": CONTRACT_VERSION,
        "finding_schema": Finding.model_json_schema(),
        "personas": {k: {"label": v.label, "description": v.description} for k, v in PERSONAS.items()},
        "jurisdictions": jurisdictions(),
        "websocket_events": [
            "finding.new",
            "finding.updated",
            "finding.rejected",
            "score.changed",
            "agent.awaiting_approval",
            "session.wiped",
        ],
        "llm_provider": get_llm().provider.name,
        "workflow": runtime.status(),
        "session_store": {
            "backend": store.backend_name,
            "ttl_seconds": store.ttl_seconds,
        },
        "identity": verifier.status(),
        "event_bus": event_bus.backend_name,
    }


# ── session lifecycle ────────────────────────────────────────────────────


@router.post("/session", tags=["Sessions"])
@limiter.limit("5/hour", exempt_when=lambda: not limits_enabled())
async def create_session(
    request: Request,
    body: SessionCreate,
    response: Response,
) -> dict[str, Any]:
    """Register a session from an already-verified identity set.

    The caller is Engineer A's identity gate, after a code loop or OAuth. This
    endpoint trusts the set it is given and treats it as the ceiling — every
    downstream worker refuses anything outside it.

    ``response`` is required by slowapi when ``headers_enabled=True`` and the
    handler returns a dict (not a Response instance).
    """
    refused = refuse_dev_session_features(
        seed_mock=body.seed_mock_findings,
        session_id=body.session_id,
    )
    if refused:
        raise HTTPException(status_code=400, detail=refused)

    token = _bearer(request)
    assertion = None
    if token or verifier.required:
        try:
            assertion = verifier.verify(token)
        except IdentityVerificationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    if assertion is not None:
        session_id = f"sess_{secrets.token_urlsafe(18)}"
        identity = assertion.build_identity(session_id)
    else:
        if is_production():
            raise HTTPException(
                status_code=401,
                detail="production requires a verified identity assertion",
            )
        session_id = body.session_id or f"sess_dev_{secrets.token_urlsafe(12)}"
        if not (body.emails or body.handles or body.account_urls):
            raise HTTPException(
                status_code=400,
                detail="a session needs at least one verified identifier; complete verification first",
            )
        identity = VerifiedIdentity.build(
            session_id=session_id,
            emails=body.emails,
            handles=body.handles,
            account_urls=body.account_urls,
        )
    if verifier.required and body.seed_mock_findings:
        raise HTTPException(
            status_code=400,
            detail="mock findings cannot be seeded in production identity mode",
        )
    with lineage_run("mirror.session.create", session_id=session_id):
        session = store.create(
            identity, persona=body.persona, created_ip=client_ip(request)
        )

        if body.seed_mock_findings:
            session.add_findings(generate(identity))
            session.log.record(
                A.FINDING_ADDED,
                actor=Origin.SYSTEM,
                subject=session.session_id,
                detail="Mock findings seeded for frontend development — NOT REAL DATA.",
                mock=True,
            )
        _persist(session)
        for entry in session.log.entries():
            append_action(session.session_id, entry.model_dump(mode="json"))
    await _broadcast(session.session_id, "session.created", session=session)

    return {
        "session_id": session.session_id,
        "persona": session.persona,
        "verified_identifier_count": len(identity.all_identifiers),
        "findings": len(session.findings),
        "snapshot": session.snapshot().model_dump(mode="json"),
        "identity_verification": (
            "signed-assertion" if assertion is not None else "development"
        ),
        "session_backend": store.backend_name,
        "expires_in_seconds": store.ttl_seconds,
    }


@router.get("/session/{session_id}", response_model=SessionSnapshot, tags=["Sessions"])
async def get_snapshot(request: Request, session_id: str) -> SessionSnapshot:
    """Everything D needs to render, in one call."""
    store.note_access_ip(session_id, client_ip(request))
    return _session(session_id).snapshot()


@router.get("/session/{session_id}/export", tags=["Sessions"])
async def export_session(session_id: str) -> dict[str, Any]:
    """GDPR data-subject export: findings, action log, identity (no vault secrets)."""
    session = _session(session_id)
    state = session.export_state()
    state.pop("vault", None)
    state["exported_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
    state["note"] = "Raw vault secrets are never exported. Wipe destroys them."
    return state


@router.get("/session/{session_id}/audit-log")
async def session_audit_log(session_id: str) -> dict[str, Any]:
    """Append-only audit trail for compliance. Combines live + persisted JSONL."""
    session = store.get(session_id)
    live = (
        [e.model_dump(mode="json") for e in session.log.entries()]
        if session is not None
        else []
    )
    persisted = read_audit_log(session_id)
    # Prefer the longer append-only file when present.
    entries = persisted if len(persisted) >= len(live) else live
    return {
        "session_id": session_id,
        "append_only": True,
        "count": len(entries),
        "entries": entries,
    }


@router.delete("/session/{session_id}")
async def wipe_session(session_id: str) -> dict[str, Any]:
    """Ephemeral guarantee, made visible.

    Returns what was destroyed so the wipe animation has real counts to render
    rather than a spinner over an empty promise.
    """
    session = _session(session_id)
    counts = session.wipe()
    release_session(session_id)
    session.log.record(
        A.SESSION_WIPED,
        actor=Origin.SYSTEM,
        subject=session_id,
        detail=f"Session destroyed: {counts['findings']} findings, "
        f"{counts['vault_entries']} raw values, {counts['attack_paths']} attack paths.",
        **counts,
    )
    tail = [e.model_dump(mode="json") for e in session.log.tail(40)]
    summary = session.log.summary()
    await _broadcast(
        session_id,
        "session.wiped",
        session=session,
        payload={"destroyed": counts, "action_log_summary": summary},
    )
    store.drop(session_id)
    orch.drop_session(session_id)
    cleanup_session_vision(session_id)
    return {"destroyed": counts, "action_log": tail, "action_log_summary": summary}


# ── the human-in-the-loop cycle ──────────────────────────────────────────


@router.post("/scan/plan")
async def plan(body: PlanRequest) -> dict[str, Any]:
    """Agent drafts what it would like to do. **Nothing runs.**"""
    session = _session(body.session_id)
    orchestrator = orch.for_session(session)
    proposals = orchestrator.plan(
        {
            "state": body.state,
            "county": body.county,
            "scraped_bio": body.scraped_bio,
            "bio_source": body.bio_source,
        }
    )
    _persist(session)
    checkpoints = {
        proposal.id: runtime.arm(body.session_id, proposal.id) for proposal in proposals
    }
    await _broadcast(
        body.session_id,
        "agent.awaiting_approval",
        payload={"proposal_ids": [proposal.id for proposal in proposals]},
    )
    return {
        "session_id": body.session_id,
        "event": "agent.awaiting_approval",
        "proposals": [p.model_dump(mode="json") for p in proposals],
        "pending_total": len(orchestrator.pending()),
        "note": "No discovery has run. Each proposal needs approve, edit, or reject.",
        "workflow": {
            "runtime": "langgraph",
            "checkpoint_backend": runtime.backend,
            "checkpoints": checkpoints,
        },
    }


@router.get("/scan/pending/{session_id}")
async def pending(session_id: str) -> dict[str, Any]:
    orchestrator = orch.for_session(_session(session_id))
    return {
        "session_id": session_id,
        "pending": [p.model_dump(mode="json") for p in orchestrator.pending()],
    }


def _run(session_id: str, proposal_id: str) -> dict[str, Any]:
    session = _session(session_id)
    orchestrator = orch.for_session(session)
    try:
        added, meta = orchestrator.execute(proposal_id)
    except TargetRefusedError as exc:
        # Design rule 1, surfacing as a 403 with an explanation. This is the
        # response the live refusal demo puts on screen.
        raise HTTPException(status_code=403, detail=exc.as_payload()) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    assert session.score is not None
    return {
        "session_id": session_id,
        "proposal_id": proposal_id,
        "findings": [f.model_dump(mode="json") for f in added],
        "worker_meta": meta,
        "score": session.score.model_dump(mode="json"),
        "attack_paths": [p.model_dump(mode="json") for p in session.attack_paths],
        "attribution": [a.model_dump(mode="json") for a in session.attribution],
    }


async def _approve_impl(body: DecisionRequest, *, ip: str) -> dict[str, Any]:
    check_session_budget(
        endpoint="/intel/scan/approve",
        session_id=body.session_id,
        bucket="approve",
        limit=PROPOSAL_APPROVALS_PER_SESSION,
        ip=ip,
    )
    try:
        result = runtime.resume(
            body.session_id,
            body.proposal_id,
            action="approve",
            reason=body.reason,
        )
    except WorkflowDecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    await _broadcast(body.session_id, "finding.new", payload=result)
    return result


@router.post("/scan/approve")
async def approve(body: DecisionRequest, request: Request) -> dict[str, Any]:
    """Human approves; the work then runs."""
    return await _approve_impl(body, ip=client_ip(request))


@router.post("/scan/edit")
async def edit_proposal(body: EditRequest) -> dict[str, Any]:
    """Human amends the draft, then it runs.

    Only inputs the step declares editable are applied; anything else is
    reported back in ``ignored`` rather than silently dropped.
    """
    try:
        result = runtime.resume(
            body.session_id,
            body.proposal_id,
            action="edit",
            changes=body.changes,
            reason=body.reason,
        )
    except WorkflowDecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    result["applied_edit"] = result["proposal"].get("human_edit")
    await _broadcast(body.session_id, "finding.new", payload=result)
    return result


@router.post("/scan/reject")
async def reject_proposal(body: DecisionRequest) -> dict[str, Any]:
    """Human declines. Nothing runs, and the decision is logged."""
    try:
        result = runtime.resume(
            body.session_id,
            body.proposal_id,
            action="reject",
            reason=body.reason,
        )
    except WorkflowDecisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    await _broadcast(body.session_id, "finding.updated", payload=result)
    return result


@router.post("/scan/cancel")
async def cancel(body: PlanRequest) -> dict[str, Any]:
    """Kill switch. Halts the agent and drops everything pending."""
    session = _session(body.session_id)
    orchestrator = orch.for_session(session)
    dropped = orchestrator.cancel()
    _persist(session)
    result = {
        "session_id": body.session_id,
        "cancelled": True,
        "dropped_actions": dropped,
        "note": "Findings already approved remain; nothing further will run.",
    }
    await _broadcast(body.session_id, "finding.updated", session=session, payload=result)
    return result


@router.get("/scan/next-moves/{session_id}")
async def next_moves(session_id: str) -> dict[str, Any]:
    """What an attacker would try next — hypotheses only, never executed."""
    orchestrator = orch.for_session(_session(session_id))
    return {
        "session_id": session_id,
        "hypotheses": orchestrator.hypothesize_next_moves(),
        "note": "Labelled hypotheses. There is no endpoint that executes these.",
    }


# ── correction loop ──────────────────────────────────────────────────────


@router.post("/findings/ingest")
async def ingest_findings(body: FindingIngest) -> dict[str, Any]:
    """Accept findings from a producer outside the discovery workers.

    This is Engineer C's door into the graph — EXIF, object detection,
    location inference, face linkage. Once through, they are ordinary
    findings: they score, they chain into attack paths, they cascade when
    rejected, and they refuse to be marked fixed if they're irreversible.

    Two things are enforced here rather than trusted:

    * **Schema validity.** Payloads are parsed through the real ``Finding``
      model, so a producer that drifts from the contract gets a 422 naming the
      field instead of quietly poisoning the score.
    * **Subject ownership.** ``subject_ref`` is overwritten with this
      session's verified seed, never read from the payload. A producer cannot
      inject a finding about someone else even by accident — design rule 2.
    """
    session = _session(body.session_id)

    parsed: list[Finding] = []
    errors: list[dict[str, Any]] = []
    for index, payload in enumerate(body.findings):
        try:
            # Force the subject rather than validating it. Trusting a producer
            # to set this correctly is a rule-2 hole waiting to happen.
            parsed.append(Finding(**{**payload, "subject_ref": session.identity.subject_ref}))
        except (ValidationError, TypeError) as exc:
            errors.append({"index": index, "id": payload.get("id"), "error": str(exc)[:400]})

    if errors and not parsed:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "no_valid_findings",
                "contract_version": CONTRACT_VERSION,
                "rejected": errors,
            },
        )

    added = session.add_findings(parsed, raw_values=body.raw_values or None)

    session.log.record(
        A.FINDING_ADDED,
        actor=Origin.SYSTEM,
        subject=body.producer,
        detail=f"{body.producer} contributed {len(added)} finding(s)"
        + (f"; {len(errors)} rejected as schema-invalid" if errors else "."),
        producer=body.producer,
        accepted=len(added),
        rejected=len(errors),
    )
    for finding in added:
        session.log.record(
            A.FINDING_ADDED,
            actor=Origin.AGENT,
            subject=finding.id,
            detail=finding.label,
            type=finding.type.value,
            producer=body.producer,
        )

    assert session.score is not None
    _persist(session)
    response = {
        "session_id": body.session_id,
        "producer": body.producer,
        "accepted": [f.model_dump(mode="json") for f in added],
        "rejected": errors,
        "score": session.score.model_dump(mode="json"),
        "attack_paths": [p.model_dump(mode="json") for p in session.attack_paths],
        "attribution": [a.model_dump(mode="json") for a in session.attribution],
    }
    await _broadcast(body.session_id, "finding.new", session=session, payload=response)
    return response


@router.post("/findings/reject")
async def reject_finding(body: FindingDecision) -> dict[str, Any]:
    """"That's not me." Prunes the node, cascades, breaks paths, corrects the score."""
    session = _session(body.session_id)
    try:
        result = session.reject_finding(body.finding_id, body.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    session.log.record(
        A.FINDING_REJECTED,
        actor=Origin.HUMAN,
        subject=body.finding_id,
        detail=f"Operator rejected the finding; {len(result.cascaded_ids)} downstream "
        f"finding(s) lost their supporting evidence.",
        cascaded=result.cascaded_ids,
        broken_paths=result.broken_path_ids,
        reason=body.reason,
    )
    assert session.score is not None
    _persist(session)
    response = {
        "rejected": body.finding_id,
        "cascaded": result.cascaded_ids,
        "broken_paths": result.broken_path_ids,
        "score": session.score.model_dump(mode="json"),
        "snapshot": session.snapshot().model_dump(mode="json"),
    }
    await _broadcast(
        body.session_id, "finding.rejected", session=session, payload=response
    )
    return response


@router.post("/findings/restore")
async def restore_finding(body: FindingDecision) -> dict[str, Any]:
    """Undo a rejection. Human control that only works one way isn't control."""
    session = _session(body.session_id)
    try:
        result = session.restore_finding(body.finding_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.log.record(
        A.FINDING_RESTORED,
        actor=Origin.HUMAN,
        subject=body.finding_id,
        detail="Operator withdrew a rejection; descendants restored as 'likely'.",
        cascaded=result.cascaded_ids,
    )
    assert session.score is not None
    _persist(session)
    response = {
        "restored": body.finding_id,
        "cascaded": result.cascaded_ids,
        "score": session.score.model_dump(mode="json"),
    }
    await _broadcast(
        body.session_id, "finding.updated", session=session, payload=response
    )
    return response


@router.post("/findings/edit")
async def edit_finding(body: FindingEdit) -> dict[str, Any]:
    """Human corrects a finding's description. Computed fields stay computed."""
    session = _session(body.session_id)
    try:
        applied = session.edit_finding(body.finding_id, body.changes, body.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.log.record(
        A.FINDING_EDITED,
        actor=Origin.HUMAN,
        subject=body.finding_id,
        detail=f"Operator edited: {', '.join(applied) or 'no editable field supplied'}",
        applied=sorted(applied),
        ignored=sorted(set(body.changes) - set(applied)),
    )
    _persist(session)
    response = {"finding_id": body.finding_id, "applied": applied}
    await _broadcast(
        body.session_id, "finding.updated", session=session, payload=response
    )
    return response


@router.post("/findings/reveal")
async def reveal(body: RevealRequest) -> dict[str, Any]:
    """Exchange a reveal token for a raw value. Logged, because it's a choice."""
    session = _session(body.session_id)
    value = session.reveal(body.finding_id, body.evidence_key, body.reveal_token)
    if value is None:
        raise HTTPException(status_code=403, detail="invalid or expired reveal token")
    session.log.record(
        A.REVEAL,
        actor=Origin.HUMAN,
        subject=body.finding_id,
        detail=f"Operator revealed the raw value for '{body.evidence_key}'.",
        evidence_key=body.evidence_key,
    )
    _persist(session)
    return {"finding_id": body.finding_id, "evidence_key": body.evidence_key, "value": value}


# ── scoring, persona, remediation ────────────────────────────────────────


@router.post("/persona")
async def set_persona(body: PersonaRequest) -> dict[str, Any]:
    """Re-rank for a different threat model. The findings do not change."""
    if body.persona not in PERSONAS:
        raise HTTPException(status_code=400, detail=f"unknown persona {body.persona}")
    session = _session(body.session_id)
    before = session.score.score if session.score else 0
    score = session.set_persona(body.persona)
    session.log.record(
        A.PERSONA_CHANGED,
        actor=Origin.HUMAN,
        subject=body.persona,
        detail=f"Threat model changed to {PERSONAS[body.persona].label}; "
        f"score moved {before} → {score.score}. Findings unchanged.",
        before=before,
        after=score.score,
    )
    _persist(session)
    response = {
        "persona": body.persona,
        "score_before": before,
        "score": score.model_dump(mode="json"),
        "attribution": [a.model_dump(mode="json") for a in session.attribution],
        "note": "Same findings, re-ranked. Nothing was rescanned.",
    }
    await _broadcast(
        body.session_id, "score.changed", session=session, payload=response
    )
    return response


@router.get("/score/{session_id}")
async def score(session_id: str) -> dict[str, Any]:
    session = _session(session_id)
    assert session.score is not None
    return session.score.model_dump(mode="json")


@router.post("/simulate")
async def simulate(body: SimulateRequest) -> dict[str, Any]:
    """Project the score if these were fixed. Irreversible findings refuse.

    ``refused`` is what makes the remediation-simulation node visibly decline
    to go dark — the honest version of the control panel.
    """
    session = _session(body.session_id)
    projected, refused = session.simulate(body.fixed_finding_ids)
    assert session.score is not None

    for finding_id in body.fixed_finding_ids:
        if finding_id in refused:
            session.log.record(
                A.FIX_REFUSED,
                actor=Origin.SYSTEM,
                subject=finding_id,
                detail="Cannot be marked fixed — the exposure is irreversible. A "
                "compensating control is offered instead.",
                design_rule="7 — nothing irreversible is claimed reversible",
            )
        else:
            session.log.record(
                A.MARKED_FIXED,
                actor=Origin.HUMAN,
                subject=finding_id,
                detail="Operator marked this remediated (simulation).",
            )

    _persist(session)
    response = {
        "score_now": session.score.model_dump(mode="json"),
        "score_projected": projected.model_dump(mode="json"),
        "refused": refused,
        "refused_reason": "These exposures cannot be undone. See each finding's "
        "compensating control." if refused else None,
    }
    await _broadcast(
        body.session_id, "score.changed", session=session, payload=response
    )
    return response


@router.get("/remediation/{session_id}")
async def remediation(session_id: str, with_copy: bool = True) -> dict[str, Any]:
    """Severity × effort ordered checklist, with persona-specific framing."""
    session = _session(session_id)
    checklist = build_checklist(session.findings, session.persona, with_copy=with_copy)
    return checklist.as_dict()


@router.get("/voice/status")
async def voice_status() -> dict[str, Any]:
    status = provider_status()
    return {
        "stt": status["providers"]["elevenlabs_stt"],
        "tts": status["providers"]["elevenlabs_tts"],
        "llm": status["providers"]["llm"],
        "required": status["require_elevenlabs"],
        "ready": not any(
            name.startswith("elevenlabs") for name in status["missing_required"]
        ),
        "pii_boundary": "scrub_text before LLM and TTS; raw transcript is never returned",
    }


@router.get("/providers/status", tags=["Health"])
async def providers_status() -> dict[str, Any]:
    """Deployment posture without exposing credential values."""
    return provider_status()


@router.get("/providers", tags=["Health"])
async def providers_summary() -> dict[str, str]:
    """Compact LLM/provider availability for the UI status indicator."""
    status = provider_status()
    llm = status.get("providers", {}).get("llm", {})
    anthropic = "available" if os.environ.get("ANTHROPIC_API_KEY") else "not_configured"
    openai = "available" if os.environ.get("OPENAI_API_KEY") else "not_configured"
    return {
        "anthropic": anthropic,
        "openai": openai,
        "local": "available",
        "llm": "available" if llm.get("ready") or llm.get("configured") else "degraded",
        "elevenlabs": (
            "available"
            if os.environ.get("ELEVENLABS_API_KEY")
            else "not_configured"
        ),
        "redis": "connected" if store.backend_name.startswith("redis") else "disabled",
    }


@router.post("/voice/turn")
async def voice_turn(body: VoiceTurnRequest, request: Request) -> dict[str, Any]:
    """STT -> local PII scrub -> grounded voice-tier LLM -> scrub -> TTS."""
    check_session_budget(
        endpoint="/intel/voice/turn",
        session_id=body.session_id,
        bucket="voice",
        limit=VOICE_TURNS_PER_SESSION,
        ip=client_ip(request),
    )
    session = _session(body.session_id)
    if body.mode not in {"question", "narrate"}:
        raise HTTPException(status_code=400, detail="mode must be question or narrate")
    if body.mode == "question" and not (body.transcript or body.audio_base64):
        raise HTTPException(status_code=400, detail="provide transcript or audio_base64")
    try:
        result = await answer_turn(
            session,
            transcript=body.transcript,
            audio_base64=body.audio_base64,
            mime_type=body.mime_type,
            mode=body.mode,
        )
    except VoiceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("voice turn failed")
        raise HTTPException(status_code=502, detail=f"voice provider failed: {exc}") from exc

    # Track 3: the voice agent is a user-facing AI action, so it belongs in the
    # action log. Deliberately metadata only — the transcript is the user's own
    # speech and never enters the log, even scrubbed (voice PII discipline).
    session.log.record(
        A.VOICE_TURN,
        actor=Origin.HUMAN,
        subject=body.mode,
        detail=f"Operator used the voice agent ({body.mode}).",
        mode=body.mode,
        input="audio" if body.audio_base64 else "text",
        stt_provider=result.stt_provider,
    )
    if result.transcript_redacted:
        # The interception point, evidenced. This is the line that proves the
        # scrub sits between the vendor's STT and any model we call.
        session.log.record(
            A.VOICE_SCRUBBED,
            actor=Origin.SYSTEM,
            subject=body.session_id,
            detail="PII scrubbed from the transcript before it reached any model.",
            replacements=result.replacements,
        )
    session.log.record(
        A.VOICE_ANSWERED,
        actor=Origin.AGENT,
        subject=body.mode,
        detail=(
            f"Voice agent answered, grounded in {len(result.grounded_finding_ids)} finding(s)."
        ),
        grounded_finding_ids=result.grounded_finding_ids,
        llm_provider=result.llm_provider,
        tts_provider=result.tts_provider,
        offline=result.offline,
    )
    return result.as_dict()


# ── guardrail demos ─────────────────────────────────────────────────────


@router.post("/quarantine/parse")
async def quarantine_parse(body: QuarantineRequest) -> dict[str, Any]:
    """Parse untrusted text in the sandbox. The prompt-injection demo endpoint.

    Stateless and session-free on purpose: it can be hit from a demo button
    without touching a live graph, and nothing it returns can enter one.
    """
    result = parse_untrusted(body.text, skip_model_on_injection=body.skip_model_on_injection)
    return result.as_dict()


@router.post("/quarantine/classify")
async def quarantine_classify(body: QuarantineRequest) -> dict[str, Any]:
    """Deterministic injection classification with no model call at all.

    Works offline, which matters: the live injection demo shouldn't depend on
    a network round-trip in front of an audience.
    """
    return classify_injection(body.text).as_dict()


# ── records advisor ─────────────────────────────────────────────────────


@router.get("/records/jurisdictions")
async def records_jurisdictions() -> dict[str, Any]:
    return {"jurisdictions": jurisdictions()}


@router.post("/records/advise")
async def records_advise(body: RecordsRequest) -> dict[str, Any]:
    """Model-written prioritization over curated jurisdiction facts.

    No lookup is performed here or anywhere in this module.
    """
    return personalize(body.state, body.persona, body.county)


# ── action log ──────────────────────────────────────────────────────────


@router.get("/actions/{session_id}")
async def actions(session_id: str, since: int = 0, limit: int = 200) -> dict[str, Any]:
    """The append-only action log. Track 3's third required element."""
    session = _session(session_id)
    return {
        "session_id": session_id,
        "summary": session.log.summary(),
        "entries": [e.model_dump(mode="json") for e in session.log.entries(since, limit)],
    }


# ── mock data for C and D ───────────────────────────────────────────────


@router.get("/mock/findings")
async def mock_findings(session_id: str = "sess_demo", count: int | None = None) -> dict[str, Any]:
    """Schema-valid fake findings. Unblocks the frontend from minute thirty.

    Everything here carries ``source="mock:generator"`` — label it in the UI.
    """
    identity = demo_identity(session_id)
    findings = generate(identity, count=count)
    from .attack_paths import annotate_findings, build_attack_paths
    from .attribution import attribute
    from .scoring import apply_persona, compute_score

    weighted = apply_persona(findings, "scammer")
    paths = build_attack_paths(weighted)
    weighted = annotate_findings(weighted, paths)

    return {
        "contract_version": CONTRACT_VERSION,
        "is_mock": True,
        "findings": [f.model_dump(mode="json") for f in weighted],
        "attack_paths": [p.model_dump(mode="json") for p in paths],
        "attribution": [a.model_dump(mode="json") for a in attribute(weighted, "scammer")],
        "score": compute_score(weighted, "scammer").model_dump(mode="json"),
    }


@router.websocket("/ws/{session_id}")
async def live_session(websocket: WebSocket, session_id: str) -> None:
    """Bidirectional interrupt/resume adapter consumed by Engineer D's UI.

    Commands travel over the socket; each acknowledgement includes the full
    recomputed snapshot. The underlying orchestrator remains the same
    approve/edit/reject state machine, so WebSocket transport cannot bypass
    its human authorization check.
    """
    ip = ws_client_ip(websocket)
    if store.get(session_id) is None:
        log.warning(
            "websocket_rejected",
            extra={"session_id": session_id, "ip": ip, "reason": "unknown_session"},
        )
        await websocket.close(code=1008, reason="Session not found")
        return

    origin = websocket.headers.get("origin") or ""
    origin_re = os.environ.get(
        "MIRROR_UI_ORIGIN_REGEX",
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    )
    if origin and not re.match(origin_re, origin):
        log.warning(
            "websocket_rejected",
            extra={
                "session_id": session_id,
                "ip": ip,
                "reason": "unexpected_origin",
                "origin": origin,
            },
        )
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    try:
        acquire_ws(ip)
    except HTTPException:
        await websocket.close(code=1008, reason="Too many WebSocket connections")
        return

    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(message: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(message)

    async def forward_events() -> None:
        async for message in event_bus.subscribe(session_id):
            await send(message)

    await send(
        {
            "event": "session.snapshot",
            "snapshot": _session(session_id).snapshot().model_dump(mode="json"),
        }
    )
    forward_task = asyncio.create_task(forward_events())

    try:
        while True:
            message = await websocket.receive_json()
            broadcast_token = _suppress_broadcast.set(True)
            request_id = str(message.get("request_id", ""))
            action = str(message.get("action", ""))
            payload: dict[str, Any] = {}
            event = "session.snapshot"

            try:
                if action == "agent.expand":
                    payload = await plan(
                        PlanRequest(
                            session_id=session_id,
                            state=message.get("state"),
                            county=message.get("county"),
                            scraped_bio=message.get("scraped_bio"),
                            bio_source=message.get("bio_source"),
                        )
                    )
                    event = "agent.awaiting_approval"
                elif action == "proposal.approve":
                    payload = await _approve_impl(
                        DecisionRequest(
                            session_id=session_id,
                            proposal_id=str(message.get("proposal_id", "")),
                        ),
                        ip=ip,
                    )
                    event = "finding.new"
                elif action == "proposal.reject":
                    payload = await reject_proposal(
                        DecisionRequest(
                            session_id=session_id,
                            proposal_id=str(message.get("proposal_id", "")),
                            reason=str(message.get("reason", "Operator declined.")),
                        )
                    )
                    event = "finding.updated"
                elif action == "proposal.edit":
                    payload = await edit_proposal(
                        EditRequest(
                            session_id=session_id,
                            proposal_id=str(message.get("proposal_id", "")),
                            changes=dict(message.get("changes") or {}),
                            reason=message.get("reason"),
                        )
                    )
                    event = "finding.new"
                elif action == "finding.reject":
                    payload = await reject_finding(
                        FindingDecision(
                            session_id=session_id,
                            finding_id=str(message.get("finding_id", "")),
                            reason=str(message.get("reason", "That's not me")),
                        )
                    )
                    event = "finding.rejected"
                elif action == "finding.restore":
                    payload = await restore_finding(
                        FindingDecision(
                            session_id=session_id,
                            finding_id=str(message.get("finding_id", "")),
                        )
                    )
                    event = "finding.updated"
                elif action == "persona.change":
                    payload = await set_persona(
                        PersonaRequest(
                            session_id=session_id,
                            persona=str(message.get("persona", "")),
                        )
                    )
                    event = "score.changed"
                elif action == "agent.cancel":
                    payload = await cancel(PlanRequest(session_id=session_id))
                    event = "finding.updated"
                elif action == "session.snapshot":
                    payload = {}
                else:
                    raise HTTPException(status_code=400, detail=f"unknown action {action}")

                snapshot = _session(session_id).snapshot().model_dump(mode="json")
                _suppress_broadcast.reset(broadcast_token)
                await send(
                    {
                        "request_id": request_id,
                        "event": event,
                        "payload": payload,
                        "snapshot": snapshot,
                    }
                )
            except HTTPException as exc:
                if _suppress_broadcast.get():
                    _suppress_broadcast.reset(broadcast_token)
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                await send(
                    {
                        "request_id": request_id,
                        "event": "command.error",
                        "error": detail,
                    }
                )
            except Exception as exc:
                if _suppress_broadcast.get():
                    _suppress_broadcast.reset(broadcast_token)
                log.exception("websocket command failed: %s", action)
                await send(
                    {
                        "request_id": request_id,
                        "event": "command.error",
                        "error": str(exc),
                    }
                )
    except WebSocketDisconnect:
        return
    finally:
        release_ws(ip)
        forward_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await forward_task
