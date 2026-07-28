"""Breach exposure via Have I Been Pwned.

Two operational notes that matter more than the code:

**The email-search endpoint requires a paid key.** ``breachedaccount`` is not
free. The spec says confirm this in hour zero and it is right — discovering it
at hour eighteen is how a demo loses its most visceral finding. This module
therefore has a first-class cached path, and every finding it produces carries
``method`` text stating whether it came from the live API or from cached demo
data. Saying "this is cached, here's why" on stage costs nothing; being caught
presenting cached data as live costs everything.

**A breach record is the canonical irreversible finding.** You cannot un-leak
a password. This is where the reversibility argument earns its keep, and where
the remediation simulation visibly refuses.

Third-party suppression matters here more than anywhere: a breach *corpus*
contains millions of other people. We query for exactly one address — the
verified one — and never enumerate a dump.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..guardrails import VerifiedIdentity, assert_self, scrub_incidental_identifiers
from ..providers import truthy
from ..redaction import redact_evidence
from ..reversibility import classify
from ..schema import Finding, FindingType, Origin, VerificationState

log = logging.getLogger("mirror-intel.hibp")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_PATH = DATA_DIR / "hibp_cache.json"

API_ROOT = "https://haveibeenpwned.com/api/v3"

#: Data classes that raise a breach's severity, and by how much. A dump of
#: email addresses is unpleasant; a dump with passwords and security questions
#: is an account-takeover kit.
SEVERITY_WEIGHTS: dict[str, float] = {
    "Passwords": 0.35,
    "Password hints": 0.2,
    "Security questions and answers": 0.25,
    "Physical addresses": 0.3,
    "Phone numbers": 0.15,
    "Dates of birth": 0.15,
    "Government issued IDs": 0.4,
    "Partial credit card data": 0.2,
    "Geographic locations": 0.15,
    "Social security numbers": 0.45,
}


def _load_cache() -> dict[str, Any]:
    try:
        with open(CACHE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _fetch_live(email: str, timeout: float = 10.0) -> list[dict[str, Any]] | None:
    """Query HIBP. Returns None when unavailable — distinct from "no breaches"."""
    api_key = os.environ.get("HIBP_API_KEY")
    if not api_key:
        log.info("HIBP_API_KEY unset; cached breach data only")
        return None

    try:
        import httpx
    except ImportError:
        log.warning("httpx unavailable; cached breach data only")
        return None

    try:
        response = httpx.get(
            f"{API_ROOT}/breachedaccount/{email}",
            params={"truncateResponse": "false"},
            headers={
                "hibp-api-key": api_key,
                "user-agent": "DDU-Mirror/0.1 (defensive self-scan)",
            },
            timeout=timeout,
        )
    except Exception as exc:  # network, DNS, TLS — all the same to us here
        log.warning("HIBP request failed (%s); falling back to cache", exc)
        return None

    if response.status_code == 404:
        return []  # genuinely no breaches — a real, good answer
    if response.status_code == 401:
        log.error("HIBP rejected the API key — check the subscription tier")
        return None
    if response.status_code != 200:
        log.warning("HIBP returned %s; falling back to cache", response.status_code)
        return None

    try:
        return response.json()
    except json.JSONDecodeError:
        return None


def _severity_for(data_classes: list[str], year: int | None) -> float:
    base = 0.45
    for cls in data_classes:
        base += SEVERITY_WEIGHTS.get(cls, 0.03)
    # Recency matters for credential-stuffing viability, but old breaches
    # never become harmless — they become permanent. Floor it accordingly.
    if year and year < 2015:
        base *= 0.85
    return max(0.3, min(1.0, base))


def breach_findings(
    identity: VerifiedIdentity,
    email: str,
    parent_id: str | None = None,
    hop_depth: int = 1,
) -> tuple[list[Finding], dict[str, Any]]:
    """Look up breach records for a **verified** email address."""
    normalized = assert_self(identity, email)

    records = _fetch_live(normalized)
    live = records is not None
    if not live:
        if truthy("MIRROR_REQUIRE_LIVE_PROVIDERS"):
            raise RuntimeError(
                "HIBP live provider is required but unavailable; refusing cached data"
            )
        records = _load_cache().get(normalized, [])

    findings: list[Finding] = []
    for record in records or []:
        name = str(record.get("Name", "unknown"))
        title = str(record.get("Title", name))
        breach_date = str(record.get("BreachDate", ""))
        year = int(breach_date[:4]) if breach_date[:4].isdigit() else None
        data_classes = [str(c) for c in record.get("DataClasses", [])]
        verified_by_hibp = bool(record.get("IsVerified", True))

        finding_id = f"f_breach_{name.lower()[:12]}_{abs(hash(name)) % 1000:03d}"
        reversible, remediation = classify(FindingType.BREACH, breach_date or None)

        # Prose from an external source can name other people. Strip that
        # before it becomes stored evidence (design rule 2).
        description = scrub_incidental_identifiers(
            str(record.get("Description", ""))[:400], identity
        )

        findings.append(
            Finding(
                id=finding_id,
                parent_id=parent_id,
                hop_depth=hop_depth,
                type=FindingType.BREACH,
                label=f"{title} breach ({year or 'date unknown'})",
                detail=(
                    f"Your address appears in the {title} breach. "
                    f"Exposed: {', '.join(data_classes) or 'unspecified'}. "
                    "This data is mirrored and resold — it cannot be withdrawn."
                ),
                # HIBP-verified breaches are corroborated dumps; unverified
                # ones are claims, and the schema has a state for that.
                verification_state=VerificationState.CONFIRMED
                if verified_by_hibp
                else VerificationState.LIKELY,
                confidence=0.95 if verified_by_hibp else 0.6,
                severity_base=_severity_for(data_classes, year),
                reversible=reversible,
                remediation=remediation,
                platform="breach_corpus",
                source=f"hibp:{name}",
                method="HIBP API v3" if live else "HIBP cached demo data (disclosed)",
                evidence=redact_evidence(
                    identity.session_id,
                    finding_id,
                    [
                        {"k": "breach", "v": title},
                        {"k": "date", "v": breach_date},
                        {"k": "data_classes", "v": ", ".join(data_classes)},
                        {"k": "description", "v": description},
                    ],
                ),
                subject_ref=identity.subject_ref,
                origin=Origin.AGENT,
            )
        )

    meta = {
        "worker": "hibp",
        "live": live,
        "breach_count": len(findings),
        "disclosure": None
        if live
        else "Breach data served from a cached demo set — say so on stage.",
    }
    return findings, meta
