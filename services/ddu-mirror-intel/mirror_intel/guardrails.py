"""Fail-closed guardrails for the discovery layer.

Engineer A owns the HTTP-level target validation. This module is the second
copy of that assertion, inside the workers, because a guardrail that exists in
exactly one place is a guardrail one refactor away from not existing.

Two invariants live here:

1. **No verified control, no scan.** Every discovery call takes a
   ``VerifiedIdentity`` and asserts the thing it is about to look up is a
   member of it. There is no code path that accepts a free-text target.
2. **No third-party traversal.** Discovery results routinely contain other
   people — the other 400 email addresses in a breach dump, the other accounts
   that happen to match a handle pattern. ``suppress_third_party`` drops them
   before they can become findings, and records the count so the UI can say
   "we saw 14 other people here and threw them away" rather than silently
   discarding.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

log = logging.getLogger("mirror-intel.guardrails")


class TargetRefusedError(Exception):
    """Raised when something asks to scan an identity the session does not
    provably control. Surfaces as HTTP 403 with an explanation — this is the
    live refusal demo, and it must be loud."""

    def __init__(self, requested: str, reason: str, verified: Sequence[str] = ()):
        self.requested = requested
        self.reason = reason
        self.verified = list(verified)
        super().__init__(reason)

    def as_payload(self) -> dict:
        """Body for the 403. Deliberately explains itself: on stage this text
        is what the judges read."""
        return {
            "error": "target_refused",
            "reason": self.reason,
            "requested": redact_for_refusal(self.requested),
            "verified_identity_count": len(self.verified),
            "explanation": (
                "DDU Mirror can only scan identities this session has proven control of. "
                "There is no free-text target field in this product. To scan this identity, "
                "verify it — receive a code at that address or complete OAuth as that account."
            ),
            "design_rule": "1 — no verified control, no scan",
        }


@dataclass(frozen=True)
class VerifiedIdentity:
    """The set of identifiers Engineer A's identity gate has proven the
    operator controls. Discovery cannot reach past this set."""

    session_id: str
    #: Lowercased, whitespace-stripped. Emails, handles, account URLs.
    emails: frozenset[str] = field(default_factory=frozenset)
    handles: frozenset[str] = field(default_factory=frozenset)
    account_urls: frozenset[str] = field(default_factory=frozenset)
    #: Stable reference used as `Finding.subject_ref`.
    subject_ref: str = ""

    @classmethod
    def build(
        cls,
        session_id: str,
        emails: Iterable[str] = (),
        handles: Iterable[str] = (),
        account_urls: Iterable[str] = (),
        subject_ref: str | None = None,
    ) -> "VerifiedIdentity":
        norm_emails = frozenset(_norm(e) for e in emails if _norm(e))
        norm_handles = frozenset(_norm(h).lstrip("@") for h in handles if _norm(h))
        norm_urls = frozenset(_norm(u) for u in account_urls if _norm(u))
        return cls(
            session_id=session_id,
            emails=norm_emails,
            handles=norm_handles,
            account_urls=norm_urls,
            subject_ref=subject_ref or f"subject:{session_id}",
        )

    @property
    def all_identifiers(self) -> frozenset[str]:
        return self.emails | self.handles | self.account_urls

    def controls(self, value: str) -> bool:
        candidate = _norm(value)
        if not candidate:
            return False
        return candidate in self.all_identifiers or candidate.lstrip("@") in self.handles


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def assert_self(identity: VerifiedIdentity, requested: str) -> str:
    """Gate every discovery call. Raises ``TargetRefusedError`` on anything
    outside the verified set.

    Returns the **canonical** stored form of the identifier, not the caller's
    spelling. Callers use the return value as a lookup key — a cache key, an
    API query parameter — so handing back ``@alice`` when the verified set
    holds ``alice`` produces a silent miss rather than a match. Normalizing
    here means every worker downstream is keyed identically.

    This is deliberately the only way into the discovery workers. There is no
    ``force=True``, no admin bypass, and no "trusted caller" flag — every one
    of those would be the hole a judge asks about.
    """
    candidate = _norm(requested)
    if not candidate:
        raise TargetRefusedError(requested, "empty target", identity.all_identifiers)
    if not identity.all_identifiers:
        raise TargetRefusedError(
            requested,
            "this session has no verified identity; complete verification before scanning",
            (),
        )
    if not identity.controls(candidate):
        log.warning(
            "REFUSED scan of unverified target in session %s (verified=%d)",
            identity.session_id,
            len(identity.all_identifiers),
        )
        raise TargetRefusedError(
            requested,
            "requested identity is not in this session's verified set",
            identity.all_identifiers,
        )

    if candidate in identity.emails or candidate in identity.account_urls:
        return candidate
    return candidate.lstrip("@")


def redact_for_refusal(value: str) -> str:
    """Even the refusal must not echo a full identifier back — otherwise the
    403 becomes a free oracle for "does this address exist in your system"."""
    value = (value or "").strip()
    if not value:
        return ""
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain[:1]}***"
    return f"{value[:2]}***"


@dataclass
class SuppressionReport:
    """What we threw away, so the UI can show the boundary working."""

    kept: list[dict]
    suppressed_count: int = 0
    suppressed_kinds: dict[str, int] = field(default_factory=dict)

    def note(self, kind: str) -> None:
        self.suppressed_count += 1
        self.suppressed_kinds[kind] = self.suppressed_kinds.get(kind, 0) + 1


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def suppress_third_party(
    identity: VerifiedIdentity,
    records: Sequence[dict],
    subject_keys: Sequence[str] = ("email", "handle", "username", "account", "url"),
) -> SuppressionReport:
    """Drop every record that is about someone other than the seed identity.

    Design rule 2. A breach dump hands back the whole dump; a handle search
    hands back near-misses. Both contain real people who did not consent to
    being in this session. They are noise, not findings.
    """
    report = SuppressionReport(kept=[])
    for record in records:
        subject_values = [str(record[k]) for k in subject_keys if record.get(k)]
        if not subject_values:
            # A record with nothing identifiable in it cannot be attributed to
            # the seed either. Fail closed.
            report.note("unattributable")
            continue
        if any(identity.controls(v) for v in subject_values):
            report.kept.append(record)
        else:
            report.note("third_party_subject")
    return report


def scrub_incidental_identifiers(text: str, identity: VerifiedIdentity) -> str:
    """Strip other people's identifiers out of free text before it is stored
    as evidence.

    A breach description or a scraped bio can name third parties in prose.
    Nothing downstream needs those, and keeping them would make the evidence
    drawer a small dossier on people who never opted in.
    """
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        return match.group(0) if identity.controls(match.group(0)) else "[third-party redacted]"

    return _EMAIL_RE.sub(_replace, text)
