"""Public Records Exposure Advisor.

**No scraping. No lookups. No retrieval.** The user tells us their state and
county; we tell them which classes of record are public there, what each one
exposes, and the documented suppression path. We never fetch a record.

That restraint is the product decision. Building the extraction machinery
would be straightforward and would immediately make this a tool for finding
*anyone's* address — the exact capability the whole design is structured to
not have. Telling you that property deeds expose your address, and how to
enrol in your state's address-confidentiality program, delivers the defensive
value without building the offensive one.

Findings from this module are always ``record_class`` type: they assert that a
*category* of record about you is public, never that a specific record exists.
That distinction is visible in the label, the evidence, and the confidence.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from .guardrails import VerifiedIdentity
from .llm import Tier, get_llm
from .personas import DEFAULT_PERSONA, describe
from .schema import (
    Effort,
    EvidenceItem,
    Finding,
    FindingType,
    Origin,
    Remediation,
    VerificationState,
)

log = logging.getLogger("mirror-intel.records")

DATA_PATH = Path(__file__).resolve().parent / "data" / "public_records.json"


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    with open(DATA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def jurisdictions() -> list[dict[str, str]]:
    """States we have curated data for. Drives A's onboarding dropdown."""
    data = _catalog()["jurisdictions"]
    return [
        {"code": code, "label": entry["label"]}
        for code, entry in data.items()
        if not code.startswith("_")
    ]


def _jurisdiction(state: str) -> tuple[str, dict[str, Any]]:
    data = _catalog()["jurisdictions"]
    code = (state or "").strip().upper()
    if code in data:
        return code, data[code]
    log.info("no curated data for %r; using the general US baseline", state)
    return "_default", data["_default"]


def _effort(value: str) -> Effort:
    return {"low": Effort.LOW, "medium": Effort.MEDIUM, "high": Effort.HIGH}.get(
        value, Effort.MEDIUM
    )


def advise(
    identity: VerifiedIdentity,
    state: str,
    county: str | None = None,
    parent_id: str | None = None,
    hop_depth: int = 1,
) -> tuple[list[Finding], dict[str, Any]]:
    """Which record classes are public where this user lives, and what to do.

    Takes a ``VerifiedIdentity`` for the ``subject_ref`` only — there is no
    lookup to gate, because nothing is looked up. The findings describe the
    jurisdiction, not the person.
    """
    code, jurisdiction = _jurisdiction(state)
    catalog = _catalog()
    classes = catalog["record_classes"]

    # Index suppression paths by the record class they help with.
    paths_by_class: dict[str, list[dict[str, Any]]] = {}
    for path in jurisdiction.get("suppression_paths", []):
        for applies in path.get("applies_to", []):
            paths_by_class.setdefault(applies, []).append(path)

    findings: list[Finding] = []
    for class_key in jurisdiction.get("public_by_default", []):
        spec = classes.get(class_key)
        if not spec:
            continue

        paths = paths_by_class.get(class_key, [])
        # Prefer a path anyone can take over one gated on eligibility — a
        # remediation step most users can't act on isn't remediation.
        paths.sort(key=lambda p: (p.get("eligibility") != "anyone", p.get("effort")))
        primary = paths[0] if paths else None

        finding_id = f"f_rec_{code.lower()}_{class_key}"
        reversible = bool(spec.get("reversible", False))

        if reversible and primary:
            remediation = Remediation(
                action=primary["path"],
                compensating=None,
                effort=_effort(primary.get("effort", "medium")),
            )
        else:
            remediation = Remediation(
                action=(
                    "This record is public by statute. It cannot be deleted."
                    if not primary
                    else f"The record itself stays public. {primary['path']}"
                ),
                compensating=(
                    "Work the data-broker opt-out list — the brokers are what make the "
                    "record findable by name. Re-check every few months; they repopulate."
                ),
                effort=_effort(primary.get("effort", "high")) if primary else Effort.HIGH,
                permanent_note=(
                    f"{spec['label']} are public government records in "
                    f"{jurisdiction['label']}. Suppression limits redistribution; it does "
                    "not remove the record."
                ),
            )

        evidence = [
            {"kind": "record", "k": "record class", "v": spec["label"], "redacted": False},
            {"kind": "text", "k": "discloses", "v": spec["discloses"], "redacted": False},
            {
                "kind": "text",
                "k": "jurisdiction",
                "v": f"{jurisdiction['label']}{f' — {county} County' if county else ''}",
                "redacted": False,
            },
        ]
        if primary and primary.get("citation"):
            evidence.append(
                {"kind": "text", "k": "citation", "v": primary["citation"], "redacted": False}
            )
        if primary and primary.get("eligibility") == "restricted":
            evidence.append(
                {
                    "kind": "text",
                    "k": "eligibility",
                    "v": "This suppression path is limited to specific qualifying groups.",
                    "redacted": False,
                }
            )

        findings.append(
            Finding(
                id=finding_id,
                parent_id=parent_id,
                hop_depth=hop_depth,
                type=FindingType.RECORD_CLASS,
                label=f"{spec['label']} are public in {jurisdiction['label']}",
                detail=spec["why_it_matters"],
                # We are asserting a fact about the jurisdiction, which we are
                # confident about — not that a specific record about this user
                # exists, which we have not checked and will not check.
                verification_state=VerificationState.CONFIRMED,
                confidence=0.9,
                severity_base=float(spec.get("severity_base", 0.5)),
                reversible=reversible,
                remediation=remediation,
                platform="public_records",
                source=f"curated:public_records.json#{code}.{class_key}",
                method="Curated jurisdiction catalog — no lookup performed",
                # Not redacted, and deliberately so: none of this is about the
                # user. "Property deeds are public in Texas" is a fact about
                # Texas, so there is nothing here to hide behind a token.
                evidence=[
                    EvidenceItem(
                        kind=e.get("kind", "kv"), k=e["k"], v=e["v"], redacted=False
                    )
                    for e in evidence
                ],
                subject_ref=identity.subject_ref,
                origin=Origin.SYSTEM,
            )
        )

    meta = {
        "worker": "records_advisor",
        "jurisdiction": jurisdiction["label"],
        "jurisdiction_code": code,
        "county": county,
        "record_classes": len(findings),
        "exact_match": code != "_default",
        "no_lookup_performed": True,
        "disclaimer": catalog["_meta"]["disclaimer"],
        "notes": jurisdiction.get("notes"),
        "biometric_note": jurisdiction.get("biometric_note"),
        "broker_opt_out": catalog["broker_opt_out"],
    }
    return findings, meta


