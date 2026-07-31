"""DDU Mirror findings contract — v1.

LOCKED. This module is the single source of truth for the shape every other
module in the product consumes: the 3D scene reads `hop_depth` and `severity`,
the evidence drawer reads `evidence`, the voice agent reads
`verification_state`, and the scoring engine reads all of it.

Changes require a version bump in CONTRACT_VERSION and a note in
docs/findings-contract.md. No silent shape changes.

Design rules this schema enforces structurally:

* Rule 2 (no third-party traversal) — every finding carries `subject_ref`,
  which must resolve to the session's verified seed identity. Findings about
  anyone else cannot be represented; see ``guardrails.suppress_third_party``.
* Rule 7 (nothing irreversible is claimed reversible) — `reversible=False`
  requires a `remediation.compensating` control. Validated, not documented.
* Track 3 (human in the loop) — `verification_state` includes ``rejected``,
  and `origin` records whether a human or the agent put the finding there.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

CONTRACT_VERSION = "1.0.0"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class VerificationState(str, Enum):
    """Epistemic class of a finding. Never collapsed — see AGENTS.md."""

    CONFIRMED = "confirmed"
    LIKELY = "likely"
    HYPOTHESIS = "hypothesis"
    CONTRADICTED = "contradicted"
    REJECTED = "rejected"  # the human said "that's not me"


#: States that count toward the exposure score. A rejected or contradicted
#: finding is still in the graph (for audit) but contributes zero.
SCORING_STATES = frozenset(
    {VerificationState.CONFIRMED, VerificationState.LIKELY, VerificationState.HYPOTHESIS}
)

#: Confidence multiplier applied per verification state when scoring. A
#: hypothesis should never weigh as much as a confirmed exposure.
STATE_WEIGHT: dict[VerificationState, float] = {
    VerificationState.CONFIRMED: 1.0,
    VerificationState.LIKELY: 0.7,
    VerificationState.HYPOTHESIS: 0.35,
    VerificationState.CONTRADICTED: 0.0,
    VerificationState.REJECTED: 0.0,
}


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


#: Ordered low→high so severity bands can be compared and bucketed.
SEVERITY_ORDER: list[Severity] = [
    Severity.INFO,
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
]


def severity_from_score(value: float) -> Severity:
    """Map a persona-adjusted 0..1 severity score onto a band."""
    if value >= 0.85:
        return Severity.CRITICAL
    if value >= 0.65:
        return Severity.HIGH
    if value >= 0.40:
        return Severity.MEDIUM
    if value >= 0.15:
        return Severity.LOW
    return Severity.INFO


class FindingType(str, Enum):
    """Closed set. Adding a type means adding a persona weight, a
    reversibility rule, and an attack-path edge rule — the three tables that
    are keyed off it. Keeping it an enum makes those omissions loud."""

    SEED_IDENTITY = "seed_identity"
    ACCOUNT = "account"
    BREACH = "breach"
    GPS_EXPOSURE = "gps_exposure"
    DEVICE_FINGERPRINT = "device_fingerprint"
    OBJECT_EXPOSURE = "object_exposure"
    LOCATION_INFERENCE = "location_inference"
    FACE_LINK = "face_link"
    HANDLE_LINK = "handle_link"
    RECORD_CLASS = "record_class"
    CREDENTIAL_REUSE = "credential_reuse"
    EMPLOYER_LINK = "employer_link"
    ATTACKER_NEXT_MOVE = "attacker_next_move"


class Effort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: Effort divides the remediation ranking score — cheap high-severity fixes
#: float to the top of the checklist.
EFFORT_COST: dict[Effort, float] = {Effort.LOW: 1.0, Effort.MEDIUM: 1.6, Effort.HIGH: 2.5}


class Origin(str, Enum):
    """Who put this finding in the graph. Track 3 wants the human's edits
    distinguishable from the model's proposals in the log and the UI."""

    AGENT = "agent"
    HUMAN = "human"
    SYSTEM = "system"


class EvidenceItem(BaseModel):
    """One row in the evidence drawer.

    `v` is *always* the redacted display value. The raw value never leaves the
    trust boundary in this object — the client exchanges `reveal_token` for it
    over an authenticated, logged endpoint (design rule 4).
    """

    kind: Literal["kv", "text", "image_ref", "url", "record"] = "kv"
    k: str
    v: str = "REDACTED"
    reveal_token: str | None = None
    redacted: bool = True


class Remediation(BaseModel):
    action: str
    compensating: str | None = None
    effort: Effort = Effort.MEDIUM
    #: Set when the exposure cannot be undone and the honest answer is a
    #: compensating control instead of a fix.
    permanent_note: str | None = None


