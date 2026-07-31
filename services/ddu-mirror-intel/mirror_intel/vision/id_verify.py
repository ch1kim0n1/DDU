"""Demo photo-ID verification — student ID / driver's license upload.

Demo path only: no live ID OCR vendor, no face-match-to-document. Upload
produces mock OCR fields (deterministic from content hash), schema-valid
``object_exposure`` findings with redacted evidence, and an ``id_document``
assurance label for the session gate.

Not a KYC product. Disclosures always say the OCR is mocked for the demo.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from ..redaction import mint_reveal_token
from ..reversibility import classify
from ..schema import (
    EvidenceItem,
    Finding,
    FindingType,
    Origin,
    VerificationState,
)
from ..session import SEED_FINDING_ID, Session
from .cache import content_hash

DocumentKind = Literal["student_id", "drivers_license"]

ALLOWED_KINDS = frozenset({"student_id", "drivers_license"})
METHOD = "mock:id-ocr-demo"
DISCLOSURE = (
    "ID OCR is mocked for the Mirror demo (deterministic fields from image "
    "sha256). No live document-OCR vendor and no face-to-ID match."
)

KIND_LABEL = {
    "student_id": "Student ID",
    "drivers_license": "Driver's license",
}


def _fid(prefix: str) -> str:
    return f"f_{prefix}_{secrets.token_hex(3)}"


def _pick(digest: str, options: list[str]) -> str:
    idx = int(digest[:8], 16) % len(options)
    return options[idx]


def mock_ocr_fields(kind: DocumentKind, digest: str) -> dict[str, str]:
    """Stable fake PII keyed by content hash — same bytes → same fields."""
    if kind == "student_id":
        return {
            "full_name": _pick(
                digest,
                ["Jordan Lee", "Alex Rivera", "Sam Okonkwo", "Casey Nguyen"],
            ),
            "student_number": f"STU-{digest[2:8].upper()}",
            "institution": _pick(
                digest[4:],
                [
                    "State University",
                    "Metro Community College",
                    "Northridge Tech",
                ],
            ),
            "expires": f"08/{2027 + (int(digest[8:10], 16) % 3)}",
        }
    return {
        "full_name": _pick(
            digest,
            ["Jordan Lee", "Alex Rivera", "Sam Okonkwo", "Casey Nguyen"],
        ),
        "license_number": f"D{digest[2:9].upper()}",
        "date_of_birth": f"19{80 + (int(digest[8:10], 16) % 20)}-0{(int(digest[10:12], 16) % 9) + 1}-15",
        "state": _pick(digest[6:], ["TX", "WA", "CA", "IL", "NY"]),
        "address": f"{100 + (int(digest[12:14], 16) % 800)} Maple Ave",
    }


@dataclass
class IdVerifyState:
    verified: bool = False
    document_kind: str | None = None
    sha256: str | None = None
    verified_at: float | None = None
    fields_redacted: dict[str, str] = field(default_factory=dict)
    disclosure: str = DISCLOSURE

    def public(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "document_kind": self.document_kind,
            "document_label": KIND_LABEL.get(self.document_kind or "", None),
            "sha256": self.sha256,
            "verified_at": self.verified_at,
            "fields": self.fields_redacted,
            "assurance": "id_document" if self.verified else None,
            "disclosure": self.disclosure,
        }


@dataclass
class IdVerifyStore:
    _by_session: dict[str, IdVerifyState] = field(default_factory=dict)

    def get(self, session_id: str) -> IdVerifyState:
        state = self._by_session.get(session_id)
        if state is None:
            state = IdVerifyState()
            self._by_session[session_id] = state
        return state

    def clear(self, session_id: str) -> None:
        self._by_session.pop(session_id, None)


id_verify_store = IdVerifyStore()


def build_id_findings(
    *,
    session: Session,
    kind: DocumentKind,
    digest: str,
    fields: dict[str, str],
    parent_id: str | None = None,
    hop_depth: int = 1,
) -> tuple[list[Finding], dict[str, str]]:
    """One object_exposure finding; PII rows vaulted behind reveal tokens."""
    parent = parent_id or SEED_FINDING_ID
    subject = session.identity.subject_ref
    finding_id = _fid("id")
    vault: dict[str, str] = {}
    evidence: list[EvidenceItem] = [
        EvidenceItem(
            kind="kv",
            k="document_type",
            v=KIND_LABEL[kind],
            redacted=False,
        ),
        EvidenceItem(
            kind="kv",
            k="ocr_mode",
            v="demo mock (not live OCR)",
            redacted=False,
        ),
    ]

    for key, raw in fields.items():
        token = mint_reveal_token(session.session_id, finding_id, key)
        vault[token] = raw
        evidence.append(
            EvidenceItem(
                kind="kv",
                k=key,
                v="REDACTED",
                reveal_token=token,
                redacted=True,
            )
        )

    reversible, remediation = classify(FindingType.OBJECT_EXPOSURE)
    label = f"{KIND_LABEL[kind]} fields readable from upload"
    detail = (
        f"You uploaded a {KIND_LABEL[kind].lower()} image. In the demo path, "
        "mock OCR extracts identifying fields (name, numbers, address/school). "
        "A real adversary with the same photo could do the same — or better — "
        "with a live document reader. Values stay vaulted until you reveal them."
    )

    finding = Finding(
        id=finding_id,
        parent_id=parent,
        hop_depth=hop_depth,
        type=FindingType.OBJECT_EXPOSURE,
        label=label,
        detail=detail,
        verification_state=VerificationState.LIKELY,
        confidence=0.82,
        severity_base=0.78,
        reversible=reversible,
        remediation=remediation,
        platform="id_upload",
        source=f"id:{kind}",
        method=METHOD,
        evidence=evidence,
        subject_ref=subject,
        origin=Origin.HUMAN,
    )
    return [finding], vault


def verify_document(
    session: Session,
    data: bytes,
    *,
    kind: DocumentKind,
    parent_id: str | None = None,
    hop_depth: int = 1,
) -> dict[str, Any]:
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"document_kind must be one of {sorted(ALLOWED_KINDS)}")
    if not data:
        raise ValueError("empty upload")

    digest = content_hash(data)
    fields = mock_ocr_fields(kind, digest)
    findings, vault = build_id_findings(
        session=session,
        kind=kind,
        digest=digest,
        fields=fields,
        parent_id=parent_id,
        hop_depth=hop_depth,
    )
    added = session.add_findings(findings, raw_values=vault or None)

    redacted_view = {k: "REDACTED" for k in fields}
    state = IdVerifyState(
        verified=True,
        document_kind=kind,
        sha256=digest,
        verified_at=time.time(),
        fields_redacted=redacted_view,
        disclosure=DISCLOSURE,
    )
    id_verify_store._by_session[session.session_id] = state

    return {
        "session_id": session.session_id,
        "sha256": digest,
        "document_kind": kind,
        "document_label": KIND_LABEL[kind],
        "assurance": "id_document",
        "fields": redacted_view,
        "disclosures": [DISCLOSURE],
        "accepted": [f.model_dump(mode="json") for f in added],
        **state.public(),
    }
