"""Session-scoped findings store.

Engineer A owns the authoritative Redis-backed session with its TTL and its
visible wipe. This is B's in-process view of the same session: the findings
graph, the derived products, and the action log, recomputed on every mutation.

Two properties are deliberate:

**Everything derived is recomputed, never patched.** ``_recompute`` runs the
whole pipeline — persona weighting, attack paths, attribution, score — after
any change. It is cheap at demo scale (tens of findings), and it is the only
way "reject a node and watch the score correct" stays true as features land.
Incremental updates would be faster and would be wrong within a day.

**Raw values live here and only here.** The vault holds the actual coordinates
and handles; findings carry reveal tokens. Wiping the session destroys the
vault, which is what makes the ephemeral guarantee real rather than cosmetic.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .actionlog import ActionLog
from .attack_paths import annotate_findings, build_attack_paths
from .attribution import attribute
from .correction import CorrectionResult, edit, prune_broken_paths, reject, restore
from .guardrails import VerifiedIdentity
from .personas import DEFAULT_PERSONA
from .redaction import verify_reveal_token
from .schema import (
    AttackPath,
    Finding,
    PlatformAttribution,
    Proposal,
    ScoreBreakdown,
    SessionSnapshot,
)
from .scoring import apply_persona, compute_score, simulate_remediation

log = logging.getLogger("mirror-intel.session")


@dataclass
class Session:
    session_id: str
    identity: VerifiedIdentity
    persona: str = DEFAULT_PERSONA

    findings: list[Finding] = field(default_factory=list)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    attack_paths: list[AttackPath] = field(default_factory=list)
    attribution: list[PlatformAttribution] = field(default_factory=list)
    score: ScoreBreakdown | None = None

    #: reveal_token -> raw value. Never serialized, never logged, never sent
    #: to a vendor. Dies with the session.
    vault: dict[str, str] = field(default_factory=dict)

    log: ActionLog = field(init=False)
    _lock: threading.RLock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.log = ActionLog(self.session_id)
        self._lock = threading.RLock()
        self._recompute()

    # ── derived state ────────────────────────────────────────────────────

    def _recompute(self) -> None:
        """Rebuild everything downstream of the findings set.

        Order matters: persona weighting first (attack-path ranking reads the
        adjusted severity), then paths, then the annotations that let the 3D
        scene light them, then attribution and score.
        """
        self.findings = apply_persona(self.findings, self.persona)
        paths = build_attack_paths(self.findings)
        self.attack_paths = prune_broken_paths(paths, self.findings)
        self.findings = annotate_findings(self.findings, self.attack_paths)
        self.attribution = attribute(self.findings, self.persona)
        self.score = compute_score(self.findings, self.persona)

    # ── mutation ─────────────────────────────────────────────────────────

    def add_findings(self, new: Iterable[Finding], raw_values: dict[str, str] | None = None) -> list[Finding]:
        """Ingest findings from a worker.

        ``raw_values`` maps reveal tokens to the underlying values. Producers
        hand them over here so the vault stays the single place raw data
        lives.
        """
        added: list[Finding] = []
        with self._lock:
            existing = {f.id for f in self.findings}
            for finding in new:
                if finding.subject_ref != self.identity.subject_ref:
                    # Should be impossible — the workers gate on this too —
                    # but a finding about someone else must never enter the
                    # graph, so check again at the door.
                    log.error(
                        "REFUSED finding %s: subject_ref %r is not this session's seed",
                        finding.id,
                        finding.subject_ref,
                    )
                    continue
                if finding.id in existing:
                    continue
                self.findings.append(finding)
                existing.add(finding.id)
                added.append(finding)
            if raw_values:
                self.vault.update(raw_values)
            if added:
                self._recompute()
        return added

    def set_persona(self, persona: str) -> ScoreBreakdown:
        """Re-rank without rescanning. The findings do not change."""
        with self._lock:
            self.persona = persona
            self._recompute()
            assert self.score is not None
            return self.score

    def reject_finding(self, finding_id: str, reason: str | None = None) -> CorrectionResult:
        with self._lock:
            result = reject(self.findings, finding_id, reason)
            self.findings = result.findings
            self._recompute()
            return result

    def restore_finding(self, finding_id: str) -> CorrectionResult:
        with self._lock:
            result = restore(self.findings, finding_id)
            self.findings = result.findings
            self._recompute()
            return result

    def edit_finding(
        self, finding_id: str, changes: dict[str, str], reason: str | None = None
    ) -> dict[str, str]:
        with self._lock:
            self.findings, applied = edit(self.findings, finding_id, changes, reason)
            if applied:
                self._recompute()
            return applied

    def simulate(self, fixed_ids: Sequence[str]) -> tuple[ScoreBreakdown, list[str]]:
        """Project the score if these were fixed. Does not mutate the session."""
        with self._lock:
            return simulate_remediation(self.findings, fixed_ids, self.persona)

    # ── reveal ───────────────────────────────────────────────────────────

    def reveal(self, finding_id: str, evidence_key: str, token: str) -> str | None:
        """Exchange a reveal token for the raw value.

        The token is HMAC-verified rather than looked up, so a client cannot
        fish for values it was never shown. Callers are expected to log the
        reveal — it is a deliberate act by the human and belongs in the trail.
        """
        if not verify_reveal_token(token, self.session_id, finding_id, evidence_key):
            log.warning("rejected forged reveal token for %s/%s", finding_id, evidence_key)
            return None
        return self.vault.get(token)

    # ── lifecycle ────────────────────────────────────────────────────────

    def wipe(self) -> dict[str, int]:
        """Destroy everything. The action log survives one call longer than
        the data does, so the UI can render "N findings destroyed" before the
        session object itself goes away."""
        with self._lock:
            counts = {
                "findings": len(self.findings),
                "attack_paths": len(self.attack_paths),
                "vault_entries": len(self.vault),
                "proposals": len(self.proposals),
            }
            self.findings = []
            self.attack_paths = []
            self.attribution = []
            self.proposals = {}
            self.vault.clear()
            self._recompute()
            return counts

    # ── serialization ────────────────────────────────────────────────────

    def snapshot(self, log_tail: int = 25) -> SessionSnapshot:
        """Everything Engineer D needs to render, in one shape."""
        with self._lock:
            assert self.score is not None
            return SessionSnapshot(
                session_id=self.session_id,
                persona=self.persona,
                findings=list(self.findings),
                attack_paths=list(self.attack_paths),
                attribution=list(self.attribution),
                score=self.score,
                pending_proposals=[
                    p for p in self.proposals.values() if p.status.value == "awaiting_approval"
                ],
                action_log_tail=self.log.tail(log_tail),
            )


class SessionStore:
    """In-memory registry. Swappable for A's Redis-backed store.

    Kept behind a tiny interface on purpose: B should not be blocked on A's
    session service landing, and A should be able to substitute the real one
    without touching any caller.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, identity: VerifiedIdentity, persona: str = DEFAULT_PERSONA) -> Session:
        session = Session(session_id=identity.session_id, identity=identity, persona=persona)
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def require(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"unknown session {session_id}")
        return session

    def drop(self, session_id: str) -> dict[str, int] | None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        return session.wipe() if session else None

    def ids(self) -> list[str]:
        return list(self._sessions)

    def stats(self) -> dict[str, Any]:
        return {
            "sessions": len(self._sessions),
            "findings": sum(len(s.findings) for s in self._sessions.values()),
        }


#: Process-wide store. A's service replaces this wholesale.
store = SessionStore()
