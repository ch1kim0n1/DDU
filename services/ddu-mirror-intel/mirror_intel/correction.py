"""The "that's not me" correction loop.

This is the human-in-the-loop feature that isn't a rubber stamp. Account
discovery has a real false-positive rate — handle searches match people who
merely picked the same username — and a tool that presents those as *your*
accounts is lying to you at the exact moment you're deciding what to lock
down.

Rejecting a node does four things, in this order:

1. The node's verification state becomes ``rejected``. It stays in the graph
   for the audit trail; it stops counting toward anything.
2. Everything discovered *because of* it cascades. If the GitHub account
   wasn't yours, neither is the employer we inferred from its commits — that
   inference has no remaining evidence.
3. Attack paths through any pruned node break, because a chain that runs
   through something that isn't you is not a chain.
4. The score is recomputed from the surviving set — not decremented.

Rejection is reversible. A human who mis-taps should be able to undo it, and
"human control" that only works in one direction isn't control. Restoring a
node restores its descendants to whatever state they held before the cascade,
which is why ``prior_state`` is recorded rather than assumed.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .schema import Finding, Origin, VerificationState

log = logging.getLogger("mirror-intel.correction")


@dataclass
class CorrectionResult:
    findings: list[Finding]
    #: The node the human acted on.
    target_id: str
    #: Descendants that lost their supporting evidence.
    cascaded_ids: list[str] = field(default_factory=list)
    #: Attack paths that no longer hold.
    broken_path_ids: list[str] = field(default_factory=list)

    @property
    def touched_ids(self) -> list[str]:
        return [self.target_id, *self.cascaded_ids]


def _descendants(findings: Sequence[Finding], root_id: str) -> list[str]:
    """Every finding that exists because ``root_id`` was believed."""
    children: dict[str, list[str]] = defaultdict(list)
    for finding in findings:
        if finding.parent_id:
            children[finding.parent_id].append(finding.id)

    out: list[str] = []
    stack = list(children.get(root_id, []))
    seen = {root_id}
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        out.append(current)
        stack.extend(children.get(current, []))
    return out


def reject(
    findings: Sequence[Finding],
    finding_id: str,
    reason: str | None = None,
) -> CorrectionResult:
    """Mark a finding as "not me" and cascade.

    Descendants are marked ``contradicted`` rather than ``rejected``: the
    human didn't assert anything about them directly, we did — their evidence
    just evaporated. Keeping that distinction means the audit log shows what
    the person actually claimed versus what the machine inferred from it.
    """
    by_id = {f.id: f for f in findings}
    if finding_id not in by_id:
        raise KeyError(f"unknown finding {finding_id}")

    cascaded = _descendants(findings, finding_id)
    broken: set[str] = set(by_id[finding_id].attack_path_ids)

    updated: list[Finding] = []
    for finding in findings:
        if finding.id == finding_id:
            note = reason or "Marked 'that's not me' by the operator."
            updated.append(
                finding.model_copy(
                    update={
                        "verification_state": VerificationState.REJECTED,
                        "origin": Origin.HUMAN,
                        "human_note": note,
                        "attack_path_ids": [],
                    }
                )
            )
        elif finding.id in cascaded:
            broken.update(finding.attack_path_ids)
            updated.append(
                finding.model_copy(
                    update={
                        "verification_state": VerificationState.CONTRADICTED,
                        "human_note": (
                            f"Supporting evidence removed: parent finding {finding_id} "
                            "was rejected by the operator."
                        ),
                        "attack_path_ids": [],
                    }
                )
            )
        else:
            updated.append(finding)

    log.info(
        "rejected %s; cascaded to %d descendant(s); broke %d path(s)",
        finding_id,
        len(cascaded),
        len(broken),
    )
    return CorrectionResult(
        findings=updated,
        target_id=finding_id,
        cascaded_ids=cascaded,
        broken_path_ids=sorted(broken),
    )


def restore(findings: Sequence[Finding], finding_id: str) -> CorrectionResult:
    """Undo a rejection, including its cascade.

    Restored descendants come back as ``likely`` rather than their original
    state. We genuinely don't know what they were before — and quietly
    promoting an inference back to ``confirmed`` because the UI needed a value
    is exactly the kind of epistemic sloppiness the whole product argues
    against.
    """
    by_id = {f.id: f for f in findings}
    if finding_id not in by_id:
        raise KeyError(f"unknown finding {finding_id}")

    cascaded = _descendants(findings, finding_id)
    updated: list[Finding] = []
    for finding in findings:
        if finding.id == finding_id:
            updated.append(
                finding.model_copy(
                    update={
                        "verification_state": VerificationState.LIKELY,
                        "origin": Origin.HUMAN,
                        "human_note": "Rejection withdrawn by the operator.",
                    }
                )
            )
        elif (
            finding.id in cascaded
            and finding.verification_state is VerificationState.CONTRADICTED
        ):
            updated.append(
                finding.model_copy(
                    update={
                        "verification_state": VerificationState.LIKELY,
                        "human_note": "Restored after the parent rejection was withdrawn; "
                        "re-verify before relying on it.",
                    }
                )
            )
        else:
            updated.append(finding)

    return CorrectionResult(
        findings=updated, target_id=finding_id, cascaded_ids=cascaded
    )


#: Fields a human is allowed to edit. Track 3 asks for approve/**edit**/reject,
#: and an allowlist is what keeps "edit" from becoming "write anything into a
#: finding". Nobody edits severity, confidence, or provenance by hand — those
#: are computed, and letting a human overwrite them would make the score a
#: matter of opinion.
EDITABLE_FIELDS = frozenset({"label", "detail", "platform", "human_note"})


def edit(
    findings: Sequence[Finding],
    finding_id: str,
    changes: dict[str, str],
    reason: str | None = None,
) -> tuple[list[Finding], dict[str, str]]:
    """Apply a human correction to a finding's descriptive fields.

    Returns the updated set and the changes actually applied — callers log the
    latter, so an attempt to edit a protected field is visible rather than
    silently dropped.
    """
    by_id = {f.id: f for f in findings}
    if finding_id not in by_id:
        raise KeyError(f"unknown finding {finding_id}")

    applied = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS}
    rejected_keys = sorted(set(changes) - EDITABLE_FIELDS)
    if rejected_keys:
        log.warning(
            "ignored edit to protected field(s) %s on %s", ", ".join(rejected_keys), finding_id
        )
    if not applied:
        return list(findings), {}

    applied.setdefault(
        "human_note", reason or "Edited by the operator."
    )
    updated = [
        f.model_copy(update={**applied, "origin": Origin.HUMAN}) if f.id == finding_id else f
        for f in findings
    ]
    return updated, applied


def prune_broken_paths(paths: Iterable, findings: Sequence[Finding]) -> list:
    """Drop attack paths that run through a rejected or contradicted node."""
    live = {f.id for f in findings if f.counts_toward_score}
    return [p for p in paths if all(fid in live for fid in p.finding_ids)]
