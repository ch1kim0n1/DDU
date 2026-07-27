"""Exposure score engine — a pure function over the live findings set.

The spec is emphatic about this and it is right: the score must be recomputed
from scratch on every mutation, never incremented or cached. Three features
depend on it simultaneously — persona re-ranking, the rejection cascade, and
the remediation simulation — and any one of them hardcoding a delta breaks the
other two.

So: ``compute_score(findings, persona)`` takes the whole set and returns a
number. No state, no accumulation, no mutation of its inputs.

How the number is built:

* Each finding contributes ``severity_base × persona_weight × confidence ×
  state_weight``. A hypothesis with 0.4 confidence contributes about a tenth
  of what a confirmed finding at the same base severity does.
* Rejected and contradicted findings contribute zero — but stay in the graph,
  because the audit trail matters more than a tidy list.
* Contributions are combined with diminishing returns rather than summed. Ten
  medium findings should not outscore one catastrophic one, and a long tail of
  low-severity noise should not saturate the meter.
* Irreversible findings get a floor: you cannot remediate your way to zero
  when part of your exposure is permanent. Watching the score stop above zero
  during the remediation demo is the honest version of that story.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Literal, Sequence

from .personas import DEFAULT_PERSONA, weight_for
from .schema import (
    STATE_WEIGHT,
    Finding,
    ScoreBreakdown,
    Severity,
    severity_from_score,
)

#: Controls how fast additional findings stop mattering. Tuned so that a
#: single critical finding lands around 55-65 and a realistic full scan lands
#: in the 70s — leaving headroom so remediation produces visible movement.
_SATURATION = 3.2


def contribution(finding: Finding, persona: str) -> float:
    """Persona-adjusted, confidence-weighted weight of one finding."""
    if not finding.counts_toward_score:
        return 0.0
    weight = weight_for(persona, finding.type)
    state = STATE_WEIGHT[finding.verification_state]
    return finding.severity_base * weight * finding.confidence * state


def apply_persona(findings: Sequence[Finding], persona: str) -> list[Finding]:
    """Recompute ``severity`` / ``severity_score`` for the persona.

    Returns new Finding objects; the inputs are not mutated. This is what
    makes "switch persona, findings stay the same, ranking changes" true
    rather than aspirational — the underlying `severity_base` never moves.
    """
    out: list[Finding] = []
    for finding in findings:
        adjusted = min(1.0, finding.severity_base * weight_for(persona, finding.type))
        out.append(
            finding.model_copy(
                update={
                    "severity_score": adjusted,
                    "severity": severity_from_score(adjusted),
                }
            )
        )
    return out


def _band(score: int) -> Literal["minimal", "moderate", "elevated", "severe", "critical"]:
    if score >= 85:
        return "critical"
    if score >= 65:
        return "severe"
    if score >= 40:
        return "elevated"
    if score >= 18:
        return "moderate"
    return "minimal"


def compute_score(
    findings: Iterable[Finding], persona: str = DEFAULT_PERSONA
) -> ScoreBreakdown:
    """The headline number. Pure function — same inputs, same output, always."""
    findings = list(findings)
    scoring_set = [f for f in findings if f.counts_toward_score]
    suppressed = len(findings) - len(scoring_set)

    contributions = [(f, contribution(f, persona)) for f in scoring_set]
    total = sum(c for _, c in contributions)

    # Diminishing returns: an exponential approach to 100 rather than a sum
    # that either saturates instantly or never gets there.
    raw = 100 * (1 - math.exp(-total / _SATURATION))

    irreversible_weight = sum(c for f, c in contributions if not f.reversible)
    irreversible_share = (irreversible_weight / total) if total > 0 else 0.0

    # A permanent exposure sets a floor. Mark every reversible thing fixed and
    # the score still won't reach zero — which is the truth.
    floor = 100 * (1 - math.exp(-irreversible_weight / _SATURATION)) * 0.6
    score = int(round(max(raw, floor)))
    score = max(0, min(100, score))

    top = sorted(contributions, key=lambda pair: pair[1], reverse=True)[:3]
    by_severity = Counter(f.severity.value for f in scoring_set)

    return ScoreBreakdown(
        score=score,
        band=_band(score),
        persona=persona,
        contributing_findings=len(scoring_set),
        suppressed_findings=suppressed,
        irreversible_share=round(irreversible_share, 3),
        top_drivers=[f.label for f, _ in top],
        by_severity={s.value: by_severity.get(s.value, 0) for s in Severity},
    )


def simulate_remediation(
    findings: Sequence[Finding],
    fixed_ids: Iterable[str],
    persona: str = DEFAULT_PERSONA,
) -> tuple[ScoreBreakdown, list[str]]:
    """Score the graph as if ``fixed_ids`` had been remediated.

    Returns the projected score and the ids that **refused** to be marked
    fixed because the underlying exposure is irreversible. Engineer D's 3D
    scene reads that refusal list to make those nodes visibly decline to go
    dark — the emotional high point of the demo, and an honest one.
    """
    fixed = set(fixed_ids)
    refused: list[str] = []
    projected: list[Finding] = []

    for finding in findings:
        if finding.id in fixed:
            if not finding.reversible:
                refused.append(finding.id)
                projected.append(finding)  # still counts; it cannot be fixed
                continue
            # A remediated finding leaves the scoring set the same way a
            # rejected one does, so the same pure function handles both.
            projected.append(
                finding.model_copy(update={"verification_state": finding.verification_state, "confidence": 0.0})
            )
        else:
            projected.append(finding)

    return compute_score(projected, persona), refused
