"""Mock findings generator.

Ship this in the first hour. Engineers C and D can build the 3D scene, the
evidence drawer, and the voice grounding against schema-valid fake data from
minute thirty, instead of waiting on real discovery to land. That is the whole
justification for the file: it is the cheapest thing B can hand over that
unblocks two people.

Everything it emits is real ``Finding`` objects through the real constructor,
so a schema change breaks the mocks immediately rather than letting the
frontend drift against a shape the backend no longer produces.

It's deterministic — seeded by ``session_id`` — so the demo looks the same on
every run and a screenshot from an hour ago still matches. Every mock finding
carries ``source="mock:generator"``, so nothing fake can be mistaken for real
in the UI or on stage.
"""

from __future__ import annotations

import random
from typing import Any

from .guardrails import VerifiedIdentity
from .redaction import redact_evidence
from .reversibility import classify
from .schema import (
    Finding,
    FindingType,
    Origin,
    VerificationState,
)

#: (type, label, detail, severity_base, confidence, state, platform, hop, parent_key)
_TEMPLATES: list[tuple[Any, ...]] = [
    (
        FindingType.SEED_IDENTITY,
        "Verified seed identity",
        "The identity you proved control of. Everything below is reachable from here.",
        0.1,
        1.0,
        VerificationState.CONFIRMED,
        None,
        0,
        None,
    ),
    (
        FindingType.BREACH,
        "2019 forum breach",
        "Your address appears in a 2019 credential dump alongside a password hash. "
        "This data is mirrored and resold — it cannot be withdrawn.",
        0.85,
        0.95,
        VerificationState.CONFIRMED,
        "breach_corpus",
        1,
        "seed",
    ),
    (
        FindingType.ACCOUNT,
        "LinkedIn account under your handle",
        "A LinkedIn profile exists for this handle, with default discoverability "
        "settings that broadcast employer and location.",
        0.6,
        0.82,
        VerificationState.LIKELY,
        "linkedin",
        1,
        "seed",
    ),
    (
        FindingType.ACCOUNT,
        "GitHub account under your handle",
        "A GitHub profile exists for this handle. Commit metadata is public by default.",
        0.5,
        0.88,
        VerificationState.LIKELY,
        "github",
        1,
        "seed",
    ),
    (
        FindingType.ACCOUNT,
        "Reddit account under your handle",
        "A Reddit profile matches this handle. Reddit exposes full comment history "
        "publicly — but username collisions here are common.",
        0.5,
        0.45,
        VerificationState.HYPOTHESIS,
        "reddit",
        1,
        "seed",
    ),
    (
        FindingType.CREDENTIAL_REUSE,
        "Password reused across accounts",
        "The credential pattern in the breach matches a password style you use "
        "elsewhere, making credential stuffing viable.",
        0.75,
        0.6,
        VerificationState.HYPOTHESIS,
        None,
        2,
        "breach",
    ),
    (
        FindingType.EMPLOYER_LINK,
        "Employer domain in commit metadata",
        "Commits in a public repository are authored from a corporate email domain, "
        "which confirms where you work.",
        0.6,
        0.85,
        VerificationState.LIKELY,
        "github",
        2,
        "github",
    ),
    (
        FindingType.HANDLE_LINK,
        "Pseudonymous handle links to your real one",
        "Shared bio phrasing and a near-identical handle tie a pseudonymous account "
        "to your primary identity.",
        0.7,
        0.78,
        VerificationState.LIKELY,
        "reddit",
        2,
        "reddit",
    ),
    (
        FindingType.GPS_EXPOSURE,
        "Home GPS in a vacation photo",
        "An uploaded image carries EXIF GPS coordinates from a residential location.",
        0.9,
        0.95,
        VerificationState.CONFIRMED,
        "instagram",
        2,
        "linkedin",
    ),
    (
        FindingType.OBJECT_EXPOSURE,
        "License plate visible in a posted photo",
        "A vehicle plate is legible in the frame of a publicly posted image.",
        0.7,
        0.8,
        VerificationState.LIKELY,
        "instagram",
        2,
        "linkedin",
    ),
    (
        FindingType.DEVICE_FINGERPRINT,
        "Camera make and model in image metadata",
        "Device metadata is consistent across uploads to two different accounts, "
        "linking them.",
        0.4,
        0.7,
        VerificationState.LIKELY,
        "instagram",
        2,
        "linkedin",
    ),
    (
        FindingType.LOCATION_INFERENCE,
        "Neighbourhood inferable from photo content",
        "Visible signage and architecture narrow the location even with EXIF stripped. "
        "Always a hypothesis — visual geolocation is ranked guesses, never a fix.",
        0.6,
        0.4,
        VerificationState.HYPOTHESIS,
        "instagram",
        3,
        "gps",
    ),
    (
        FindingType.FACE_LINK,
        "Same face on your pseudonymous and professional accounts",
        "Avatar comparison across your verified accounts matches the same face.",
        0.75,
        0.83,
        VerificationState.LIKELY,
        "linkedin",
        3,
        "handle",
    ),
    (
        FindingType.RECORD_CLASS,
        "Property deeds are public in your state",
        "Property records tie your full name to a street address and are resold by "
        "brokers. Public by statute — not deletable.",
        0.85,
        0.9,
        VerificationState.CONFIRMED,
        "public_records",
        3,
        "gps",
    ),
]

