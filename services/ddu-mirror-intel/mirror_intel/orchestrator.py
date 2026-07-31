"""Scan orchestrator — propose, wait for a human, then act.

This module is where Track 3 lives. The rule it enforces has no exceptions:

    **No discovery worker runs without a Proposal in APPROVED or EDITED
    state.** ``execute`` asserts it, and there is no bypass flag.

The loop:

    plan()  →  Proposal(AWAITING_APPROVAL)  →  human decides
                                                  ├─ approve → execute → findings
                                                  ├─ edit    → execute with the
                                                  │            human's changes
                                                  └─ reject  → nothing runs
    findings change the graph → plan() proposes the next hop → repeat

Every transition is an action-log entry, so the log answers "who authorized
this expansion?" for every finding in the graph.

``workflow.py`` places this deterministic planner/executor behind a real
LangGraph ``interrupt``. Redis or SQLite checkpoints hold the resumable graph
cursor; the encrypted session backend holds raw pending inputs. Keeping the
worker logic here makes replay idempotence and the authorization assertion
easy to test without weakening the checkpointed runtime.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import actionlog as A
from .discovery.hibp import breach_findings
from .discovery.linkability import AccountProfile, linkability_findings
from .discovery.sherlock import account_findings
from .guardrails import TargetRefusedError
from .quarantine import parse_untrusted
from .records import advise
from .schema import Finding, Origin, Proposal, ProposalStatus
from .session import SEED_FINDING_ID, Session

log = logging.getLogger("mirror-intel.orchestrator")


class StepHandler(Protocol):
    def __call__(self, session: Session, inputs: dict[str, Any]) -> tuple[list[Finding], dict[str, Any]]: ...


@dataclass
class Step:
    """One thing the agent can ask permission to do."""

    key: str
    title: str
    #: Shown to the human before they decide. Must be specific enough to
    #: consent to — "we will search 10 sites for this handle", not "discovery".
    rationale: str
    expected_findings: str
    #: External services this step contacts. The human is consenting to an
    #: outbound call, and naming the vendor is part of informed consent.
    touches_external: list[str]
    handler: StepHandler
    #: Fields a human may change when they edit rather than approve.
    editable_inputs: frozenset[str] = frozenset()


# ── step handlers ────────────────────────────────────────────────────────


def _step_accounts(session: Session, inputs: dict[str, Any]) -> tuple[list[Finding], dict[str, Any]]:
    handle = inputs.get("handle") or next(iter(session.identity.handles), "")
    return account_findings(
        session.identity,
        handle,
        parent_id=inputs.get("parent_id"),
        hop_depth=int(inputs.get("hop_depth", 1)),
    )


def _step_breaches(session: Session, inputs: dict[str, Any]) -> tuple[list[Finding], dict[str, Any]]:
    email = inputs.get("email") or next(iter(session.identity.emails), "")
    return breach_findings(
        session.identity,
        email,
        parent_id=inputs.get("parent_id"),
        hop_depth=int(inputs.get("hop_depth", 1)),
    )


def _step_linkability(session: Session, inputs: dict[str, Any]) -> tuple[list[Finding], dict[str, Any]]:
    profiles = [
        AccountProfile(**p) if isinstance(p, dict) else p for p in inputs.get("profiles", [])
    ]
    if not profiles:
        # Derive candidate profiles from accounts already in the graph, so
        # this step composes with whatever the human has approved so far.
        profiles = [
            AccountProfile(
                platform=f.platform or "unknown",
                handle=next(iter(session.identity.handles), ""),
                url="",
            )
            for f in session.findings
            if f.type.value == "account" and f.counts_toward_score
        ]
    return linkability_findings(
        session.identity,
        profiles,
        parent_id=inputs.get("parent_id"),
        hop_depth=int(inputs.get("hop_depth", 2)),
    )


def _step_records(session: Session, inputs: dict[str, Any]) -> tuple[list[Finding], dict[str, Any]]:
    return advise(
        session.identity,
        state=str(inputs.get("state", "")),
        county=inputs.get("county"),
        parent_id=inputs.get("parent_id"),
        hop_depth=int(inputs.get("hop_depth", 1)),
    )


def _step_parse_bio(session: Session, inputs: dict[str, Any]) -> tuple[list[Finding], dict[str, Any]]:
    """Parse a scraped bio inside the quarantine sandbox.

    Returns no findings by design. The sandbox produces *data*, and letting it
    produce findings would be a path from attacker-controlled text into the
    graph — which is the thing quarantine exists to prevent. The result goes
    into the step metadata for the UI to display.
    """
    result = parse_untrusted(str(inputs.get("text", "")))
    if result.verdict.detected:
        session.log.record(
            A.INJECTION_QUARANTINED,
            actor=Origin.SYSTEM,
            subject=inputs.get("source", "scraped profile"),
            detail="Prompt-injection payload detected in scraped text and contained.",
            signatures=result.verdict.signatures,
            confidence=result.verdict.confidence,
        )
    return [], {"worker": "quarantine", **result.as_dict()}


STEPS: dict[str, Step] = {
    "discovery.accounts": Step(
        key="discovery.accounts",
        title="Search for accounts using your handle",
        rationale=(
            "Your handle is the cheapest pivot an attacker has. I'd check a curated "
            "set of high-signal platforms for profiles using it. Username matches are "
            "not proof of identity, so anything I find comes back as 'likely' and you "
            "can reject what isn't yours."
        ),
        expected_findings="0-10 account findings, each individually rejectable",
        touches_external=["Sherlock (site availability checks)"],
        handler=_step_accounts,
        editable_inputs=frozenset({"handle"}),
    ),
    "discovery.breaches": Step(
        key="discovery.breaches",
        title="Check your verified email against breach corpora",
        rationale=(
            "I'd query Have I Been Pwned for your verified address only. Breach "
            "records are the clearest example of exposure you cannot undo, so this "
            "is also where the reversibility story becomes concrete."
        ),
        expected_findings="0-8 breach findings, all irreversible",
        touches_external=["Have I Been Pwned API"],
        handler=_step_breaches,
        editable_inputs=frozenset({"email"}),
    ),
    "intel.linkability": Step(
        key="intel.linkability",
        title="Test whether your accounts are linkable to each other",
        rationale=(
            "Runs entirely on data already in this session — no new outbound calls. "
            "I'd compare the accounts you've approved for shared avatars, copied bio "
            "phrases, cross-links, and handle similarity, to see whether an account "
            "you keep pseudonymous is provably yours."
        ),
        expected_findings="0-5 linkability findings",
        touches_external=[],
        handler=_step_linkability,
    ),
    "advisor.records": Step(
        key="advisor.records",
        title="Map which public records are public where you live",
        rationale=(
            "No lookup and no scraping — I don't retrieve any record. I'd tell you "
            "which classes of record are public by statute in your state, what each "
            "one discloses, and the documented suppression path."
        ),
        expected_findings="4-7 record-class findings",
        touches_external=[],
        handler=_step_records,
        editable_inputs=frozenset({"state", "county"}),
    ),
    "quarantine.parse_bio": Step(
        key="quarantine.parse_bio",
        title="Parse a scraped profile bio in the sandbox",
        rationale=(
            "Scraped bios are attacker-controlled text. I'd send this to an isolated "
            "model with no tools, and treat everything it returns as data. Nothing "
            "from this step can reach a tool call or start a scan."
        ),
        expected_findings="No findings — this step produces data only",
        touches_external=["quarantined LLM (no tools bound)"],
        handler=_step_parse_bio,
    ),
}


@dataclass
class Orchestrator:
    """Drives one session's scan. One instance per session."""

    session: Session
    #: Set by the kill switch; blocks execution even for already-approved work.
    cancelled: bool = False
    _proposal_seq: int = field(default=0, repr=False)
    #: Full step inputs, held out of band. The Proposal carries only a
    #: redacted preview, so a handle never reaches the action log or the wire
    #: — but the handler still needs the real value on approval.
    _pending_inputs: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        persisted = self.session.workflow_state
        self.cancelled = bool(persisted.get("cancelled", self.cancelled))
        self._proposal_seq = int(persisted.get("proposal_seq", self._proposal_seq))
        self._pending_inputs = {
            str(proposal_id): dict(inputs)
            for proposal_id, inputs in dict(persisted.get("pending_inputs", {})).items()
        }

    def _sync_state(self) -> None:
        state = dict(self.session.workflow_state)
        state.update(
            {
                "cancelled": self.cancelled,
                "proposal_seq": self._proposal_seq,
                "pending_inputs": self._pending_inputs,
            }
        )
        self.session.workflow_state = state

    # ── planning ─────────────────────────────────────────────────────────

    def plan(self, context: dict[str, Any] | None = None) -> list[Proposal]:
        """Propose the next expansions, given what's already in the graph.

        Deliberately conservative: it proposes what the graph makes available
        now, rather than queueing a whole scan up front. The human approves
        one hop at a time, which is what makes the 3D scene bloom outward
        under their control instead of animating a decision already made.
        """
        context = context or {}
        existing = {p.step for p in self.session.proposals.values()}
        proposals: list[Proposal] = []

        types_present = {f.type.value for f in self.session.findings if f.counts_toward_score}

        if self.session.identity.handles and "discovery.accounts" not in existing:
            proposals.append(
                self._draft(
                    "discovery.accounts",
                    inputs={"handle": next(iter(self.session.identity.handles)), "hop_depth": 1},
                )
            )

        if self.session.identity.emails and "discovery.breaches" not in existing:
            proposals.append(
                self._draft(
                    "discovery.breaches",
                    inputs={"email": next(iter(self.session.identity.emails)), "hop_depth": 1},
                )
            )

        # Linkability only becomes meaningful once there are accounts to
        # compare, so it isn't offered before then.
        if "account" in types_present and "intel.linkability" not in existing:
            seed = next(
                (f for f in self.session.findings if f.type.value == "account"), None
            )
            proposals.append(
                self._draft(
                    "intel.linkability",
                    inputs={"parent_id": seed.id if seed else None, "hop_depth": 2},
                )
            )

        if context.get("state") and "advisor.records" not in existing:
            proposals.append(
                self._draft(
                    "advisor.records",
                    inputs={
                        "state": context["state"],
                        "county": context.get("county"),
                        "hop_depth": 1,
                    },
                )
            )

        if context.get("scraped_bio") and "quarantine.parse_bio" not in existing:
            proposals.append(
                self._draft(
                    "quarantine.parse_bio",
                    inputs={
                        "text": context["scraped_bio"],
                        "source": context.get("bio_source", "scraped profile"),
                    },
                )
            )

        return proposals

    def _draft(self, step_key: str, inputs: dict[str, Any]) -> Proposal:
        step = STEPS[step_key]
        # Hang first-hop expansions off the seed node. Without this every
        # worker's output lands unparented at depth 1 and no attack path can
        # form — the graph is a spray, not a tree.
        inputs.setdefault("parent_id", SEED_FINDING_ID)
        self._proposal_seq += 1
        proposal = Proposal(
            id=f"prop_{self._proposal_seq:02d}_{uuid.uuid4().hex[:4]}",
            session_id=self.session.session_id,
            step=step.key,
            title=step.title,
            rationale=step.rationale,
            # Redacted preview only. The human already knows their own handle;
            # the proposal record does not need to carry it, and the action
            # log definitely does not.
            inputs={k: v for k, v in inputs.items() if k in {"hop_depth", "parent_id", "state", "county"}},
            expected_findings=step.expected_findings,
            touches_external=list(step.touches_external),
            # Sorted so the edit form renders in a stable order between drafts.
            editable_inputs=sorted(step.editable_inputs),
            parent_finding_id=inputs.get("parent_id"),
            hop_depth=int(inputs.get("hop_depth", 1)),
        )
        # Full inputs are kept out of band so they never reach the log or the
        # wire, but are available to the handler on approval.
        self._pending_inputs[proposal.id] = inputs
        self.session.proposals[proposal.id] = proposal
        self.session.log.record(
            A.PROPOSED,
            actor=Origin.AGENT,
            subject=proposal.id,
            detail=f"Agent proposes: {step.title}",
            step=step.key,
            touches_external=step.touches_external,
        )
        self._sync_state()
        return proposal

    # ── human decisions ──────────────────────────────────────────────────

    def approve(self, proposal_id: str) -> Proposal:
        proposal = self._require(proposal_id, ProposalStatus.AWAITING_APPROVAL)
        proposal.status = ProposalStatus.APPROVED
        proposal.decided_at = _now()
        self.session.log.record(
            A.APPROVED,
            actor=Origin.HUMAN,
            subject=proposal_id,
            detail=f"Operator approved: {proposal.title}",
            step=proposal.step,
        )
        self._sync_state()
        return proposal

    def edit_and_approve(
        self, proposal_id: str, changes: dict[str, Any], reason: str | None = None
    ) -> Proposal:
        """The 'edit' arm of approve/edit/reject.

        Only inputs the step declares editable can change. That allowlist is
        what stops "edit" from becoming a free-text target field through the
        back door — a human can narrow a scan, not redirect it, and the
        identity gate still runs on whatever they supply.
        """
        proposal = self._require(proposal_id, ProposalStatus.AWAITING_APPROVAL)
        step = STEPS[proposal.step]
        applied = {k: v for k, v in changes.items() if k in step.editable_inputs}
        ignored = sorted(set(changes) - step.editable_inputs)

        self._pending_inputs.setdefault(proposal_id, {}).update(applied)
        proposal.status = ProposalStatus.EDITED
        proposal.human_edit = applied
        proposal.human_reason = reason
        proposal.decided_at = _now()
        proposal.inputs.update({k: v for k, v in applied.items() if k in {"state", "county"}})

        self.session.log.record(
            A.EDITED,
            actor=Origin.HUMAN,
            subject=proposal_id,
            detail=f"Operator edited before approving: {', '.join(applied) or 'no changes applied'}",
            step=proposal.step,
            applied=sorted(applied),
            ignored=ignored,
            reason=reason,
        )
        if ignored:
            log.warning("ignored non-editable input(s) %s on %s", ignored, proposal_id)
        self._sync_state()
        return proposal

    def reject(self, proposal_id: str, reason: str | None = None) -> Proposal:
        proposal = self._require(proposal_id, ProposalStatus.AWAITING_APPROVAL)
        proposal.status = ProposalStatus.REJECTED
        proposal.human_reason = reason
        proposal.decided_at = _now()
        self._pending_inputs.pop(proposal_id, None)
        self.session.log.record(
            A.REJECTED_PROPOSAL,
            actor=Origin.HUMAN,
            subject=proposal_id,
            detail=f"Operator declined: {proposal.title}",
            step=proposal.step,
            reason=reason,
        )
        self._sync_state()
        return proposal

    def cancel(self, reason: str | None = None) -> int:
        """Kill switch. Consent that can't be withdrawn isn't consent.

        Halts the agent and drops every pending proposal. Findings already in
        the graph stay — the human consented to those — but nothing further
        runs, including work that was already approved.
        """
        self.cancelled = True
        dropped = 0
        for proposal in self.session.proposals.values():
            if proposal.status in (ProposalStatus.AWAITING_APPROVAL, ProposalStatus.APPROVED, ProposalStatus.EDITED):
                proposal.status = ProposalStatus.CANCELLED
                proposal.decided_at = _now()
                dropped += 1
        self._pending_inputs.clear()
        self.session.log.record(
            A.CANCELLED,
            actor=Origin.HUMAN,
            subject=self.session.session_id,
            detail=f"Operator halted the scan. {dropped} pending action(s) dropped.",
            reason=reason,
        )
        self._sync_state()
        return dropped

    # ── execution ────────────────────────────────────────────────────────

    def execute(self, proposal_id: str) -> tuple[list[Finding], dict[str, Any]]:
        """Run an approved proposal. Refuses anything else.

        The assertion below is the load-bearing line of this module. Every
        finding in the graph can be traced back through it to a human
        decision.
        """
        proposal = self.session.proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"unknown proposal {proposal_id}")

        if proposal.status not in (ProposalStatus.APPROVED, ProposalStatus.EDITED):
            raise PermissionError(
                f"proposal {proposal_id} is {proposal.status.value}; discovery runs only "
                "after a human approves or edits it"
            )
        if self.cancelled:
            raise PermissionError("scan was cancelled by the operator")

        step = STEPS[proposal.step]
        inputs = self._pending_inputs.get(proposal_id, {})

        try:
            findings, meta = step.handler(self.session, inputs)
        except TargetRefusedError as exc:
            # The identity gate fired inside a worker. This is the live
            # refusal demo, and it belongs in the log as loudly as any success.
            proposal.status = ProposalStatus.FAILED
            self.session.log.record(
                A.TARGET_REFUSED,
                actor=Origin.SYSTEM,
                subject=proposal_id,
                detail=exc.reason,
                step=step.key,
                design_rule="1 — no verified control, no scan",
            )
            raise
        except Exception as exc:
            proposal.status = ProposalStatus.FAILED
            self.session.log.record(
                A.FAILED,
                actor=Origin.AGENT,
                subject=proposal_id,
                detail=f"{step.title} failed: {exc}",
                step=step.key,
            )
            raise

        added = self.session.add_findings(findings)
        proposal.status = ProposalStatus.EXECUTED

        self.session.log.record(
            A.EXECUTED,
            actor=Origin.AGENT,
            subject=proposal_id,
            detail=f"{step.title} produced {len(added)} finding(s).",
            step=step.key,
            **{k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, list))},
        )
        for finding in added:
            self.session.log.record(
                A.FINDING_ADDED,
                actor=Origin.AGENT,
                subject=finding.id,
                detail=finding.label,
                type=finding.type.value,
                state=finding.verification_state.value,
                severity=finding.severity.value,
            )

        self._pending_inputs.pop(proposal_id, None)
        self._sync_state()
        return added, meta

    # ── attacker-next-move hypotheses ────────────────────────────────────

    def hypothesize_next_moves(self) -> list[dict[str, Any]]:
        """What an attacker would try next — labelled, never executed.

        Red-team insight while visibly refusing to act on it. These are
        returned as annotated hypotheses for the UI, not as Proposals, so
        there is no approve button that could turn one into a running scan.
        """
        moves: list[dict[str, Any]] = []
        types = {f.type.value for f in self.session.findings if f.counts_toward_score}

        if "breach" in types and "credential_reuse" not in types:
            moves.append(
                {
                    "move": "Credential stuffing",
                    "reasoning": "A breached password is worth trying against your other "
                    "accounts. This is the cheapest next step available to them.",
                    "would_require": "Attempting logins as you — which this tool will not do.",
                    "your_counter": "Rotate the password everywhere it was reused and turn on MFA.",
                }
            )
        if "account" in types and "face_link" not in types:
            moves.append(
                {
                    "move": "Avatar cross-matching",
                    "reasoning": "Comparing profile photos across your accounts to link a "
                    "pseudonymous handle to your real name.",
                    "would_require": "An open-web face search — a capability we deliberately "
                    "do not build.",
                    "your_counter": "Use a distinct, non-facial avatar on accounts you keep separate.",
                }
            )
        if "gps_exposure" in types or "location_inference" in types:
            moves.append(
                {
                    "move": "Address confirmation via public records",
                    "reasoning": "Coordinates narrow it to a building; a property record "
                    "turns that into a name-confirmed address.",
                    "would_require": "Retrieving a specific public record — we tell you the "
                    "class is public and never fetch one.",
                    "your_counter": "Check your county's address-redaction program and work "
                    "the broker opt-out list.",
                }
            )

        for move in moves:
            move["state"] = "hypothesis"
            move["executed"] = False
        return moves

    # ── internals ────────────────────────────────────────────────────────

    def _require(self, proposal_id: str, expected: ProposalStatus) -> Proposal:
        proposal = self.session.proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"unknown proposal {proposal_id}")
        if proposal.status is not expected:
            raise ValueError(
                f"proposal {proposal_id} is {proposal.status.value}, expected {expected.value}"
            )
        return proposal

    def pending(self) -> list[Proposal]:
        return [
            p
            for p in self.session.proposals.values()
            if p.status is ProposalStatus.AWAITING_APPROVAL
        ]


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


#: Orchestrator per session id.
_orchestrators: dict[str, Orchestrator] = {}


def for_session(session: Session) -> Orchestrator:
    orch = _orchestrators.get(session.session_id)
    if orch is None or orch.session is not session:
        orch = Orchestrator(session=session)
        _orchestrators[session.session_id] = orch
    return orch


def drop_session(session_id: str) -> None:
    _orchestrators.pop(session_id, None)
