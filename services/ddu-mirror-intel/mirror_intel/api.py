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

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from . import actionlog as A
from . import orchestrator as orch
from .guardrails import TargetRefusedError, VerifiedIdentity
from .llm import get_llm
from .mock import demo_identity, generate
from .personas import PERSONAS, load_persona_weights
from .quarantine import classify_injection, parse_untrusted
from .records import jurisdictions, personalize
from .remediation import build_checklist
from .schema import CONTRACT_VERSION, Finding, Origin
from .session import store

log = logging.getLogger("mirror-intel.api")

router = APIRouter(prefix="/intel", tags=["mirror-intel"])

load_persona_weights()


# ── request models ───────────────────────────────────────────────────────
# Note what none of these have: a free-text target. A session is created from
# an already-verified identity set handed over by Engineer A's identity gate.


class SessionCreate(BaseModel):
    session_id: str
    emails: list[str] = Field(default_factory=list)
    handles: list[str] = Field(default_factory=list)
    account_urls: list[str] = Field(default_factory=list)
    persona: str = "scammer"
    #: Populate the graph with mock findings so C and D can build against a
    #: full scene without waiting for real discovery.
    seed_mock_findings: bool = False


class PlanRequest(BaseModel):
    session_id: str
    #: Context the human supplied in onboarding — jurisdiction for the records
    #: advisor, a pasted bio for the quarantine demo.
    state: str | None = None
    county: str | None = None
    scraped_bio: str | None = None
    bio_source: str | None = None


class DecisionRequest(BaseModel):
    session_id: str
    proposal_id: str
    reason: str | None = None


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


def _session(session_id: str):
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
    return session


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
    }


# ── session lifecycle ────────────────────────────────────────────────────


@router.post("/session")
async def create_session(body: SessionCreate) -> dict[str, Any]:
    """Register a session from an already-verified identity set.

    The caller is Engineer A's identity gate, after a code loop or OAuth. This
    endpoint trusts the set it is given and treats it as the ceiling — every
    downstream worker refuses anything outside it.
    """
    if not (body.emails or body.handles or body.account_urls):
        raise HTTPException(
            status_code=400,
            detail="a session needs at least one verified identifier; complete verification first",
        )

    identity = VerifiedIdentity.build(
        session_id=body.session_id,
        emails=body.emails,
        handles=body.handles,
        account_urls=body.account_urls,
    )
    session = store.create(identity, persona=body.persona)

    if body.seed_mock_findings:
        session.add_findings(generate(identity))
        session.log.record(
            A.FINDING_ADDED,
            actor=Origin.SYSTEM,
            subject=body.session_id,
            detail="Mock findings seeded for frontend development — NOT REAL DATA.",
            mock=True,
        )

    return {
        "session_id": session.session_id,
        "persona": session.persona,
        "verified_identifier_count": len(identity.all_identifiers),
        "findings": len(session.findings),
        "snapshot": session.snapshot().model_dump(mode="json"),
    }


@router.get("/session/{session_id}")
async def get_snapshot(session_id: str) -> dict[str, Any]:
    """Everything D needs to render, in one call."""
    return _session(session_id).snapshot().model_dump(mode="json")


@router.delete("/session/{session_id}")
async def wipe_session(session_id: str) -> dict[str, Any]:
    """Ephemeral guarantee, made visible.

    Returns what was destroyed so the wipe animation has real counts to render
    rather than a spinner over an empty promise.
    """
    session = _session(session_id)
    counts = session.wipe()
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
    store.drop(session_id)
    orch.drop_session(session_id)
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
    return {
        "session_id": body.session_id,
        "event": "agent.awaiting_approval",
        "proposals": [p.model_dump(mode="json") for p in proposals],
        "pending_total": len(orchestrator.pending()),
        "note": "No discovery has run. Each proposal needs approve, edit, or reject.",
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


@router.post("/scan/approve")
async def approve(body: DecisionRequest) -> dict[str, Any]:
    """Human approves; the work then runs."""
    orchestrator = orch.for_session(_session(body.session_id))
    try:
        orchestrator.approve(body.proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _run(body.session_id, body.proposal_id)


@router.post("/scan/edit")
async def edit_proposal(body: EditRequest) -> dict[str, Any]:
    """Human amends the draft, then it runs.

    Only inputs the step declares editable are applied; anything else is
    reported back in ``ignored`` rather than silently dropped.
    """
    orchestrator = orch.for_session(_session(body.session_id))
    try:
        proposal = orchestrator.edit_and_approve(body.proposal_id, body.changes, body.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result = _run(body.session_id, body.proposal_id)
    result["applied_edit"] = proposal.human_edit
    return result


@router.post("/scan/reject")
async def reject_proposal(body: DecisionRequest) -> dict[str, Any]:
    """Human declines. Nothing runs, and the decision is logged."""
    orchestrator = orch.for_session(_session(body.session_id))
    try:
        proposal = orchestrator.reject(body.proposal_id, body.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"proposal": proposal.model_dump(mode="json"), "findings_added": 0}


@router.post("/scan/cancel")
async def cancel(body: PlanRequest) -> dict[str, Any]:
    """Kill switch. Halts the agent and drops everything pending."""
    orchestrator = orch.for_session(_session(body.session_id))
    dropped = orchestrator.cancel()
    return {
        "session_id": body.session_id,
        "cancelled": True,
        "dropped_actions": dropped,
        "note": "Findings already approved remain; nothing further will run.",
    }


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
    return {
        "session_id": body.session_id,
        "producer": body.producer,
        "accepted": [f.model_dump(mode="json") for f in added],
        "rejected": errors,
        "score": session.score.model_dump(mode="json"),
        "attack_paths": [p.model_dump(mode="json") for p in session.attack_paths],
        "attribution": [a.model_dump(mode="json") for a in session.attribution],
    }


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
    return {
        "rejected": body.finding_id,
        "cascaded": result.cascaded_ids,
        "broken_paths": result.broken_path_ids,
        "score": session.score.model_dump(mode="json"),
        "snapshot": session.snapshot().model_dump(mode="json"),
    }


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
    return {
        "restored": body.finding_id,
        "cascaded": result.cascaded_ids,
        "score": session.score.model_dump(mode="json"),
    }


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
    return {"finding_id": body.finding_id, "applied": applied}


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
    return {
        "persona": body.persona,
        "score_before": before,
        "score": score.model_dump(mode="json"),
        "attribution": [a.model_dump(mode="json") for a in session.attribution],
        "note": "Same findings, re-ranked. Nothing was rescanned.",
    }


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

    return {
        "score_now": session.score.model_dump(mode="json"),
        "score_projected": projected.model_dump(mode="json"),
        "refused": refused,
        "refused_reason": "These exposures cannot be undone. See each finding's "
        "compensating control." if refused else None,
    }


@router.get("/remediation/{session_id}")
async def remediation(session_id: str, with_copy: bool = True) -> dict[str, Any]:
    """Severity × effort ordered checklist, with persona-specific framing."""
    session = _session(session_id)
    checklist = build_checklist(session.findings, session.persona, with_copy=with_copy)
    return checklist.as_dict()


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
