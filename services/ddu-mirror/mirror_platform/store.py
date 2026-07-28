"""Ephemeral trust-boundary state for DDU Mirror.

This module contains raw email addresses only for the lifetime of a verified
session.  Nothing here calls discovery providers; Part B can only obtain a
verified identity capability after this service has issued it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .personas import PERSONAS

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat()


def redact(value: str) -> str:
    """Keep audit records useful without retaining an email or a code."""
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain}"
    return "[REDACTED]"


class TrustError(ValueError):
    def __init__(self, code: str, explanation: str, status_code: int = 403) -> None:
        super().__init__(explanation)
        self.code = code
        self.explanation = explanation
        self.status_code = status_code

    def payload(self) -> dict[str, str]:
        return {"error": self.code, "explanation": self.explanation}


@dataclass
class AuditEvent:
    action: str
    at: str = field(default_factory=stamp)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Challenge:
    id: str
    email: str
    code_digest: str
    purpose: str
    adult_confirmed: bool
    persona: str
    guess: str | None
    expires_at: datetime
    session_id: str | None = None
    attempts: int = 0


@dataclass
class MirrorSession:
    id: str
    email: str
    persona: str
    created_at: datetime
    expires_at: datetime
    guess: str | None = None
    biometric_consent_at: datetime | None = None
    biometric_expires_at: datetime | None = None
    step_up_until: datetime | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    audit: list[AuditEvent] = field(default_factory=list)

    def active(self) -> bool:
        return now() < self.expires_at

    def snapshot(self) -> dict[str, Any]:
        seconds = 0
        if self.biometric_expires_at:
            seconds = max(0, int((self.biometric_expires_at - now()).total_seconds()))
        return {
            "session_id": self.id,
            "verified_identity": {"email": redact(self.email), "verified": True},
            "persona": self.persona,
            "expires_at": self.expires_at.isoformat(),
            "guess_first": self.guess,
            "biometric": {
                "consented": self.biometric_consent_at is not None,
                "template_expires_at": self.biometric_expires_at.isoformat() if self.biometric_expires_at else None,
                "destruction_countdown_seconds": seconds,
            },
            "step_up_verified": bool(self.step_up_until and self.step_up_until > now()),
            "finding_count": len(self.findings),
        }


class SessionStore:
    """Thread-safe in-memory development store with TTL semantics.

    The API is deliberately narrow so its backing can be replaced by Redis in
    deployment.  Session expiry and explicit deletion follow the same wipe
    path, preventing development behavior from becoming a privacy exception.
    """

    def __init__(self, session_ttl_minutes: int = 60, code_ttl_minutes: int = 10) -> None:
        self.session_ttl = timedelta(minutes=session_ttl_minutes)
        self.code_ttl = timedelta(minutes=code_ttl_minutes)
        self._challenges: dict[str, Challenge] = {}
        self._sessions: dict[str, MirrorSession] = {}
        self._active_by_email: dict[str, str] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = threading.RLock()

    def _audit(self, session: MirrorSession, action: str, **detail: Any) -> None:
        session.audit.append(AuditEvent(action=action, detail=detail))

    def _expire_locked(self) -> None:
        for challenge_id, challenge in list(self._challenges.items()):
            if challenge.expires_at <= now() or challenge.attempts >= 3:
                self._challenges.pop(challenge_id, None)
        for session_id, session in list(self._sessions.items()):
            if not session.active():
                self._destroy_locked(session_id, "ttl_expired")

    def issue_code(self, email: str, *, adult_confirmed: bool, persona: str, guess: str | None, purpose: str = "verify", session_id: str | None = None) -> tuple[Challenge, str]:
        normalized = email.strip().lower()
        if not EMAIL_RE.fullmatch(normalized):
            raise TrustError("invalid_email", "Enter a valid email address.", 422)
        if not adult_confirmed:
            raise TrustError("adult_confirmation_required", "DDU Mirror is available only to people 18 or older.", 403)
        if persona not in PERSONAS:
            raise TrustError("invalid_persona", "Choose one of the supported threat-model personas.", 422)
        with self._lock:
            self._expire_locked()
            if purpose == "verify" and normalized in self._active_by_email:
                raise TrustError("active_scan_exists", "This verified identity already has an active scan. End it before starting another.", 429)
            code = f"{secrets.randbelow(1_000_000):06d}"
            challenge = Challenge(
                id=f"vc_{uuid4().hex}", email=normalized,
                code_digest=hashlib.sha256(code.encode()).hexdigest(), purpose=purpose,
                adult_confirmed=adult_confirmed, persona=persona, guess=guess,
                expires_at=now() + self.code_ttl, session_id=session_id,
            )
            self._challenges[challenge.id] = challenge
            return challenge, code

    def verify_code(self, challenge_id: str, code: str) -> MirrorSession:
        with self._lock:
            self._expire_locked()
            challenge = self._challenges.get(challenge_id)
            if not challenge:
                raise TrustError("verification_expired", "That verification code has expired. Request a new one.", 403)
            challenge.attempts += 1
            supplied = hashlib.sha256(code.strip().encode()).hexdigest()
            if not hmac.compare_digest(challenge.code_digest, supplied):
                remaining = max(0, 3 - challenge.attempts)
                raise TrustError("invalid_verification_code", f"That code is not valid. {remaining} attempt(s) remain.", 403)
            self._challenges.pop(challenge_id, None)
            if challenge.purpose == "step_up":
                session = self._sessions.get(challenge.session_id or "")
                if session is None:
                    raise TrustError("unknown_session", "The session no longer exists.", 404)
                session.step_up_until = now() + timedelta(minutes=10)
                self._audit(session, "step_up_verified")
                return session
            session = MirrorSession(
                id=f"ms_{uuid4().hex}", email=challenge.email, persona=challenge.persona,
                guess=challenge.guess, created_at=now(), expires_at=now() + self.session_ttl,
            )
            self._sessions[session.id] = session
            self._active_by_email[session.email] = session.id
            self._audit(session, "identity_verified", identity=redact(session.email), persona=session.persona)
            return session

    def get(self, session_id: str) -> MirrorSession:
        with self._lock:
            self._expire_locked()
            session = self._sessions.get(session_id)
            if session is None:
                raise TrustError("unknown_session", "This session has ended or does not exist.", 404)
            return session

    def authorize_scan(self, session_id: str) -> MirrorSession:
        """The fail-closed gate. There is no target parameter in this API."""
        session = self.get(session_id)
        self._audit(session, "scan_authorized")
        return session

    def issue_step_up(self, session_id: str) -> tuple[Challenge, str]:
        session = self.get(session_id)
        return self.issue_code(session.email, adult_confirmed=True, persona=session.persona, guess=None, purpose="step_up", session_id=session.id)

    def biometric_consent(self, session_id: str, accepted: bool, template_ttl_seconds: int = 300) -> MirrorSession:
        session = self.get(session_id)
        if not accepted:
            self._audit(session, "biometric_skipped")
            return session
        session.biometric_consent_at = now()
        session.biometric_expires_at = now() + timedelta(seconds=template_ttl_seconds)
        self._audit(session, "biometric_consent_granted", template_ttl_seconds=template_ttl_seconds)
        return session

    def add_findings(self, session_id: str, findings: list[dict[str, Any]]) -> MirrorSession:
        session = self.authorize_scan(session_id)
        # The gateway never accepts an identity or raw values from a producer.
        # Part B/C findings must already be redacted and tied to this session.
        safe = [{k: v for k, v in item.items() if k not in {"email", "coordinates", "raw_value", "subject_ref"}} for item in findings]
        session.findings.extend(safe)
        self._audit(session, "findings_ingested", count=len(safe))
        return session

    def _destroy_locked(self, session_id: str, reason: str) -> dict[str, int]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return {"findings": 0, "audit_events": 0, "face_template": 0}
        self._active_by_email.pop(session.email, None)
        counts = {"findings": len(session.findings), "audit_events": len(session.audit), "face_template": int(session.biometric_expires_at is not None)}
        session.findings.clear()
        session.biometric_expires_at = None
        self._subscribers.pop(session_id, None)
        return counts

    def destroy(self, session_id: str, reason: str = "operator_request") -> dict[str, int]:
        with self._lock:
            self._expire_locked()
            if session_id not in self._sessions:
                raise TrustError("unknown_session", "This session has ended or does not exist.", 404)
            return self._destroy_locked(session_id, reason)

    def audit(self, session_id: str) -> list[dict[str, Any]]:
        session = self.get(session_id)
        return [{"action": e.action, "at": e.at, "detail": e.detail} for e in session.audit]

    async def broadcast(self, session_id: str, event: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers.get(session_id, set())):
            await queue.put(event)

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        self.get(session_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.get(session_id, set()).discard(queue)


class RedisSessionStore(SessionStore):
    """Redis-backed production session store.

    Verification challenges remain process-local because they are short lived
    and never survive a deployment; all verified-session state, including the
    active-scan lock, uses Redis keys with the session's exact remaining TTL.
    """

    def __init__(self, redis_url: str, session_ttl_minutes: int = 60, code_ttl_minutes: int = 10) -> None:
        super().__init__(session_ttl_minutes=session_ttl_minutes, code_ttl_minutes=code_ttl_minutes)
        import redis

        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _key(session_id: str) -> str:
        return f"ddu-mirror:session:{session_id}"

    @staticmethod
    def _active_key(email: str) -> str:
        return f"ddu-mirror:active:{hashlib.sha256(email.encode()).hexdigest()}"

    def _encode(self, session: MirrorSession) -> str:
        return json.dumps({
            "id": session.id, "email": session.email, "persona": session.persona,
            "created_at": session.created_at.isoformat(), "expires_at": session.expires_at.isoformat(),
            "guess": session.guess,
            "biometric_consent_at": session.biometric_consent_at.isoformat() if session.biometric_consent_at else None,
            "biometric_expires_at": session.biometric_expires_at.isoformat() if session.biometric_expires_at else None,
            "step_up_until": session.step_up_until.isoformat() if session.step_up_until else None,
            "findings": session.findings,
            "audit": [{"action": item.action, "at": item.at, "detail": item.detail} for item in session.audit],
        }, separators=(",", ":"))

    def _decode(self, encoded: str) -> MirrorSession:
        value = json.loads(encoded)
        session = MirrorSession(
            id=value["id"], email=value["email"], persona=value["persona"],
            created_at=datetime.fromisoformat(value["created_at"]), expires_at=datetime.fromisoformat(value["expires_at"]),
            guess=value.get("guess"),
            biometric_consent_at=datetime.fromisoformat(value["biometric_consent_at"]) if value.get("biometric_consent_at") else None,
            biometric_expires_at=datetime.fromisoformat(value["biometric_expires_at"]) if value.get("biometric_expires_at") else None,
            step_up_until=datetime.fromisoformat(value["step_up_until"]) if value.get("step_up_until") else None,
            findings=list(value.get("findings", [])),
            audit=[AuditEvent(**item) for item in value.get("audit", [])],
        )
        return session

    def _persist(self, session: MirrorSession) -> None:
        ttl = max(1, math.ceil((session.expires_at - now()).total_seconds()))
        pipe = self._redis.pipeline()
        pipe.setex(self._key(session.id), ttl, self._encode(session))
        pipe.setex(self._active_key(session.email), ttl, session.id)
        pipe.execute()

    def issue_code(self, email: str, **kwargs: Any) -> tuple[Challenge, str]:
        normalized = email.strip().lower()
        if kwargs.get("purpose", "verify") == "verify" and self._redis.get(self._active_key(normalized)):
            raise TrustError("active_scan_exists", "This verified identity already has an active scan. End it before starting another.", 429)
        return super().issue_code(email, **kwargs)

    def verify_code(self, challenge_id: str, code: str) -> MirrorSession:
        session = super().verify_code(challenge_id, code)
        self._persist(session)
        return session

    def get(self, session_id: str) -> MirrorSession:
        try:
            return super().get(session_id)
        except TrustError as exc:
            if exc.code != "unknown_session":
                raise
        encoded = self._redis.get(self._key(session_id))
        if not encoded:
            raise TrustError("unknown_session", "This session has ended or does not exist.", 404)
        session = self._decode(encoded)
        if not session.active():
            self._redis.delete(self._key(session_id), self._active_key(session.email))
            raise TrustError("unknown_session", "This session has ended or does not exist.", 404)
        with self._lock:
            self._sessions[session.id] = session
            self._active_by_email[session.email] = session.id
        return session

    def authorize_scan(self, session_id: str) -> MirrorSession:
        session = super().authorize_scan(session_id)
        self._persist(session)
        return session

    def biometric_consent(self, session_id: str, accepted: bool, template_ttl_seconds: int = 300) -> MirrorSession:
        session = super().biometric_consent(session_id, accepted, template_ttl_seconds)
        self._persist(session)
        return session

    def add_findings(self, session_id: str, findings: list[dict[str, Any]]) -> MirrorSession:
        session = super().add_findings(session_id, findings)
        self._persist(session)
        return session

    def destroy(self, session_id: str, reason: str = "operator_request") -> dict[str, int]:
        session = self.get(session_id)
        counts = super().destroy(session_id, reason)
        self._redis.delete(self._key(session.id), self._active_key(session.email))
        return counts


def build_store() -> SessionStore:
    """Use Redis whenever deployment supplies its URL; otherwise stay local."""
    redis_url = os.getenv("MIRROR_REDIS_URL")
    return RedisSessionStore(redis_url) if redis_url else SessionStore()


def receipt_for(session: MirrorSession) -> dict[str, Any]:
    return {
        "receipt_version": "1.0",
        "session_id": session.id,
        "identity": {"email": redact(session.email), "verified": True},
        "persona": session.persona,
        "issued_at": stamp(),
        "data_lifecycle": {"session_expires_at": session.expires_at.isoformat(), "ephemeral": True},
        "consents": {"adult": True, "biometric": session.biometric_consent_at is not None},
        "sources_touched": sorted({str(f.get("source", "unknown")) for f in session.findings}),
    }


class ReceiptSigner:
    def __init__(self) -> None:
        raw = os.getenv("MIRROR_CONSENT_SIGNING_KEY")
        self._key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw)) if raw else Ed25519PrivateKey.generate()

    def sign(self, receipt: dict[str, Any]) -> dict[str, Any]:
        canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        signature = self._key.sign(canonical)
        public = self._key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return {**receipt, "signature": {"algorithm": "Ed25519", "value": base64.b64encode(signature).decode(), "public_key": base64.b64encode(public).decode()}}