_SYSTEM = """You advise people on suppressing their exposure in public records.

You will be given: a US jurisdiction, a list of record classes that are public
there, and the user's threat model. You will NOT be given the user's name,
address, or any record — none has been looked up, and you must not imply
otherwise.

Write a short prioritized plan: which suppression path to pursue first for
this threat model and why, and what to do about the classes that cannot be
suppressed. Be concrete and honest — if a path is restricted to qualifying
groups, say so rather than implying everyone can use it. Do not invent
statutes, agency names, or program names beyond what you are given.

Return 3-5 short paragraphs of plain text. No preamble."""


def personalize(
    state: str,
    persona: str = DEFAULT_PERSONA,
    county: str | None = None,
) -> dict[str, Any]:
    """Model-written prioritization over the curated facts.

    The model reorders and explains; it never sources the facts. Everything it
    receives came from the curated file, so it has nothing to hallucinate a
    statute from — and nothing identifying to leak, because a jurisdiction is
    not a person.
    """
    code, jurisdiction = _jurisdiction(state)
    catalog = _catalog()
    persona_desc = describe(persona)

    briefing = {
        "jurisdiction": jurisdiction["label"],
        "county": county,
        "public_record_classes": [
            {
                "key": key,
                "label": catalog["record_classes"][key]["label"],
                "discloses": catalog["record_classes"][key]["discloses"],
                "reversible": catalog["record_classes"][key].get("reversible", False),
            }
            for key in jurisdiction.get("public_by_default", [])
            if key in catalog["record_classes"]
        ],
        "suppression_paths": jurisdiction.get("suppression_paths", []),
    }

    completion = get_llm().complete(
        messages=[
            {
                "role": "user",
                "content": (
                    f"Threat model: {persona_desc.label} — {persona_desc.description} "
                    f"Their goal is to {persona_desc.goal}.\n\n"
                    f"Jurisdiction briefing:\n{json.dumps(briefing, indent=2)}"
                ),
            }
        ],
        tier=Tier.ADVISOR,
        system=_SYSTEM,
        max_tokens=1600,
    )

    return {
        "jurisdiction": jurisdiction["label"],
        "jurisdiction_code": code,
        "persona": persona,
        "plan": completion.text,
        "offline": completion.offline,
        "grounded_in": "curated jurisdiction catalog only — no records were retrieved",
    }
