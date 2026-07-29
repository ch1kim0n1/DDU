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

import base64
import json
import logging
import os
import secrets
import threading
import time
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
    Effort,
    Finding,
    FindingType,
    Origin,
    PlatformAttribution,
    Proposal,
    Remediation,
    ScoreBreakdown,
    SessionSnapshot,
    VerificationState,
)
from .scoring import apply_persona, compute_score, simulate_remediation

log = logging.getLogger("mirror-intel.session")

#: Stable id for the depth-0 node. Discovery findings parent to it, which is
#: what gives attack paths a root to start from.
SEED_FINDING_ID = "f_seed"


def seed_finding(identity: VerifiedIdentity) -> Finding:
    """The verified identity itself, as a depth-0 node.

    Without this the graph is a flat spray of unparented findings and no
    attack path can form — every worker expands the seed independently, so
    they all land at depth 1 with nothing above them. This node is the "one
    clue" the whole product narrative starts from, and it is what makes
    "here is how far an attacker gets from one clue" literally true on the
    Z axis rather than just a caption.

    It contributes almost nothing to the score (severity_base 0.1, and every
    persona weights it ~0.2) because knowing your own verified email is not
    an exposure — it is the starting point.
    """
    return Finding(
        id=SEED_FINDING_ID,
        parent_id=None,
        hop_depth=0,
        type=FindingType.SEED_IDENTITY,
        label="Verified seed identity",
        detail=(
            "The identity you proved control of. Everything below is reachable "
            "from here — this is the single clue an attacker starts with."
        ),
        verification_state=VerificationState.CONFIRMED,
        confidence=1.0,
        severity_base=0.1,
        reversible=True,
        remediation=Remediation(
            action="Nothing to remediate — this is the identity you verified.",
            effort=Effort.LOW,
        ),
        platform=None,
        source="identity_gate:verified",
        method="operator verification (email code or OAuth)",
        subject_ref=identity.subject_ref,
        origin=Origin.SYSTEM,
    )


@dataclass
class Session:
    session_id: str
    identity: VerifiedIdentity
    persona: str = DEFAULT_PERSONA
    revision: int = 0

    findings: list[Finding] = field(default_factory=list)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    attack_paths: list[AttackPath] = field(default_factory=list)
    attribution: list[PlatformAttribution] = field(default_factory=list)
    score: ScoreBreakdown | None = None

    #: reveal_token -> raw value. Never serialized, never logged, never sent
    #: to a vendor. Dies with the session.
    vault: dict[str, str] = field(default_factory=dict)
    #: Serializable orchestration internals (pending full inputs, cancellation
    #: state, proposal sequence). Never returned in SessionSnapshot.
    workflow_state: dict[str, Any] = field(default_factory=dict)

    log: ActionLog = field(init=False)
    _lock: threading.RLock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.log = ActionLog(self.session_id)
        self._lock = threading.RLock()
        if not any(f.id == SEED_FINDING_ID for f in self.findings):
            self.findings.insert(0, seed_finding(self.identity))
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

    def export_state(self) -> dict[str, Any]:
        """Serializable, complete state for an encrypted backend."""
        with self._lock:
            return {
                "version": 1,
                "revision": self.revision,
                "session_id": self.session_id,
                "identity": {
                    "emails": sorted(self.identity.emails),
                    "handles": sorted(self.identity.handles),
                    "account_urls": sorted(self.identity.account_urls),
                    "subject_ref": self.identity.subject_ref,
                },
                "persona": self.persona,
                "findings": [finding.model_dump(mode="json") for finding in self.findings],
                "proposals": {
                    proposal_id: proposal.model_dump(mode="json")
                    for proposal_id, proposal in self.proposals.items()
                },
                "vault": dict(self.vault),
                "workflow_state": self.workflow_state,
                "action_log": [
                    entry.model_dump(mode="json") for entry in self.log.entries()
                ],
            }

    @classmethod
    def import_state(cls, payload: dict[str, Any]) -> "Session":
        if payload.get("version") != 1:
            raise ValueError("unsupported persisted session version")
        session_id = str(payload["session_id"])
        identity_payload = dict(payload["identity"])
        identity = VerifiedIdentity.build(
            session_id=session_id,
            emails=identity_payload.get("emails", []),
            handles=identity_payload.get("handles", []),
            account_urls=identity_payload.get("account_urls", []),
            subject_ref=str(identity_payload["subject_ref"]),
        )
        session = cls(
            session_id=session_id,
            identity=identity,
            persona=str(payload.get("persona", DEFAULT_PERSONA)),
            revision=int(payload.get("revision", 0)),
        )
        session.findings = [
            Finding.model_validate(item) for item in payload.get("findings", [])
        ]
        session.proposals = {
            str(proposal_id): Proposal.model_validate(item)
            for proposal_id, item in dict(payload.get("proposals", {})).items()
        }
        session.vault = {
            str(key): str(value) for key, value in dict(payload.get("vault", {})).items()
        }
        session.workflow_state = dict(payload.get("workflow_state", {}))
        session.log.restore(list(payload.get("action_log", [])))
        session._recompute()
        return session