class Finding(BaseModel):
    """The unit of everything. Emitted by discovery, vision, and the agent."""

    model_config = {"use_enum_values": False}

    contract_version: str = CONTRACT_VERSION

    id: str
    parent_id: str | None = None
    hop_depth: int = Field(0, ge=0, description="Distance from verified seed; drives 3D Z axis")

    type: FindingType
    label: str
    detail: str = ""

    verification_state: VerificationState = VerificationState.HYPOTHESIS
    confidence: float = Field(0.5, ge=0.0, le=1.0)

    #: Persona-independent badness of this exposure in the abstract.
    severity_base: float = Field(0.5, ge=0.0, le=1.0)
    #: Persona-adjusted band. Recomputed by scoring.apply_persona; never set
    #: by hand in a producer module.
    severity: Severity = Severity.MEDIUM
    #: The numeric behind `severity`, kept so ranking is stable within a band.
    severity_score: float = Field(0.5, ge=0.0, le=1.0)

    reversible: bool = True
    remediation: Remediation

    platform: str | None = None
    source: str = Field(..., description="Where the value came from, e.g. 'exif:GPSInfo'")
    method: str = Field(..., description="What produced it, e.g. 'exifread v3.0'")

    evidence: list[EvidenceItem] = Field(default_factory=list)
    attack_path_ids: list[str] = Field(default_factory=list)

    #: Must equal the session's verified seed identity. The reason there is no
    #: free-text target field anywhere in this product.
    subject_ref: str

    origin: Origin = Origin.AGENT
    #: Free-form human edit trail; populated by the correction loop.
    human_note: str | None = None

    timestamp: str = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _irreversible_needs_compensating(self) -> "Finding":
        """Design rule 7, enforced in the type system rather than in a doc.

        If we cannot undo it, we owe the user a compensating control. A
        finding that claims permanence but offers no alternative is a dead end
        in the UI and a lie in the pitch.
        """
        if not self.reversible and not self.remediation.compensating:
            raise ValueError(
                f"finding {self.id}: reversible=False requires remediation.compensating "
                "(design rule 7 — nothing irreversible is claimed reversible)"
            )
        return self

    @property
    def counts_toward_score(self) -> bool:
        return self.verification_state in SCORING_STATES


class AttackPath(BaseModel):
    """A chain of findings in the order an attacker would walk them."""

    id: str
    finding_ids: list[str]
    narrative: str
    #: Severity of the weakest-but-still-sufficient link, i.e. how hard the
    #: path is to walk. Driven by the least-confident hop.
    feasibility: float = Field(0.5, ge=0.0, le=1.0)
    terminal_impact: str = ""


class PlatformAttribution(BaseModel):
    platform: str
    finding_count: int
    weighted_severity: float
    share: float = Field(0.0, ge=0.0, le=1.0)
    hardening_hint: str = ""


class ScoreBreakdown(BaseModel):
    """Output of the exposure score engine. Pure function of the live set."""

    score: int = Field(..., ge=0, le=100)
    band: Literal["minimal", "moderate", "elevated", "severe", "critical"]
    persona: str
    contributing_findings: int
    suppressed_findings: int
    irreversible_share: float = Field(0.0, ge=0.0, le=1.0)
    top_drivers: list[str] = Field(default_factory=list)
    by_severity: dict[str, int] = Field(default_factory=dict)


class ProposalStatus(str, Enum):
    """Track 3's approve/edit/reject flow, as a state machine."""

    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXECUTED = "executed"
    FAILED = "failed"


class Proposal(BaseModel):
    """An action the agent wants to take, drafted but *not* taken.

    Nothing in this system reaches a discovery worker without a Proposal
    transitioning to APPROVED or EDITED first. This is the object the
    hackathon's Track 3 rubric is actually asking about.
    """

    id: str
    session_id: str
    step: str = Field(..., description="Discovery step key, e.g. 'sherlock.enumerate'")
    title: str
    rationale: str = Field(..., description="Why the agent wants this — shown to the human")
    #: Redacted preview of what this step will look at.
    inputs: dict[str, Any] = Field(default_factory=dict)
    #: What the human is being asked to accept: cost, reach, and reversibility.
    expected_findings: str = ""
    touches_external: list[str] = Field(default_factory=list)
    #: Fields this step will accept on an edit. The UI renders exactly these
    #: and nothing else, so the allowlist has one definition (the step) rather
    #: than a second copy in the client that can drift out of step with it.
    #: Additive with a default, so a client built against 1.0.0 ignores it.
    editable_inputs: list[str] = Field(default_factory=list)
    parent_finding_id: str | None = None
    hop_depth: int = 0

    status: ProposalStatus = ProposalStatus.AWAITING_APPROVAL
    #: Populated when the human edits rather than accepts the draft.
    human_edit: dict[str, Any] | None = None
    human_reason: str | None = None
    decided_at: str | None = None
    created_at: str = Field(default_factory=_utcnow)


class ActionLogEntry(BaseModel):
    """Append-only. Track 3's 'simple action log', kept honest: it records
    refusals and rejections, not just successes."""

    seq: int
    session_id: str
    at: str = Field(default_factory=_utcnow)
    actor: Origin
    action: str
    subject: str = ""
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionSnapshot(BaseModel):
    """Everything D needs to render, in one shape."""

    session_id: str
    contract_version: str = CONTRACT_VERSION
    persona: str
    findings: list[Finding]
    attack_paths: list[AttackPath]
    attribution: list[PlatformAttribution]
    score: ScoreBreakdown
    pending_proposals: list[Proposal]
    action_log_tail: list[ActionLogEntry] = Field(default_factory=list)
