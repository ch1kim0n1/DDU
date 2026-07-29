"""Closed face corpus — verified-account avatars + user uploads only.

Design rule 3: no open-web face search, ever. Enrollment of anything that
is not session-owned is a CorpusViolation.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


class CorpusViolation(Exception):
    """Raised when a caller tries to expand the corpus beyond Rule 3."""


ALLOWED_SOURCES = frozenset({"verified_avatar", "user_upload", "liveness_frame"})


@dataclass
class CorpusEntry:
    entry_id: str
    source: str
    account_label: str
    platform: str | None
    # Compact perceptual fingerprint — not a biometric template for long-term
    # storage. Destroyed with the session.
    fingerprint: str
    enrolled_at: float = field(default_factory=time.time)
    content_sha256: str = ""

    def to_public(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "source": self.source,
            "account_label": self.account_label,
            "platform": self.platform,
            "enrolled_at": self.enrolled_at,
            "content_sha256": self.content_sha256,
        }


@dataclass
class ClosedCorpus:
    """Per-session allowlisted face gallery."""

    entries: dict[str, CorpusEntry] = field(default_factory=dict)

    def enroll(
        self,
        *,
        entry_id: str,
        source: str,
        account_label: str,
        image_bytes: bytes,
        platform: str | None = None,
        verified_accounts: set[str] | None = None,
    ) -> CorpusEntry:
        if source not in ALLOWED_SOURCES:
            raise CorpusViolation(
                f"refusing corpus source {source!r} — only verified avatars "
                "and user uploads are allowed (design rule 3)"
            )
        if source == "verified_avatar":
            allowed = verified_accounts or set()
            if account_label not in allowed and not account_label.startswith("verified:"):
                raise CorpusViolation(
                    f"avatar for {account_label!r} is not in this session's "
                    "verified account set"
                )

        fingerprint = _fingerprint(image_bytes)
        entry = CorpusEntry(
            entry_id=entry_id,
            source=source,
            account_label=account_label,
            platform=platform,
            fingerprint=fingerprint,
            content_sha256=hashlib.sha256(image_bytes).hexdigest(),
        )
        self.entries[entry_id] = entry
        return entry

    def match(self, image_bytes: bytes, threshold: float = 0.72) -> list[dict[str, Any]]:
        """Compare probe against closed corpus only."""
        probe = _fingerprint(image_bytes)
        hits: list[dict[str, Any]] = []
        for entry in self.entries.values():
            score = _similarity(probe, entry.fingerprint)
            if score >= threshold:
                hits.append(
                    {
                        "entry_id": entry.entry_id,
                        "account_label": entry.account_label,
                        "platform": entry.platform,
                        "source": entry.source,
                        "similarity": round(score, 4),
                    }
                )
        hits.sort(key=lambda h: h["similarity"], reverse=True)
        return hits

    def clear(self) -> int:
        n = len(self.entries)
        self.entries.clear()
        return n

    def to_public(self) -> list[dict[str, Any]]:
        return [e.to_public() for e in self.entries.values()]


def _fingerprint(data: bytes) -> str:
    """Session-scoped compact fingerprint from image bytes.

    Not a production face embedding — adequate for demo closed-corpus
    linkability and for tests without CompreFace. When CompreFace is
    configured, ``face.live_embed`` can replace this.
    """
    # Average block hash over fixed-size downsample when Pillow is present.
    try:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("L").resize((16, 16))
        pixels = list(image.getdata())
        mean = sum(pixels) / len(pixels)
        bits = "".join("1" if p >= mean else "0" for p in pixels)
        return bits
    except Exception:  # noqa: BLE001
        return hashlib.sha256(data).hexdigest()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Hamming for equal-length bitstrings; else token overlap on hex.
    if len(a) == len(b) and set(a) <= {"0", "1"} and set(b) <= {"0", "1"}:
        same = sum(1 for x, y in zip(a, b) if x == y)
        return same / len(a)
    # Prefix match for sha fallback — exact content match only.
    return 1.0 if a == b else 0.0


# Process-wide per-session corpora; wiped with the session.
_corpora: dict[str, ClosedCorpus] = {}


def corpus_for(session_id: str) -> ClosedCorpus:
    corpus = _corpora.get(session_id)
    if corpus is None:
        corpus = ClosedCorpus()
        _corpora[session_id] = corpus
    return corpus


def drop_corpus(session_id: str) -> int:
    corpus = _corpora.pop(session_id, None)
    return corpus.clear() if corpus else 0
