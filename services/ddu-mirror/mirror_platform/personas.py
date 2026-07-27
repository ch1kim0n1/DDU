"""The persona weights owned by Engineer A and consumed by the intelligence service."""

from __future__ import annotations

PERSONA_WEIGHTS: dict[str, dict[str, float]] = {
    "employer": {
        "account": 1.2, "breach": 0.6, "gps_exposure": 0.5,
        "object": 0.6, "face_link": 1.7, "handle_link": 1.8,
        "record_class": 0.7, "employer_link": 1.4,
    },
    "stalker": {
        "account": 1.0, "breach": 0.7, "gps_exposure": 1.9,
        "object": 1.7, "face_link": 1.5, "handle_link": 1.3,
        "record_class": 1.8, "employer_link": 1.6,
    },
    "scammer": {
        "account": 1.3, "breach": 1.8, "gps_exposure": 0.6,
        "object": 0.8, "face_link": 0.9, "handle_link": 1.2,
        "record_class": 1.0, "credential_reuse": 1.9,
    },
    "state": {
        "account": 1.1, "breach": 1.2, "gps_exposure": 1.2,
        "object": 1.0, "face_link": 1.6, "handle_link": 1.7,
        "record_class": 1.2, "device_fingerprint": 1.4,
    },
}

PERSONAS = {
    "employer": "Employer or recruiter",
    "stalker": "Stalker or abusive ex",
    "scammer": "Scammer or account thief",
    "state": "State-level actor",
}
