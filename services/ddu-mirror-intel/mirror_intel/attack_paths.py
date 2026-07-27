"""Attack path chaining — turning a list into a story.

A severity-sorted list of findings is a chore. The same findings in the order
an attacker would actually walk them —

    email → breach dump → reused password → GitHub account →
    commit metadata leaks employer domain → employer confirmed

— is a narrative, and a narrative is what makes someone change a setting. The
spec calls this the highest-value single addition and that matches experience:
it is the difference between "here are 14 problems" and "here is how someone
gets from your email address to your front door."

Two sources of edges:

1. **Parent links.** The graph already records what expansion produced what.
   A root-to-leaf walk is a real traversal an attacker performed.
2. **Type rules.** Some pivots are real but not parent/child, because they
   were discovered by different workers. A breach record and a reused handle
   on another platform are siblings in our graph and consecutive steps in an
   attacker's. ``PIVOTS`` encodes those.

Feasibility is the *weakest* link, not the average: a chain is exactly as
walkable as its least certain hop. Averaging would let a chain with one
0.2-confidence guess and four confirmations look like a sure thing.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Iterable, Sequence

from .schema import STATE_WEIGHT, AttackPath, Finding, FindingType

#: Pivots an attacker makes between findings that aren't parent and child.
#: ``(from_type, to_type) -> how they get from one to the other``.
PIVOTS: dict[tuple[FindingType, FindingType], str] = {
    (FindingType.SEED_IDENTITY, FindingType.BREACH): "looks the address up in breach corpora",
    (FindingType.SEED_IDENTITY, FindingType.ACCOUNT): "searches the handle across platforms",
    (FindingType.BREACH, FindingType.CREDENTIAL_REUSE): "tries the leaked password elsewhere",
    (FindingType.BREACH, FindingType.ACCOUNT): "uses the leaked address to find more accounts",
    (FindingType.ACCOUNT, FindingType.HANDLE_LINK): "matches the handle to a pseudonymous account",
    (FindingType.ACCOUNT, FindingType.FACE_LINK): "matches the avatar across accounts",
    (FindingType.ACCOUNT, FindingType.EMPLOYER_LINK): "reads the profile for an employer",
    (FindingType.ACCOUNT, FindingType.GPS_EXPOSURE): "pulls metadata from the posted photos",
    (FindingType.ACCOUNT, FindingType.OBJECT_EXPOSURE): "studies what's visible in the photos",
    (FindingType.HANDLE_LINK, FindingType.EMPLOYER_LINK): "reads commit metadata for a work domain",
    (FindingType.HANDLE_LINK, FindingType.GPS_EXPOSURE): "checks the linked account's photos",
    (FindingType.FACE_LINK, FindingType.EMPLOYER_LINK): "finds the professional profile behind the face",
    (FindingType.GPS_EXPOSURE, FindingType.RECORD_CLASS): "matches the coordinates to property records",
    (FindingType.LOCATION_INFERENCE, FindingType.RECORD_CLASS): "narrows the area, then searches public records",
    (FindingType.OBJECT_EXPOSURE, FindingType.RECORD_CLASS): "runs the plate or house number against public records",
    (FindingType.EMPLOYER_LINK, FindingType.RECORD_CLASS): "uses the employer to confirm identity in filings",
    (FindingType.CREDENTIAL_REUSE, FindingType.ACCOUNT): "takes over the account",
}

#: What an attacker walks away with, keyed on where the chain terminates.
TERMINAL_IMPACT: dict[FindingType, str] = {
    FindingType.RECORD_CLASS: "your home address, confirmed against a public record",
    FindingType.GPS_EXPOSURE: "the coordinates of a place you regularly are",
    FindingType.LOCATION_INFERENCE: "the neighbourhood you live or work in",
    FindingType.EMPLOYER_LINK: "where you work, and a plausible pretext for contacting you there",
    FindingType.CREDENTIAL_REUSE: "a working password for one of your accounts",
    FindingType.ACCOUNT: "control of, or access to, one of your accounts",
    FindingType.FACE_LINK: "proof that your pseudonymous account is you",
    FindingType.HANDLE_LINK: "proof that your pseudonymous account is you",
    FindingType.BREACH: "credentials to try against your other accounts",
    FindingType.OBJECT_EXPOSURE: "an identifying detail — a plate, a badge, a house number",
    FindingType.DEVICE_FINGERPRINT: "a device fingerprint that links your uploads together",
}

#: Chains shorter than this aren't stories, they're findings.
MIN_PATH_LENGTH = 3
MAX_PATHS = 8


def _path_id(finding_ids: Sequence[str]) -> str:
    digest = hashlib.sha256("|".join(finding_ids).encode()).hexdigest()[:6]
    return f"ap_{digest}"


def _step_phrase(a: Finding, b: Finding) -> str:
    pivot = PIVOTS.get((a.type, b.type))
    if pivot:
        return pivot
    if b.parent_id == a.id:
        return f"follows that to {b.label.lower()}"
    return f"pivots to {b.label.lower()}"


def _narrate(path: Sequence[Finding]) -> str:
    """Plain-language description of the walk.

    Deterministic on purpose. The voice agent reads these out, and a generated
    narrative is one hallucination away from inventing a finding — which the
    spec correctly identifies as the thing that would torch the whole
    provenance pitch on stage.
    """
    head = path[0]
    parts = [f"Starting from {head.label.lower()}, an attacker"]
    for previous, current in zip(path, path[1:]):
        parts.append(f"{_step_phrase(previous, current)} ({current.label.lower()})")
    sentence = ", then ".join([parts[0] + " " + parts[1]] + parts[2:]) if len(parts) > 2 else " ".join(parts)
    impact = TERMINAL_IMPACT.get(path[-1].type)
    if impact:
        sentence += f". They end up with {impact}."
    else:
        sentence += "."
    return sentence


def _feasibility(path: Sequence[Finding]) -> float:
    """A chain is as strong as its weakest hop."""
    return min(f.confidence * STATE_WEIGHT[f.verification_state] for f in path)


def build_attack_paths(findings: Iterable[Finding]) -> list[AttackPath]:
    """Chain findings into attacker-ordered narratives.

    Rejected and contradicted findings are excluded — a path that runs through
    a node the human said isn't theirs is not a path. That exclusion is what
    makes the correction loop visibly break downstream paths in the 3D scene.
    """
    live = [f for f in findings if f.counts_toward_score]
    by_id = {f.id: f for f in live}
    if not live:
        return []

    # Adjacency: parent links first, then type-rule pivots between findings
    # that aren't already connected.
    children: dict[str, list[Finding]] = defaultdict(list)
    for finding in live:
        if finding.parent_id and finding.parent_id in by_id:
            children[finding.parent_id].append(finding)

    for source in live:
        for target in live:
            if source.id == target.id or target.parent_id == source.id:
                continue
            if (source.type, target.type) not in PIVOTS:
                continue
            # Never pivot *backwards* toward the seed — that would invert the
            # direction of the attack. Same-depth pivots ARE allowed, and that
            # matters more than it looks: real discovery workers all emit at
            # depth 1 (they each expand the seed independently), so requiring
            # a strictly increasing depth meant real scans produced zero paths
            # while the mock hierarchy produced eight. PIVOTS is a DAG over
            # finding types and `walk` carries a seen-set, so equal depth
            # cannot introduce a cycle.
            if target.hop_depth < source.hop_depth:
                continue
            children[source.id].append(target)

    roots = [f for f in live if not f.parent_id or f.parent_id not in by_id]
    if not roots:
        roots = sorted(live, key=lambda f: f.hop_depth)[:1]

    paths: list[list[Finding]] = []

    def walk(node: Finding, trail: list[Finding], seen: set[str]) -> None:
        trail = trail + [node]
        seen = seen | {node.id}
        # Deduplicate: the same finding can be reachable via a parent link and
        # a pivot, and we don't want the same chain twice.
        nexts = {c.id: c for c in children.get(node.id, []) if c.id not in seen}
        if not nexts:
            if len(trail) >= MIN_PATH_LENGTH:
                paths.append(trail)
            return
        for child in nexts.values():
            walk(child, trail, seen)
        # A chain that could continue is still a chain worth telling if it is
        # already long enough and ends somewhere meaningful.
        if len(trail) >= MIN_PATH_LENGTH and node.type in TERMINAL_IMPACT:
            paths.append(trail)

    for root in roots:
        walk(root, [], set())

    # Prefer paths that are both long and walkable; a five-hop chain of
    # hypotheses is less useful than a three-hop chain of confirmations.
    scored = sorted(
        paths,
        key=lambda p: (_feasibility(p) * (1 + 0.15 * len(p))),
        reverse=True,
    )

    out: list[AttackPath] = []
    used: set[tuple[str, ...]] = set()
    # Terminal diversity: four paths that all end at "property deeds" tell one
    # story four times. Cap repeats per endpoint so the rendered set reads as
    # distinct outcomes — the point of showing several paths at all.
    terminals: dict[str, int] = {}
    max_per_terminal = 2

    for path in scored:
        key = tuple(f.id for f in path)
        if key in used:
            continue
        # Drop paths that are a strict prefix of one we already kept.
        if any(key == existing[: len(key)] for existing in used):
            continue
        terminal = path[-1].id
        if terminals.get(terminal, 0) >= max_per_terminal:
            continue
        terminals[terminal] = terminals.get(terminal, 0) + 1
        used.add(key)
        out.append(
            AttackPath(
                id=_path_id(key),
                finding_ids=list(key),
                narrative=_narrate(path),
                feasibility=round(_feasibility(path), 3),
                terminal_impact=TERMINAL_IMPACT.get(path[-1].type, ""),
            )
        )
        if len(out) >= MAX_PATHS:
            break
    return out


def annotate_findings(findings: Sequence[Finding], paths: Sequence[AttackPath]) -> list[Finding]:
    """Write path membership back onto findings so the 3D scene can light them.

    Returns new objects; inputs are not mutated.
    """
    membership: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        for finding_id in path.finding_ids:
            membership[finding_id].append(path.id)
    return [f.model_copy(update={"attack_path_ids": membership.get(f.id, [])}) for f in findings]
