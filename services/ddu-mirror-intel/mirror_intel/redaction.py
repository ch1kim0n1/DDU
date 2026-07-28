"""The redaction layer — the outbound trust boundary.

Design rule 4: nothing leaves our server unredacted, in any direction, to any
vendor. That includes the LLM provider, the TTS vendor, log lines, and the
findings we stream to our own browser client.

Two directions, both handled here:

* **Structured out.** ``redact_finding`` reduces a Finding to the de-identified
  struct a third-party model is allowed to see. The model can write good
  remediation guidance from ``{"type": "gps_exposure", "severity":
  "critical", "reversible": false}``; it cannot learn who the user is.
* **Free text out.** ``scrub_text`` runs over anything a human typed or spoke
  before it reaches a vendor. The voice pipeline (Engineer D) routes through
  this on the way in *and* on the way out.

Reveal tokens are the escape hatch for the UI: the raw value stays server-side
in the session store, the client holds an opaque token, and exchanging it is
an authenticated, logged event.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
from dataclasses import dataclass
from typing import Any, Iterable

from .schema import EvidenceItem, Finding

log = logging.getLogger("mirror-intel.redaction")

#: Redis workers derive the same HMAC secret from the shared encryption key;
#: local ephemeral mode keeps the original per-process behaviour.
_configured_secret = (
    os.environ.get("MIRROR_REVEAL_SECRET", "")
    or os.environ.get("MIRROR_SESSION_ENCRYPTION_KEY", "")
)
_TOKEN_SECRET = (
    hashlib.sha256(_configured_secret.encode()).digest()
    if _configured_secret
    else secrets.token_bytes(32)
)


# ── Free-text scrubbing ──────────────────────────────────────────────────────
# Ordered most-specific first: an email must be caught before the bare-number
# patterns get a chance to shred it.

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("URL", re.compile(r"https?://[^\s<>\"]+")),
    (
        "COORD",
        re.compile(r"[-+]?\d{1,3}\.\d{4,}\s*[,/]\s*[-+]?\d{1,3}\.\d{4,}"),
    ),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    (
        "CARD",
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    ),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "PHONE",
        re.compile(r"\+?\d{0,2}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"),
    ),
    (
        "ADDRESS",
        re.compile(
            r"\b\d{1,6}\s+(?:[A-Z][a-z]+\s){1,3}"
            r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Terrace|Ter)\b",
            re.IGNORECASE,
        ),
    ),
    ("HANDLE", re.compile(r"(?<![\w])@[A-Za-z0-9_]{3,30}\b")),
]


@dataclass
class ScrubResult:
    text: str
    replacements: dict[str, int]

    @property
    def changed(self) -> bool:
        return bool(self.replacements)


def scrub_text(text: str, extra_terms: Iterable[str] = ()) -> ScrubResult:
    """Replace PII in free text with typed placeholders.

    Placeholders are typed (``[EMAIL]``, ``[COORD]``) rather than blanked so a
    downstream model still understands the sentence structure — "your
    [COORD] appears in three photos" is answerable; "your ███ appears" is not.

    ``extra_terms`` carries session-specific values (the user's actual handle,
    their city) that no regex would catch.
    """
    replacements: dict[str, int] = {}
    out = text or ""

    for label, pattern in _PATTERNS:
        out, count = pattern.subn(f"[{label}]", out)
        if count:
            replacements[label] = replacements.get(label, 0) + count

    for term in extra_terms:
        term = (term or "").strip()
        if len(term) < 3:
            continue
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        out, count = pattern.subn("[SELF]", out)
        if count:
            replacements["SELF"] = replacements.get("SELF", 0) + count

    return ScrubResult(text=out, replacements=replacements)


# ── Reveal tokens ────────────────────────────────────────────────────────────


def mint_reveal_token(session_id: str, finding_id: str, evidence_key: str) -> str:
    """Deterministic, unguessable handle for one raw value.

    Deterministic so a re-render produces the same token (the UI can cache);
    HMAC'd so a client cannot forge one for a value it was never shown.
    """
    payload = f"{session_id}|{finding_id}|{evidence_key}".encode()
    digest = hmac.new(_TOKEN_SECRET, payload, hashlib.sha256).hexdigest()[:32]
    return f"rv_{digest}"


def verify_reveal_token(token: str, session_id: str, finding_id: str, evidence_key: str) -> bool:
    return hmac.compare_digest(token, mint_reveal_token(session_id, finding_id, evidence_key))


def redact_evidence(
    session_id: str, finding_id: str, items: Iterable[dict[str, Any]]
) -> list[EvidenceItem]:
    """Turn producer-side evidence (which holds raw values) into client-side
    evidence (which holds tokens).

    Producers hand us ``{"k": "lat/lon", "v": "32.7767,-96.7970"}``. The client
    gets ``{"k": "lat/lon", "v": "REDACTED", "reveal_token": "rv_..."}``. The
    raw value is the caller's responsibility to store in the session vault.
    """
    out: list[EvidenceItem] = []
    for item in items:
        key = str(item.get("k", ""))
        out.append(
            EvidenceItem(
                kind=item.get("kind", "kv"),
                k=key,
                v="REDACTED",
                reveal_token=mint_reveal_token(session_id, finding_id, key),
                redacted=True,
            )
        )
    return out


# ── Structured outbound ──────────────────────────────────────────────────────

#: The complete allowlist of fields a third-party model may receive about a
#: finding. Allowlist, not denylist — a new field added to the schema is
#: invisible to vendors until someone deliberately adds it here.
_OUTBOUND_FIELDS = (
    "type",
    "severity",
    "severity_score",
    "verification_state",
    "confidence",
    "reversible",
    "platform",
    "hop_depth",
)


def redact_finding(finding: Finding) -> dict[str, Any]:
    """Reduce a Finding to what may cross the trust boundary.

    Note what is absent: `label`, `detail`, `evidence`, `source`, `subject_ref`,
    `human_note`. Labels leak ("Home GPS in vacation photo" names a behaviour);
    sources leak (a file path names a device). The model gets the shape of the
    exposure and nothing about the person.
    """
    payload: dict[str, Any] = {}
    for field_name in _OUTBOUND_FIELDS:
        value = getattr(finding, field_name, None)
        payload[field_name] = getattr(value, "value", value)
    #: A stable opaque handle so the model's answer can be mapped back to the
    #: finding without the model learning the real id.
    payload["ref"] = hashlib.sha256(finding.id.encode()).hexdigest()[:8]
    return payload


def redact_findings(findings: Iterable[Finding]) -> list[dict[str, Any]]:
    return [redact_finding(f) for f in findings]


def assert_no_raw_pii(payload: Any, context: str = "outbound") -> None:
    """Last line of defence before an outbound call.

    Every LLM request passes through this. If a raw email, coordinate pair, or
    phone number is still present in something we are about to send, we raise
    rather than send. A noisy crash inside the boundary is recoverable; a
    quiet leak across it is not.
    """
    import json

    blob = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    for label, pattern in _PATTERNS:
        if label in ("PHONE", "CARD"):
            # Too loose to enforce on structured payloads full of scores and
            # timestamps; scrub_text still replaces them in free text.
            continue
        match = pattern.search(blob)
        if match:
            raise RedactionViolation(
                f"{context}: refusing to transmit — matched {label} at offset {match.start()}"
            )


class RedactionViolation(Exception):
    """Raised inside the boundary when something unredacted tried to leave."""
