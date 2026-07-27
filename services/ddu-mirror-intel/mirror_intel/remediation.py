"""Severity-ranked remediation checklist.

Ranking is ``persona-adjusted severity ÷ effort``, so a critical exposure with
a thirty-second fix outranks a critical exposure that needs a lawyer. That's
the ordering someone can actually work through on a Tuesday evening.

Two-layer copy:

* The **action** and **compensating control** come from the reversibility
  table — curated, deterministic, and identical every run. These are the
  load-bearing sentences, and they must not vary.
* The **framing** is model-written from redacted structs, personalized to the
  threat persona. This is where "because your threat model is an ex-partner,
  the coordinates matter more than the account list" comes from.

The model never sees a label, a coordinate, a handle, or a platform-specific
detail — only ``{"type": "gps_exposure", "severity": "critical", "reversible":
false}``. It can write good guidance from that shape; it cannot learn who the
user is. If the model is unavailable, the curated layer stands alone and the
checklist is still correct — just less tailored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from .llm import Tier, get_llm
from .personas import DEFAULT_PERSONA, describe
from .redaction import redact_findings
from .schema import EFFORT_COST, Finding
from .scoring import contribution

log = logging.getLogger("mirror-intel.remediation")


@dataclass
class RemediationItem:
    rank: int
    finding_id: str
    label: str
    severity: str
    reversible: bool
    action: str
    compensating: str | None
    effort: str
    permanent_note: str | None
    priority: float
    #: Model-written, persona-specific framing. Empty when offline.
    why_it_matters: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "finding_id": self.finding_id,
            "label": self.label,
            "severity": self.severity,
            "reversible": self.reversible,
            "action": self.action,
            "compensating": self.compensating,
            "effort": self.effort,
            "permanent_note": self.permanent_note,
            "priority": round(self.priority, 4),
            "why_it_matters": self.why_it_matters,
        }


@dataclass
class Checklist:
    persona: str
    items: list[RemediationItem] = field(default_factory=list)
    irreversible_count: int = 0
    offline: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "persona": self.persona,
            "items": [i.as_dict() for i in self.items],
            "irreversible_count": self.irreversible_count,
            "offline": self.offline,
            "note": (
                f"{self.irreversible_count} of these cannot be undone. Those entries carry a "
                "compensating control instead of a fix."
            )
            if self.irreversible_count
            else "",
        }


def rank(findings: Sequence[Finding], persona: str = DEFAULT_PERSONA) -> list[RemediationItem]:
    """Order findings by what to do first. Pure function, no model needed."""
    scored: list[tuple[float, Finding]] = []
    for finding in findings:
        if not finding.counts_toward_score:
            continue
        weight = contribution(finding, persona)
        cost = EFFORT_COST[finding.remediation.effort]
        # Irreversible findings get a small boost: you can't fix them, but
        # understanding them changes what else you should do, so they belong
        # near the top rather than buried under quick wins.
        boost = 1.15 if not finding.reversible else 1.0
        scored.append((weight / cost * boost, finding))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        RemediationItem(
            rank=i + 1,
            finding_id=f.id,
            label=f.label,
            severity=f.severity.value,
            reversible=f.reversible,
            action=f.remediation.action,
            compensating=f.remediation.compensating,
            effort=f.remediation.effort.value,
            permanent_note=f.remediation.permanent_note,
            priority=priority,
        )
        for i, (priority, f) in enumerate(scored)
    ]


_SYSTEM = """You write privacy remediation guidance.

You will receive a JSON array of de-identified exposure descriptors and the
user's threat model. You do NOT know who the user is, and you must not ask or
speculate. Each descriptor has a stable `ref` — key your output to it.

For each descriptor write one or two sentences explaining why this exposure
matters TO THIS SPECIFIC THREAT MODEL. Be concrete about what the adversary
gains, in plain language. Do not restate the severity label, do not invent
details that aren't in the descriptor, and never suggest an action for an
exposure marked reversible:false other than the compensating approach.

Return an object mapping each `ref` to its sentence. Nothing else."""


def _copy_schema(refs: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {ref: {"type": "string"} for ref in refs},
        "required": list(refs),
        "additionalProperties": False,
    }


def write_copy(
    items: Sequence[RemediationItem],
    findings: Sequence[Finding],
    persona: str = DEFAULT_PERSONA,
    limit: int = 10,
) -> tuple[list[RemediationItem], bool]:
    """Attach persona-specific framing to the top items.

    Only the top ``limit`` get model copy — the tail of a long checklist is
    read by nobody and generating it costs latency the demo can't spare.
    Returns the items and whether the offline provider answered.
    """
    if not items:
        return list(items), False

    by_id = {f.id: f for f in findings}
    head = list(items[:limit])
    payload = redact_findings([by_id[i.finding_id] for i in head if i.finding_id in by_id])
    if not payload:
        return list(items), False

    ref_to_item = {p["ref"]: item for p, item in zip(payload, head)}
    persona_desc = describe(persona)

    completion = get_llm().complete(
        messages=[
            {
                "role": "user",
                "content": (
                    f"Threat model: {persona_desc.label} — {persona_desc.description} "
                    f"Their goal is to {persona_desc.goal}.\n\n"
                    f"Exposures:\n{payload}"
                ),
            }
        ],
        tier=Tier.ADVISOR,
        system=_SYSTEM,
        schema=_copy_schema(list(ref_to_item)),
        max_tokens=2048,
    )

    mapping = completion.as_json(default={}) or {}
    for ref, sentence in mapping.items():
        item = ref_to_item.get(ref)
        if item and isinstance(sentence, str):
            item.why_it_matters = sentence.strip()

    return list(items), completion.offline


def build_checklist(
    findings: Sequence[Finding],
    persona: str = DEFAULT_PERSONA,
    with_copy: bool = True,
) -> Checklist:
    items = rank(findings, persona)
    offline = False
    if with_copy:
        items, offline = write_copy(items, findings, persona)
    irreversible = sum(1 for i in items if not i.reversible)
    return Checklist(
        persona=persona, items=items, irreversible_count=irreversible, offline=offline
    )