#: Template index → stable key, so parents can be referenced by name above.
_KEYS = {
    0: "seed",
    1: "breach",
    2: "linkedin",
    3: "github",
    4: "reddit",
    5: "reuse",
    6: "employer",
    7: "handle",
    8: "gps",
    9: "plate",
    10: "device",
    11: "geoclip",
    12: "face",
    13: "records",
}


def generate(
    identity: VerifiedIdentity,
    count: int | None = None,
    seed: int | None = None,
) -> list[Finding]:
    """Produce schema-valid mock findings for a session.

    Deterministic given the same identity, so C and D see a stable graph
    across reloads. ``count`` trims from the end; the templates are ordered so
    a prefix is still a coherent graph rather than orphaned nodes.
    """
    rng = random.Random(seed if seed is not None else hash(identity.session_id) & 0xFFFF)
    templates = _TEMPLATES[:count] if count else _TEMPLATES

    ids: dict[str, str] = {}
    findings: list[Finding] = []

    for index, template in enumerate(templates):
        (
            finding_type,
            label,
            detail,
            severity_base,
            confidence,
            state,
            platform,
            hop,
            parent_key,
        ) = template

        key = _KEYS.get(index, f"n{index}")
        finding_id = f"f_mock_{key}"
        ids[key] = finding_id

        reversible, remediation = classify(finding_type)
        # Small deterministic jitter so the 3D scene doesn't render a row of
        # identical bar heights.
        jitter = rng.uniform(-0.04, 0.04)

        findings.append(
            Finding(
                id=finding_id,
                parent_id=ids.get(parent_key) if parent_key else None,
                hop_depth=hop,
                type=finding_type,
                label=label,
                detail=detail,
                verification_state=state,
                confidence=round(min(1.0, max(0.05, confidence + jitter)), 3),
                severity_base=round(min(1.0, max(0.05, severity_base + jitter)), 3),
                reversible=reversible,
                remediation=remediation,
                platform=platform,
                source="mock:generator",
                method="mock findings generator v1 — NOT REAL DATA",
                evidence=redact_evidence(
                    identity.session_id,
                    finding_id,
                    [
                        {"k": "sample_value", "v": "mock"},
                        {"k": "observed_at", "v": "mock"},
                    ],
                ),
                subject_ref=identity.subject_ref,
                origin=Origin.AGENT,
            )
        )

    return findings


def demo_identity(session_id: str = "sess_demo") -> VerifiedIdentity:
    """A verified identity for the mock path.

    Note what this is *not*: a way to scan an arbitrary target. It fabricates
    a session whose verified set contains these values, which is the same
    thing A's identity gate does after a real code loop. The guardrail still
    holds — anything outside this set is still refused.
    """
    return VerifiedIdentity.build(
        session_id=session_id,
        emails=["demo@ddu-mirror.local"],
        handles=["demo_operator"],
        subject_ref=f"subject:{session_id}",
    )
