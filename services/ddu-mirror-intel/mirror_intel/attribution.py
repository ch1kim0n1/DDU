"""Per-platform attribution.

A scan produces a scattered list. Grouped by platform and weighted by
severity, the same list becomes "38% of your exposure traces to LinkedIn
defaults" — which is three settings changes instead of thirty tasks.

Weighting matters here: counting findings per platform would rank a platform
with nine trivial exposures above one with a single catastrophic leak. We
weight by the same persona-adjusted contribution the score uses, so the
attribution chart and the headline number always agree.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from .personas import DEFAULT_PERSONA
from .schema import Finding, PlatformAttribution
from .scoring import contribution

#: Platform-specific hardening advice. Curated rather than generated: it is
#: stable, it is short, and a model writing it fresh each run would be slower
#: and less accurate than a table someone checked once.
HARDENING_HINTS: dict[str, str] = {
    "linkedin": "Settings → Visibility: turn off profile discovery by email and phone, "
    "hide your connections list, and disable profile viewing by search engines.",
    "instagram": "Switch to a private account, turn off location tagging on new posts, "
    "and audit tagged photos — those carry your face on other people's feeds.",
    "github": "Set your commit email to the noreply address, remove your location and "
    "employer from your profile, and check old commits for a real address.",
    "x": "Turn off discoverability by email and phone, and remove location from your bio "
    "and from photo metadata.",
    "twitter": "Turn off discoverability by email and phone, and remove location from your "
    "bio and from photo metadata.",
    "reddit": "Reddit exposes your full comment history publicly — audit it for location, "
    "employer, and schedule details.",
    "facebook": "Privacy Checkup → limit past posts, turn off search-engine indexing, and "
    "restrict friends-list visibility.",
    "strava": "Set a privacy zone around your home and workplace, and make your activity "
    "feed followers-only.",
    "public_records": "Check your county assessor for an address-redaction program, then "
    "work the broker opt-out list.",
    "breach_corpus": "Nothing to configure here — rotate the credentials and add MFA on "
    "every account tied to this address.",
}

_DEFAULT_HINT = (
    "Review this platform's privacy settings for discoverability by email or phone, "
    "public post history, and location tagging."
)


def attribute(
    findings: Sequence[Finding], persona: str = DEFAULT_PERSONA
) -> list[PlatformAttribution]:
    """Group findings by platform, weighted by persona-adjusted severity.

    Findings with no platform (EXIF from a local upload, inferred locations)
    are grouped under ``"your own files"`` rather than dropped — a user whose
    biggest exposure is their own camera roll should see that.
    """
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        if not finding.counts_toward_score:
            continue
        grouped[finding.platform or "your own files"].append(finding)

    rows: list[PlatformAttribution] = []
    for platform, group in grouped.items():
        weighted = sum(contribution(f, persona) for f in group)
        rows.append(
            PlatformAttribution(
                platform=platform,
                finding_count=len(group),
                weighted_severity=round(weighted, 4),
                hardening_hint=HARDENING_HINTS.get(platform.lower(), _DEFAULT_HINT),
            )
        )

    total = sum(r.weighted_severity for r in rows)
    for row in rows:
        row.share = round(row.weighted_severity / total, 4) if total > 0 else 0.0

    rows.sort(key=lambda r: r.weighted_severity, reverse=True)
    return rows
