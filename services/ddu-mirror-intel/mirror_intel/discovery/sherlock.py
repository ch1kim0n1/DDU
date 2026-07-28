"""Account discovery via Sherlock — handle to accounts you own.

Three things this module takes seriously:

**It can only run against a verified handle.** ``assert_self`` is the first
statement in the entry point. Sherlock itself will happily enumerate anyone;
the gate is ours.

**Its false-positive rate is real and we say so.** Sherlock reports a hit when
a profile URL returns 200, which also happens when a stranger picked your
username, when a site returns a soft-404, and when a site has a catch-all
profile page. Findings therefore come back as ``likely``, not ``confirmed``,
with per-site confidence — and they are the primary feed for the "that's not
me" loop. A tool that presented these as certainties would be generating the
false positives it then asks the user to clean up.

**The site list is capped and results are cached.** Full Sherlock enumeration
is hundreds of HTTP requests and minutes of wall clock. On a 24-hour clock
with a live demo, that is a liability, so we run a curated high-signal subset
and cache by handle.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..guardrails import VerifiedIdentity, assert_self, suppress_third_party
from ..providers import truthy
from ..redaction import redact_evidence
from ..reversibility import classify
from ..schema import Finding, FindingType, Origin, VerificationState

log = logging.getLogger("mirror-intel.sherlock")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_PATH = DATA_DIR / "sherlock_cache.json"

#: High-signal sites only. Each entry carries a base confidence reflecting how
#: often a 200 on that site actually means the handle is the same person.
#: GitHub usernames are globally unique and rarely squatted; Reddit and Medium
#: are common enough words that collisions are routine.
SITES: dict[str, float] = {
    "GitHub": 0.85,
    "LinkedIn": 0.8,
    "Instagram": 0.7,
    "X": 0.7,
    "Reddit": 0.55,
    "Medium": 0.5,
    "Strava": 0.65,
    "Pinterest": 0.5,
    "Twitch": 0.6,
    "Steam": 0.6,
}

#: Base severity per platform — what an account on it discloses about you.
#: LinkedIn is high because its defaults broadcast employer, location, and
#: career history to anyone; Steam is low because it mostly discloses that you
#: play games.
PLATFORM_SEVERITY: dict[str, float] = {
    "linkedin": 0.6,
    "instagram": 0.55,
    "strava": 0.7,
    "github": 0.5,
    "x": 0.45,
    "reddit": 0.5,
    "medium": 0.3,
    "pinterest": 0.3,
    "twitch": 0.35,
    "steam": 0.25,
}


def _load_cache() -> dict[str, Any]:
    try:
        with open(CACHE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _run_sherlock(handle: str, timeout: int = 45) -> list[dict[str, Any]] | None:
    """Shell out to Sherlock if it is installed, otherwise return nothing.

    Deliberately not a hard dependency: the demo path runs from cache, and a
    missing binary should degrade to cached results rather than a 500.
    """
    if not truthy("MIRROR_SHERLOCK_LIVE"):
        log.info("MIRROR_SHERLOCK_LIVE is disabled; using cached results only")
        return None
    binary = shutil.which("sherlock")
    if not binary:
        log.info("sherlock not on PATH; using cached results only")
        return None

    cmd = [binary, handle, "--print-found", "--timeout", "5", "--no-color"]
    for site in SITES:
        cmd += ["--site", site]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("sherlock run failed (%s); using cached results", exc)
        return None
    if proc.returncode not in (0, 1):
        log.warning("sherlock exited %s; using cached results", proc.returncode)
        return None

    results: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        # Sherlock prints found accounts as "[+] SiteName: https://..."
        if not line.startswith("[+]") or ":" not in line:
            continue
        body = line[3:].strip()
        site, _, url = body.partition(":")
        url = url.strip()
        if url.startswith("http"):
            results.append({"site": site.strip(), "url": url, "handle": handle})
    return results


def account_findings(
    identity: VerifiedIdentity,
    handle: str,
    parent_id: str | None = None,
    hop_depth: int = 1,
    use_cache: bool = True,
) -> tuple[list[Finding], dict[str, Any]]:
    """Discover accounts belonging to a **verified** handle.

    Returns the findings plus a report describing what was suppressed, so the
    UI can show the third-party boundary doing its job rather than just
    asserting it exists.
    """
    normalized = assert_self(identity, handle)

    live_results = _run_sherlock(normalized)
    if live_results is None and truthy("MIRROR_REQUIRE_LIVE_PROVIDERS"):
        raise RuntimeError(
            "Sherlock live provider is required but unavailable; refusing cached data"
        )
    raw = live_results or []
    from_cache = False
    if live_results is None and use_cache:
        raw = _load_cache().get(normalized.lstrip("@"), [])
        from_cache = bool(raw)

    # Design rule 2. A handle search returns accounts belonging to whoever
    # holds that handle on each site — which is not always our operator. Every
    # record must be attributable to the verified identity or it is noise.
    for record in raw:
        record.setdefault("handle", normalized)
    report = suppress_third_party(identity, raw, subject_keys=("handle",))

    findings: list[Finding] = []
    for record in report.kept:
        site = str(record.get("site", "unknown"))
        url = str(record.get("url", ""))
        platform = site.lower()
        confidence = float(record.get("confidence", SITES.get(site, 0.5)))
        severity_base = PLATFORM_SEVERITY.get(platform, 0.4)

        finding_id = f"f_acct_{platform}_{abs(hash((normalized, platform))) % 10000:04d}"
        reversible, remediation = classify(
            FindingType.ACCOUNT, record.get("observed_at")
        )

        findings.append(
            Finding(
                id=finding_id,
                parent_id=parent_id,
                hop_depth=hop_depth,
                type=FindingType.ACCOUNT,
                label=f"{site} account under your handle",
                detail=(
                    f"A profile exists at {site} for this handle. Username matches are "
                    "not identity proof — if this isn't yours, reject it and the graph "
                    "will prune everything derived from it."
                ),
                # Never `confirmed`: a 200 on a profile URL is evidence, not proof.
                verification_state=VerificationState.LIKELY
                if confidence >= 0.65
                else VerificationState.HYPOTHESIS,
                confidence=confidence,
                severity_base=severity_base,
                reversible=reversible,
                remediation=remediation,
                platform=platform,
                source=f"sherlock:{site}",
                method="sherlock (curated site subset)" + (" [cached]" if from_cache else ""),
                evidence=redact_evidence(
                    identity.session_id,
                    finding_id,
                    [{"k": "profile_url", "v": url}, {"k": "handle", "v": normalized}],
                ),
                subject_ref=identity.subject_ref,
                origin=Origin.AGENT,
            )
        )

    meta = {
        "worker": "sherlock",
        "live": live_results is not None,
        "sites_checked": len(SITES),
        "from_cache": from_cache,
        "suppressed_third_party": report.suppressed_count,
        "suppressed_kinds": report.suppressed_kinds,
        "false_positive_note": (
            "Username collisions are common. These are reported as likely, not confirmed."
        ),
    }
    return findings, meta
