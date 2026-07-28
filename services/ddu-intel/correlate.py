"""Graph-backed correlation helpers for ddu-intel (no hard-coded cities/people)."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Callable


HypothesisFactory = Callable[..., dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attrs(entity: dict[str, Any]) -> dict[str, Any]:
    return entity.get("attributes") or {}


def _label(entity: dict[str, Any]) -> str:
    attrs = _attrs(entity)
    return str(
        attrs.get("label")
        or attrs.get("username")
        or attrs.get("name")
        or attrs.get("place")
        or entity.get("type")
        or entity.get("id")
        or ""
    )


def _text_blob(entity: dict[str, Any]) -> str:
    attrs = _attrs(entity)
    return " ".join(str(v) for v in [_label(entity), *attrs.values()]).lower()


def _match_score(seed: str, entity: dict[str, Any]) -> float:
    seed_l = seed.lower().strip()
    if not seed_l:
        return 0.0
    blob = _text_blob(entity)
    if seed_l == _label(entity).lower():
        return 0.92
    if seed_l in blob:
        return 0.78
    # token overlap
    seed_tokens = set(re.findall(r"[a-z0-9_]+", seed_l))
    blob_tokens = set(re.findall(r"[a-z0-9_]+", blob))
    if not seed_tokens:
        return 0.0
    overlap = len(seed_tokens & blob_tokens) / len(seed_tokens)
    return round(0.35 + 0.5 * overlap, 3) if overlap else 0.0


def _entity_ids(entities: list[dict[str, Any]]) -> list[str]:
    return [str(e.get("id", "")) for e in entities if e.get("id")]


def subject_entities(entities: list[dict[str, Any]], seed: str) -> list[tuple[float, dict[str, Any]]]:
    scored = [(_match_score(seed, e), e) for e in entities]
    scored = [(s, e) for s, e in scored if s >= 0.35]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def location_hypotheses(
    investigation_id: str,
    seed: str,
    entities: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
    fused: bool = False,
) -> list[dict[str, Any]]:
    locations = [
        e for e in entities
        if e.get("type") in {"ENTITY_TYPE_LOCATION", "ENTITY_TYPE_OBSERVATION"}
        and (
            e.get("type") == "ENTITY_TYPE_LOCATION"
            or "geo" in _attrs(e)
            or "lat" in _attrs(e)
            or "place" in _attrs(e)
            or "location" in _text_blob(e)
        )
    ]
    scored = subject_entities(locations, seed)
    if not scored and locations:
        # Location evidence exists but is not text-linked to subject — still surface it.
        # Prefer fresher observed_at when present.
        def _freshness(entity: dict[str, Any]) -> str:
            return str(_attrs(entity).get("observed_at") or _attrs(entity).get("created_at") or "")

        ordered = sorted(locations, key=_freshness, reverse=True)
        scored = [
            (0.7 - min(0.3, 0.05 * index), entity)
            for index, entity in enumerate(ordered)
        ]
    elif not scored:
        scored = subject_entities(entities, seed)
    out: list[dict[str, Any]] = []
    for score, entity in scored[:max_results]:
        attrs = _attrs(entity)
        place = attrs.get("place") or attrs.get("geo") or _label(entity)
        evidence = list(entity.get("evidence_ids") or [])
        if not evidence:
            digest = hashlib.sha256(f"{investigation_id}:{entity.get('id')}".encode()).hexdigest()
            evidence = [f"sha256:{digest[:32]}"]
        signals = ["graph_entity_match", "attribute_overlap"]
        if attrs.get("geo") or attrs.get("lat"):
            signals.append("geospatial_attribute")
        out.append(hypothesis(
            investigation_id,
            str(place),
            min(0.95, score if not fused else min(0.95, score + 0.08)),
            hypothesis_type="HYPOTHESIS_FUSED_LOCATION" if fused else "HYPOTHESIS_CURRENT_LOCATION",
            evidence_ids=evidence,
            attributes={
                "lat": attrs.get("lat") or attrs.get("latitude") or "",
                "lon": attrs.get("lon") or attrs.get("longitude") or "",
                "uncertainty_km": attrs.get("uncertainty_km") or "25",
                "freshness": attrs.get("observed_at") or attrs.get("created_at") or _now(),
                "source_entity_id": entity.get("id"),
                "signals": signals,
            },
            run_id=run_id,
            job=job,
        ))
    if out:
        return out
    # Sparse graph: emit low-confidence unknown rather than inventing a city.
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return [hypothesis(
        investigation_id,
        "unknown-location",
        0.2,
        hypothesis_type="HYPOTHESIS_FUSED_LOCATION" if fused else "HYPOTHESIS_CURRENT_LOCATION",
        evidence_ids=[f"sha256:{digest[:32]}"],
        attributes={
            "uncertainty_km": "1000",
            "freshness": _now(),
            "signals": ["insufficient_graph_evidence"],
            "note": "No LOCATION/geo-bearing entities matched subject; hypothesis deferred.",
        },
        contradictions=["sparse_graph"],
        run_id=run_id,
        job=job,
    )]


def related_person_hypotheses(
    investigation_id: str,
    seed: str,
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
    hypothesis_type: str,
) -> list[dict[str, Any]]:
    seeds = subject_entities(entities, seed)
    seed_ids = {e.get("id") for _, e in seeds[:5]}
    people = [
        e for e in entities
        if e.get("type") in {
            "ENTITY_TYPE_PERSON", "ENTITY_TYPE_ACCOUNT", "ENTITY_TYPE_USERNAME", "ENTITY_TYPE_ORGANIZATION",
        } and e.get("id") not in seed_ids
    ]
    by_id = {e.get("id"): e for e in entities}
    scored: list[tuple[float, dict[str, Any], str]] = []
    for rel in relationships:
        src, tgt = rel.get("source_entity_id"), rel.get("target_entity_id")
        if src in seed_ids and tgt in by_id:
            other = by_id[tgt]
            conf = float((rel.get("confidence") or {}).get("value") or 0.5)
            scored.append((conf, other, str(rel.get("relationship_type") or "ASSOCIATED_WITH")))
        elif tgt in seed_ids and src in by_id:
            other = by_id[src]
            conf = float((rel.get("confidence") or {}).get("value") or 0.5)
            scored.append((conf, other, str(rel.get("relationship_type") or "ASSOCIATED_WITH")))
    if not scored:
        for person in people:
            score = _match_score(seed, person) * 0.5 + 0.25
            scored.append((score, person, "graph_cooccurrence"))
    scored.sort(key=lambda item: item[0], reverse=True)
    out = []
    for score, entity, rel_type in scored[:max_results]:
        out.append(hypothesis(
            investigation_id,
            f"{rel_type}:{_label(entity)}",
            min(0.95, score),
            hypothesis_type=hypothesis_type,
            evidence_ids=list(entity.get("evidence_ids") or []),
            attributes={
                "relationship_type": rel_type,
                "related_entity_id": entity.get("id"),
                "related_entity_label": _label(entity),
                "signals": ["graph_relationship", "entity_type_filter"],
            },
            run_id=run_id,
            job=job,
        ))
    return out


def identity_hypotheses(
    investigation_id: str,
    seed: str,
    entities: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
) -> list[dict[str, Any]]:
    accounts = [
        e for e in entities
        if e.get("type") in {
            "ENTITY_TYPE_ACCOUNT", "ENTITY_TYPE_USERNAME", "ENTITY_TYPE_CANDIDATE_ACCOUNT", "ENTITY_TYPE_PERSON",
        }
    ]
    scored = subject_entities(accounts or entities, seed)
    out = []
    for score, entity in scored[:max_results]:
        attrs = _attrs(entity)
        platform = attrs.get("platform") or attrs.get("source") or entity.get("type")
        handle = attrs.get("username") or attrs.get("handle") or _label(entity)
        out.append(hypothesis(
            investigation_id,
            f"{handle}@{platform}",
            score,
            hypothesis_type="HYPOTHESIS_SAME_IDENTITY",
            evidence_ids=list(entity.get("evidence_ids") or []),
            attributes={
                "platform": platform,
                "entity_id": entity.get("id"),
                "signals": ["username_similarity", "graph_entity_match"],
                "entity_count_considered": len(entities),
            },
            run_id=run_id,
            job=job,
        ))
    return out


def attribute_pattern_hypotheses(
    investigation_id: str,
    entities: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
) -> list[dict[str, Any]]:
    places: dict[str, int] = {}
    orgs: dict[str, int] = {}
    for entity in entities:
        attrs = _attrs(entity)
        place = attrs.get("place") or attrs.get("geo") or ""
        if place:
            places[str(place)] = places.get(str(place), 0) + 1
        if entity.get("type") == "ENTITY_TYPE_ORGANIZATION":
            orgs[_label(entity)] = orgs.get(_label(entity), 0) + 1
    out = []
    for place, count in sorted(places.items(), key=lambda item: item[1], reverse=True)[:max_results]:
        out.append(hypothesis(
            investigation_id,
            f"Recurring location cluster: {place}",
            min(0.9, 0.4 + 0.1 * count),
            hypothesis_type="HYPOTHESIS_PATTERN_OF_LIFE",
            attributes={
                "pattern": "recurring_location",
                "place": place,
                "observations": count,
                "signals": ["recurring_cluster", "graph_frequency"],
            },
            run_id=run_id,
            job=job,
        ))
    for org, count in sorted(orgs.items(), key=lambda item: item[1], reverse=True)[: max(0, max_results - len(out))]:
        out.append(hypothesis(
            investigation_id,
            f"Org affiliation pattern: {org}",
            min(0.85, 0.4 + 0.1 * count),
            hypothesis_type="HYPOTHESIS_PATTERN_OF_LIFE",
            attributes={
                "pattern": "organization_affinity",
                "organization": org,
                "signals": ["org_entity_frequency"],
            },
            run_id=run_id,
            job=job,
        ))
    return out


def history_from_entities(
    investigation_id: str,
    entities: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
) -> list[dict[str, Any]]:
    timed = []
    for entity in entities:
        attrs = _attrs(entity)
        place = attrs.get("place") or attrs.get("geo")
        ts = attrs.get("observed_at") or attrs.get("timestamp") or entity.get("created_at")
        if place and ts:
            timed.append((str(ts), str(place), entity))
    timed.sort(key=lambda item: item[0])
    out = []
    for ts, place, entity in timed[:max_results]:
        out.append(hypothesis(
            investigation_id,
            f"{ts[:7]} → {place}",
            _match_score(place, entity) or 0.55,
            hypothesis_type="HYPOTHESIS_HISTORICAL_LOCATION",
            evidence_ids=list(entity.get("evidence_ids") or []),
            attributes={
                "period": ts[:7],
                "place": place,
                "source_entity_id": entity.get("id"),
                "signals": ["entity_timestamp", "geo_attribute"],
            },
            run_id=run_id,
            job=job,
        ))
    return out


def alias_hypotheses(
    investigation_id: str,
    seed: str,
    entities: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
) -> list[dict[str, Any]]:
    out = []
    for score, entity in subject_entities(entities, seed)[:max_results]:
        label = _label(entity)
        if label.lower() == seed.lower():
            continue
        out.append(hypothesis(
            investigation_id,
            label,
            score,
            hypothesis_type="HYPOTHESIS_ALIAS",
            evidence_ids=list(entity.get("evidence_ids") or []),
            attributes={
                "alias_type": "graph_label_variant",
                "source_entity_id": entity.get("id"),
                "signals": ["label_variant", "username_similarity"],
            },
            run_id=run_id,
            job=job,
        ))
    return out


def org_hypotheses(
    investigation_id: str,
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
) -> list[dict[str, Any]]:
    orgs = [e for e in entities if e.get("type") == "ENTITY_TYPE_ORGANIZATION"]
    out = []
    for entity in orgs[:max_results]:
        out.append(hypothesis(
            investigation_id,
            _label(entity),
            0.55 + 0.05 * min(5, len(relationships)),
            hypothesis_type="HYPOTHESIS_EMPLOYMENT",
            evidence_ids=list(entity.get("evidence_ids") or []),
            attributes={
                "relationship_type": "affiliated_with",
                "entity_id": entity.get("id"),
                "signals": ["organization_entity", "graph_presence"],
            },
            run_id=run_id,
            job=job,
        ))
    return out


def asset_hypotheses(
    investigation_id: str,
    entities: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
) -> list[dict[str, Any]]:
    assets = [
        e for e in entities
        if e.get("type") in {"ENTITY_TYPE_VEHICLE", "ENTITY_TYPE_OBJECT"}
        or "vehicle" in _text_blob(e)
    ]
    out = []
    for entity in assets[:max_results]:
        out.append(hypothesis(
            investigation_id,
            _label(entity),
            0.5,
            hypothesis_type="HYPOTHESIS_ASSET_ASSOCIATION",
            evidence_ids=list(entity.get("evidence_ids") or []),
            attributes={
                "asset_type": "vehicle" if "vehicle" in _text_blob(entity) else "object",
                "ownership_claim": False,
                "source_entity_id": entity.get("id"),
                "signals": ["object_entity", "recurring_object_in_imagery"],
                "note": "Association is probabilistic; not ownership.",
            },
            run_id=run_id,
            job=job,
        ))
    return out


def life_event_hypotheses(
    investigation_id: str,
    entities: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
) -> list[dict[str, Any]]:
    history = history_from_entities(
        investigation_id, entities, hypothesis=hypothesis, run_id=run_id, job=job, max_results=max_results + 1,
    )
    out = []
    for index in range(1, len(history)):
        prev = history[index - 1]["attributes"]["place"]
        curr = history[index]["attributes"]["place"]
        if prev != curr:
            out.append(hypothesis(
                investigation_id,
                f"Possible relocation {prev} → {curr}",
                0.6,
                hypothesis_type="HYPOTHESIS_LIFE_EVENT",
                attributes={
                    "event_type": "relocation",
                    "approx_date": history[index]["attributes"]["period"],
                    "signals": ["location_shift", "temporal_sequence"],
                },
                run_id=run_id,
                job=job,
            ))
    return out[:max_results]


def record_hypotheses(
    investigation_id: str,
    seed: str,
    entities: list[dict[str, Any]],
    *,
    hypothesis: HypothesisFactory,
    run_id: str,
    job: str,
    max_results: int,
    record_type_prefix: str,
) -> list[dict[str, Any]]:
    """Derive public-record style hypotheses from DOCUMENT/CLAIM entities only."""
    docs = [
        e for e in entities
        if e.get("type") in {"ENTITY_TYPE_DOCUMENT", "ENTITY_TYPE_CLAIM", "ENTITY_TYPE_SOURCE"}
    ]
    scored = subject_entities(docs, seed) if docs else []
    out = []
    for score, entity in scored[:max_results]:
        attrs = _attrs(entity)
        out.append(hypothesis(
            investigation_id,
            f"{record_type_prefix}:{_label(entity)}",
            score,
            hypothesis_type="HYPOTHESIS_PUBLIC_RECORD",
            evidence_ids=list(entity.get("evidence_ids") or []),
            attributes={
                "record_type": attrs.get("record_type") or record_type_prefix,
                "jurisdiction": attrs.get("jurisdiction") or "unknown",
                "source_url": attrs.get("source_url") or attrs.get("url") or "",
                "record_identifier": entity.get("id"),
                "reliability": score,
                "signals": ["document_entity", "subject_overlap"],
            },
            run_id=run_id,
            job=job,
        ))
    return out