class SessionStore:
    """In-memory registry. Swappable for A's Redis-backed store.

    Kept behind a tiny interface on purpose: B should not be blocked on A's
    session service landing, and A should be able to substitute the real one
    without touching any caller.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._created_at: dict[str, float] = {}
        self._created_ip: dict[str, str] = {}
        self._lock = threading.Lock()
        self._ttl = int(
            ttl_seconds
            if ttl_seconds is not None
            else os.environ.get("MIRROR_SESSION_TTL_SECONDS", "1800")
        )

    def create(
        self,
        identity: VerifiedIdentity,
        persona: str = DEFAULT_PERSONA,
        created_ip: str = "",
    ) -> Session:
        session = Session(session_id=identity.session_id, identity=identity, persona=persona)
        with self._lock:
            self._sessions[session.session_id] = session
            self._created_at[session.session_id] = time.time()
            if created_ip:
                self._created_ip[session.session_id] = created_ip
        return session

    def note_access_ip(self, session_id: str, ip: str) -> None:
        """Log when a session is accessed from a different IP than creation."""
        if not ip:
            return
        with self._lock:
            created = self._created_ip.get(session_id)
            if created and created != ip:
                log.warning(
                    "session_ip_mismatch",
                    extra={
                        "session_id": session_id,
                        "created_ip": created,
                        "access_ip": ip,
                    },
                )

    @property
    def backend_name(self) -> str:
        return "memory"

    @property
    def ttl_seconds(self) -> int | None:
        return self._ttl

    def persist(self, session: Session) -> None:
        """Memory sessions are already live; durable stores override this."""

    def healthy(self) -> bool:
        return True

    def _expire_locked(self, session_id: str) -> None:
        created = self._created_at.get(session_id)
        if created is None or self._ttl <= 0:
            return
        age = time.time() - created
        if age <= self._ttl:
            return
        session = self._sessions.pop(session_id, None)
        self._created_at.pop(session_id, None)
        self._created_ip.pop(session_id, None)
        if session is not None:
            session.wipe()
            log.info(
                "session_auto_expired",
                extra={"session_id": session_id, "age_seconds": int(age)},
            )

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            self._expire_locked(session_id)
            return self._sessions.get(session_id)

    def require(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"unknown session {session_id}")
        return session

    def drop(self, session_id: str) -> dict[str, int] | None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            self._created_at.pop(session_id, None)
            self._created_ip.pop(session_id, None)
        return session.wipe() if session else None

    def ids(self) -> list[str]:
        with self._lock:
            for session_id in list(self._sessions):
                self._expire_locked(session_id)
            return list(self._sessions)

    def stats(self) -> dict[str, Any]:
        ids = self.ids()
        return {
            "sessions": len(ids),
            "findings": sum(
                len(self._sessions[sid].findings) for sid in ids if sid in self._sessions
            ),
            "backend": self.backend_name,
            "ttl_seconds": self.ttl_seconds,
        }


class SessionConflictError(RuntimeError):
    """A different worker updated the session after this request loaded it."""


class RedisSessionStore(SessionStore):
    """Encrypted Redis session registry with sliding TTL and optimistic CAS."""

    def __init__(
        self,
        redis_url: str,
        encryption_key: str,
        *,
        ttl_seconds: int = 1800,
        key_prefix: str = "ddu:mirror:session:",
    ) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from redis import Redis

        try:
            padding = "=" * (-len(encryption_key) % 4)
            key = base64.urlsafe_b64decode(encryption_key + padding)
        except Exception as exc:
            raise RuntimeError("MIRROR_SESSION_ENCRYPTION_KEY is not valid base64") from exc
        if len(key) != 32:
            raise RuntimeError(
                "MIRROR_SESSION_ENCRYPTION_KEY must decode to exactly 32 bytes"
            )
        if ttl_seconds < 60:
            raise RuntimeError("MIRROR_SESSION_TTL_SECONDS must be at least 60")
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._aes = AESGCM(key)
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    @staticmethod
    def generate_encryption_key() -> str:
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    @property
    def backend_name(self) -> str:
        return "redis-encrypted"

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def _encode(self, session: Session) -> str:
        key = self._key(session.session_id)
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(
            session.export_state(), separators=(",", ":"), sort_keys=True
        ).encode()
        ciphertext = self._aes.encrypt(nonce, plaintext, key.encode())
        return json.dumps(
            {
                "version": 1,
                "revision": session.revision,
                "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
            },
            separators=(",", ":"),
        )

    def _decode(self, key: str, encoded: str) -> Session:
        envelope = json.loads(encoded)
        if envelope.get("version") != 1:
            raise ValueError("unsupported encrypted session envelope")
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        plaintext = self._aes.decrypt(nonce, ciphertext, key.encode())
        payload = json.loads(plaintext)
        session = Session.import_state(payload)
        if session.revision != int(envelope["revision"]):
            raise ValueError("persisted session revision mismatch")
        return session

    def create(
        self,
        identity: VerifiedIdentity,
        persona: str = DEFAULT_PERSONA,
        created_ip: str = "",
    ) -> Session:
        session = Session(session_id=identity.session_id, identity=identity, persona=persona)
        if not self._client.set(
            self._key(session.session_id),
            self._encode(session),
            ex=self._ttl,
            nx=True,
        ):
            raise ValueError(f"session {session.session_id} already exists")
        if created_ip:
            self._client.set(
                f"{self._key(session.session_id)}:ip",
                created_ip,
                ex=self._ttl,
            )
        return session

    def note_access_ip(self, session_id: str, ip: str) -> None:
        if not ip:
            return
        created = self._client.get(f"{self._key(session_id)}:ip")
        if created and created != ip:
            log.warning(
                "session_ip_mismatch",
                extra={
                    "session_id": session_id,
                    "created_ip": created,
                    "access_ip": ip,
                },
            )

    def get(self, session_id: str) -> Session | None:
        key = self._key(session_id)
        encoded = self._client.get(key)
        if encoded is None:
            return None
        self._client.expire(key, self._ttl)
        return self._decode(key, encoded)

    def persist(self, session: Session) -> None:
        from redis import WatchError

        key = self._key(session.session_id)
        expected = session.revision
        with self._client.pipeline() as pipeline:
            try:
                pipeline.watch(key)
                current = pipeline.get(key)
                if current is None:
                    raise KeyError(f"unknown or expired session {session.session_id}")
                envelope = json.loads(current)
                if int(envelope["revision"]) != expected:
                    raise SessionConflictError(
                        "session changed on another worker; refresh and retry"
                    )
                session.revision = expected + 1
                encoded = self._encode(session)
                pipeline.multi()
                pipeline.set(key, encoded, ex=self._ttl)
                pipeline.execute()
            except WatchError as exc:
                session.revision = expected
                raise SessionConflictError(
                    "session changed on another worker; refresh and retry"
                ) from exc
            except Exception:
                session.revision = expected
                raise

    def drop(self, session_id: str) -> dict[str, int] | None:
        session = self.get(session_id)
        if session is None:
            return None
        counts = session.wipe()
        self._client.delete(self._key(session_id))
        return counts

    def ids(self) -> list[str]:
        return [
            key.removeprefix(self._prefix)
            for key in self._client.scan_iter(match=f"{self._prefix}*")
        ]

    def stats(self) -> dict[str, Any]:
        session_ids = self.ids()
        findings = 0
        for session_id in session_ids:
            session = self.get(session_id)
            findings += len(session.findings) if session else 0
        return {
            "sessions": len(session_ids),
            "findings": findings,
            "backend": self.backend_name,
            "ttl_seconds": self.ttl_seconds,
        }

    def healthy(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            return False


def _redis_with_retry(client: Any, op: str, *args: Any, **kwargs: Any) -> Any:
    """3 retries with exponential backoff (100/200/400ms)."""
    delays = (0.1, 0.2, 0.4)
    last: Exception | None = None
    for attempt, delay in enumerate(delays):
        try:
            return getattr(client, op)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.warning("redis_%s_retry", op, extra={"attempt": attempt + 1, "error": str(exc)})
            time.sleep(delay)
    raise RuntimeError(f"redis {op} failed after retries: {last}")


def build_session_store() -> SessionStore:
    redis_url = os.environ.get("MIRROR_REDIS_URL", "").strip()
    ttl = int(os.environ.get("MIRROR_SESSION_TTL_SECONDS", "1800"))
    if not redis_url:
        return SessionStore(ttl_seconds=ttl)
    encryption_key = os.environ.get("MIRROR_SESSION_ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        raise RuntimeError(
            "MIRROR_REDIS_URL requires MIRROR_SESSION_ENCRYPTION_KEY so PII is "
            "never written to Redis in plaintext"
        )
    try:
        from redis import ConnectionPool, Redis

        pool = ConnectionPool.from_url(redis_url, max_connections=20)
        store = RedisSessionStore(
            redis_url,
            encryption_key,
            ttl_seconds=ttl,
        )
        client = Redis(connection_pool=pool, decode_responses=True)
        _redis_with_retry(client, "ping")
        store._client = client
        log.info("session_store: redis pooled")
        return store
    except Exception as exc:  # noqa: BLE001
        log.error("redis unavailable (%s); falling back to in-memory store", exc)
        return SessionStore(ttl_seconds=ttl)


store = build_session_store()
