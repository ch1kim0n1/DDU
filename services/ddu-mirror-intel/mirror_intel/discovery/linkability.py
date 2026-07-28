"""Account linkability heuristics — is your pseudonymous account provably you?

This is a genuine exposure finding rather than an account listing. A user who
keeps a throwaway handle separate from their real name has made a decision;
discovering that the two are trivially linkable tells them the decision didn't
hold.

Deliberately **not** Splink. Probabilistic record linkage is the right tool
for reconciling millions of records against each other, and the wrong tool for
scoring four signals across a handful of accounts inside a 24-hour build. A
hand-rolled scorer here is more explainable, has no training step, and — the
part that matters — can show its working in the evidence drawer. "These two
accounts share an avatar hash and a bio substring" is auditable in a way a
match weight is not.

Four signals, combined with a noisy-OR so that several weak agreements
compound but no single weak signal creates a link:

* **Avatar reuse** — same image bytes on both accounts. Nearly conclusive.
* **Bio substring** — a distinctive phrase copy-pasted between profiles.
* **Cross-links** — one profile links to the other. The user did this.
* **Handle similarity** — edit distance between the two handles.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any, Sequence

from ..guardrails import VerifiedIdentity, assert_self
from ..redaction import redact_evidence
from ..reversibility import classify
from ..schema import Finding, FindingType, Origin, VerificationState

log = logging.getLogger("mirror-intel.linkability")

#: Per-signal strength. Avatar reuse dominates because identical image bytes
#: across two accounts is a deliberate act, not a coincidence.
SIGNAL_STRENGTH: dict[str, float] = {
    "avatar_hash": 0.88,
    "cross_link": 0.8,
    "bio_phrase": 0.62,
    "handle_similarity": 0.45,
}

#: Below this, a shared phrase is just English. "Software engineer" links
#: nobody to anybody.
MIN_PHRASE_WORDS = 4

_COMMON_PHRASES = {
    "software engineer",
    "views my own",
    "opinions are my own",
    "he him",
    "she her",
    "they them",
    "coffee lover",
    "dm for business",
}


@dataclass
class AccountProfile:
    """A profile as observed. All fields optional — sites vary in what they expose."""

    platform: str
    handle: str
    bio: str = ""
    avatar_bytes: bytes | None = None
    avatar_hash: str | None = None
    links: list[str] = None  # type: ignore[assignment]
    url: str = ""

    def __post_init__(self) -> None:
        if self.links is None:
            self.links = []
        if self.avatar_hash is None and self.avatar_bytes:
            self.avatar_hash = hashlib.sha256(self.avatar_bytes).hexdigest()


@dataclass
class Signal:
    name: str
    strength: float
    explanation: str


def _normalize_phrases(bio: str) -> set[str]:
    """Distinctive n-grams from a bio, with boilerplate removed."""
    words = re.findall(r"[a-z0-9']+", bio.lower())
    grams: set[str] = set()
    for size in (MIN_PHRASE_WORDS, MIN_PHRASE_WORDS + 2):
        for i in range(len(words) - size + 1):
            phrase = " ".join(words[i : i + size])
            if phrase not in _COMMON_PHRASES:
                grams.add(phrase)
    return grams


def compare(a: AccountProfile, b: AccountProfile) -> list[Signal]:
    """Signals suggesting two accounts are the same person."""
    signals: list[Signal] = []

    if a.avatar_hash and b.avatar_hash and a.avatar_hash == b.avatar_hash:
        signals.append(
            Signal(
                "avatar_hash",
                SIGNAL_STRENGTH["avatar_hash"],
                f"Both accounts use byte-identical avatar images "
                f"(sha256 {a.avatar_hash[:12]}…).",
            )
        )

    a_targets = {link.lower() for link in a.links}
    b_targets = {link.lower() for link in b.links}
    if (b.url and b.url.lower() in a_targets) or (a.url and a.url.lower() in b_targets):
        signals.append(
            Signal(
                "cross_link",
                SIGNAL_STRENGTH["cross_link"],
                "One profile links directly to the other — the accounts are "
                "connected by their own contents.",
            )
        )
    elif b.handle.lower() in " ".join(a_targets) or a.handle.lower() in " ".join(b_targets):
        signals.append(
            Signal(
                "cross_link",
                SIGNAL_STRENGTH["cross_link"] * 0.8,
                "One profile's links mention the other account's handle.",
            )
        )

    shared = _normalize_phrases(a.bio) & _normalize_phrases(b.bio)
    if shared:
        longest = max(shared, key=len)
        signals.append(
            Signal(
                "bio_phrase",
                SIGNAL_STRENGTH["bio_phrase"],
                f'Both bios contain the phrase "{longest}", which is distinctive '
                "enough that copy-paste is the likely explanation.",
            )
        )

    ratio = difflib.SequenceMatcher(
        None, a.handle.lower().lstrip("@"), b.handle.lower().lstrip("@")
    ).ratio()
    if ratio >= 0.72:
        signals.append(
            Signal(
                "handle_similarity",
                SIGNAL_STRENGTH["handle_similarity"] * ratio,
                f"The handles are {int(ratio * 100)}% similar — a pseudonym derived "
                "from a real handle is easy to reverse.",
            )
        )

    return signals


def _noisy_or(signals: Sequence[Signal]) -> float:
    """Combine independent signals without letting any one of them saturate."""
    residual = 1.0
    for signal in signals:
        residual *= 1 - signal.strength
    return 1 - residual


def linkability_findings(
    identity: VerifiedIdentity,
    profiles: Sequence[AccountProfile],
    parent_id: str | None = None,
    hop_depth: int = 2,
    threshold: float = 0.5,
) -> tuple[list[Finding], dict[str, Any]]:
    """Score every pair of the operator's own accounts for linkability.

    Both sides of every pair must be in the verified set. This is not a
    formality: comparing a verified account against an unverified one would be
    building an identity link about a third party, which is precisely the
    capability this product is built not to have.
    """
    for profile in profiles:
        assert_self(identity, profile.handle)

    findings: list[Finding] = []
    pairs_examined = 0

    for i, a in enumerate(profiles):
        for b in profiles[i + 1 :]:
            if a.platform == b.platform:
                continue
            pairs_examined += 1
            signals = compare(a, b)
            if not signals:
                continue
            score = _noisy_or(signals)
            if score < threshold:
                continue

            finding_id = f"f_link_{a.platform}_{b.platform}_{abs(hash((a.handle, b.handle))) % 1000:03d}"
            reversible, remediation = classify(FindingType.HANDLE_LINK)

            findings.append(
                Finding(
                    id=finding_id,
                    parent_id=parent_id,
                    hop_depth=hop_depth,
                    type=FindingType.HANDLE_LINK,
                    label=f"{a.platform} and {b.platform} accounts are linkable",
                    detail=(
                        f"{len(signals)} independent signal(s) tie these two accounts to "
                        "the same person. If you keep one of them pseudonymous, that "
                        "separation does not currently hold."
                    ),
                    verification_state=VerificationState.LIKELY
                    if score >= 0.8
                    else VerificationState.HYPOTHESIS,
                    confidence=round(score, 3),
                    severity_base=0.65,
                    reversible=reversible,
                    remediation=remediation,
                    platform=b.platform,
                    source=f"linkability:{a.platform}+{b.platform}",
                    method="DDU Mirror linkability scorer (noisy-OR over 4 signals)",
                    evidence=redact_evidence(
                        identity.session_id,
                        finding_id,
                        [{"k": s.name, "v": s.explanation} for s in signals]
                        + [{"k": "combined_score", "v": f"{score:.3f}"}],
                    ),
                    subject_ref=identity.subject_ref,
                    origin=Origin.AGENT,
                )
            )

    return findings, {
        "worker": "linkability",
        "pairs_examined": pairs_examined,
        "links_found": len(findings),
        "threshold": threshold,
    }
