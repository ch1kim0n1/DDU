"""Threat-model persona weights.

The findings never change when the persona changes. Only the ranking does.
That distinction is the whole point: home GPS coordinates are a mild
annoyance if your threat model is a recruiter and a catastrophe if it is an
abusive ex, and a tool that scores them identically is lying to one of those
two users.

Engineer A owns the *values* here (the spec hands the persona weight matrix
from A to B). This module owns the *shape* and ships defaults so nothing is
blocked waiting on that handoff. ``load_persona_weights`` accepts A's JSON
verbatim and overlays it.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from .schema import FindingType

log = logging.getLogger("mirror-intel.personas")


@dataclass(frozen=True)
class Persona:
    key: str
    label: str
    description: str
    #: What this adversary is actually trying to accomplish. Used verbatim in
    #: remediation copy so the advice reads as targeted rather than generic.
    goal: str


PERSONAS: dict[str, Persona] = {
    "employer": Persona(
        key="employer",
        label="Employer or recruiter",
        description="Someone screening you before a hiring or promotion decision.",
        goal="form a judgment about your character, politics, and history",
    ),
    "stalker": Persona(
        key="stalker",
        label="Stalker or abusive ex",
        description="Someone who knows you and wants to find or reach you physically.",
        goal="locate you in the physical world and re-establish contact",
    ),
    "scammer": Persona(
        key="scammer",
        label="Scammer or account thief",
        description="Someone monetizing you through account takeover or social engineering.",
        goal="take over an account or convincingly impersonate you",
    ),
    "state": Persona(
        key="state",
        label="State-level actor",
        description="A well-resourced adversary correlating across many sources.",
        goal="build a complete, durable dossier and link your pseudonymous activity",
    ),
}

DEFAULT_PERSONA = "scammer"

#: persona × finding_type → multiplier applied to severity_base.
#:
#: Read a column to see the argument: GPS exposure is 1.9× for a stalker and
#: 0.5× for an employer. Breach records are 1.8× for a scammer (credential
#: stuffing is their whole business) and 0.7× for a stalker who already knows
#: who you are.
PERSONA_WEIGHTS: dict[str, dict[FindingType, float]] = {
    "employer": {
        FindingType.SEED_IDENTITY: 0.2,
        FindingType.ACCOUNT: 1.2,
        FindingType.BREACH: 0.6,
        FindingType.GPS_EXPOSURE: 0.5,
        FindingType.DEVICE_FINGERPRINT: 0.3,
        FindingType.OBJECT_EXPOSURE: 0.6,
        FindingType.LOCATION_INFERENCE: 0.4,
        FindingType.FACE_LINK: 1.7,
        FindingType.HANDLE_LINK: 1.8,
        FindingType.RECORD_CLASS: 0.7,
        FindingType.CREDENTIAL_REUSE: 0.5,
        FindingType.EMPLOYER_LINK: 1.4,
        FindingType.ATTACKER_NEXT_MOVE: 0.6,
    },
    "stalker": {
        FindingType.SEED_IDENTITY: 0.2,
        FindingType.ACCOUNT: 1.0,
        FindingType.BREACH: 0.7,
        FindingType.GPS_EXPOSURE: 1.9,
        FindingType.DEVICE_FINGERPRINT: 0.8,
        FindingType.OBJECT_EXPOSURE: 1.7,
        FindingType.LOCATION_INFERENCE: 1.6,
        FindingType.FACE_LINK: 1.5,
        FindingType.HANDLE_LINK: 1.3,
        FindingType.RECORD_CLASS: 1.8,
        FindingType.CREDENTIAL_REUSE: 0.9,
        FindingType.EMPLOYER_LINK: 1.6,
        FindingType.ATTACKER_NEXT_MOVE: 1.2,
    },
    "scammer": {
        FindingType.SEED_IDENTITY: 0.2,
        FindingType.ACCOUNT: 1.3,
        FindingType.BREACH: 1.8,
        FindingType.GPS_EXPOSURE: 0.6,
        FindingType.DEVICE_FINGERPRINT: 0.7,
        FindingType.OBJECT_EXPOSURE: 0.8,
        FindingType.LOCATION_INFERENCE: 0.5,
        FindingType.FACE_LINK: 0.9,
        FindingType.HANDLE_LINK: 1.2,
        FindingType.RECORD_CLASS: 1.0,
        FindingType.CREDENTIAL_REUSE: 1.9,
        FindingType.EMPLOYER_LINK: 1.1,
        FindingType.ATTACKER_NEXT_MOVE: 1.0,
    },
    "state": {
        FindingType.SEED_IDENTITY: 0.3,
        FindingType.ACCOUNT: 1.1,
        FindingType.BREACH: 1.2,
        FindingType.GPS_EXPOSURE: 1.2,
        FindingType.DEVICE_FINGERPRINT: 1.4,
        FindingType.OBJECT_EXPOSURE: 1.0,
        FindingType.LOCATION_INFERENCE: 1.1,
        FindingType.FACE_LINK: 1.6,
        FindingType.HANDLE_LINK: 1.7,
        FindingType.RECORD_CLASS: 1.2,
        FindingType.CREDENTIAL_REUSE: 1.3,
        FindingType.EMPLOYER_LINK: 1.3,
        FindingType.ATTACKER_NEXT_MOVE: 1.1,
    },
}


def weight_for(persona: str, finding_type: FindingType) -> float:
    """Multiplier for one persona/type pair. Unknown pairs weigh 1.0 rather
    than raising: a new finding type should degrade to persona-neutral, not
    take down the scan."""
    table = PERSONA_WEIGHTS.get(persona)
    if table is None:
        log.warning("unknown persona %r, scoring persona-neutral", persona)
        return 1.0
    if finding_type not in table:
        log.warning("persona %s has no weight for %s, defaulting to 1.0", persona, finding_type)
        return 1.0
    return table[finding_type]


#: Shorthand Engineer A's matrix uses for finding types, mapped to the
#: contract's canonical names. Without this, A's ``"object"`` key is silently
#: dropped and object-exposure findings score persona-neutral — which was
#: masked at integration time only because A's intended value happened to
#: match this module's default. A tuning pass on their side would have
#: silently stopped reaching the scoring engine.
KEY_ALIASES: dict[str, str] = {
    "object": FindingType.OBJECT_EXPOSURE.value,
    "gps": FindingType.GPS_EXPOSURE.value,
    "face": FindingType.FACE_LINK.value,
    "handle": FindingType.HANDLE_LINK.value,
    "employer": FindingType.EMPLOYER_LINK.value,
    "device": FindingType.DEVICE_FINGERPRINT.value,
    "location": FindingType.LOCATION_INFERENCE.value,
    "records": FindingType.RECORD_CLASS.value,
    "seed": FindingType.SEED_IDENTITY.value,
}


def load_persona_weights(path: str | None = None) -> None:
    """Overlay Engineer A's persona matrix onto the defaults.

    Accepts ``{persona: {finding_type: multiplier}}`` — the exact shape named
    in the interface-contracts table. Missing personas or types keep the
    default, so A can hand over a partial matrix early and refine it.
    """
    path = path or os.environ.get("MIRROR_PERSONA_WEIGHTS")
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as fh:
            incoming = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not load persona weights from %s: %s — keeping defaults", path, exc)
        return

    applied = 0
    for persona_key, table in incoming.items():
        target = PERSONA_WEIGHTS.setdefault(persona_key, {})
        for type_key, multiplier in table.items():
            canonical = KEY_ALIASES.get(type_key, type_key)
            try:
                target[FindingType(canonical)] = float(multiplier)
                applied += 1
            except (ValueError, TypeError):
                log.warning("ignoring unknown finding type %r in persona %s", type_key, persona_key)
    log.info("applied %d persona weight overrides from %s", applied, path)


def describe(persona: str) -> Persona:
    return PERSONAS.get(persona, PERSONAS[DEFAULT_PERSONA])
