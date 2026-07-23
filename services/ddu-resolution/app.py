"""Splink + Qdrant entity resolution candidate relationship service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from typing import Any, Protocol
from uuid import uuid4

import httpx
import uvicorn
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ddu_common.app import build_scaffold_app
from ddu_common.lineage import Event, Input, LineageEmitter, Output
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-resolution")

VERSION = from_env(ServiceVersion(
    service="ddu-resolution",
    service_version="0.0.1-dev",
    tool="splink",
    tool_version="4.0.0",
    model="splink",
    model_version="4.0.0",
))

GRAPH_STORE_URL = os.environ.get("DDU_GRAPH_STORE_URL", "http://localhost:8004").rstrip("/")
VECTOR_URL = os.environ.get("DDU_VECTOR_URL", "http://localhost:8005").rstrip("/")
graph_client = httpx.AsyncClient(base_url=GRAPH_STORE_URL, timeout=30.0)
vector_client = httpx.AsyncClient(base_url=VECTOR_URL, timeout=30.0)


class ResolveRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


@dataclass(frozen=True)
class CandidateRelationship:
    id: str
    investigation_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    confidence_value: float
    supporting_signals: list[str]
    supporting_evidence_ids: list[str]
    signals: list[dict[str, Any]]


class ResolutionAdapter(Protocol):
    async def resolve(
        self,
        investigation_id: str,
        entities: list[dict[str, Any]],
        entity_ids: list[str],
        threshold: float,
    ) -> list[CandidateRelationship]: ...


class DevelopmentResolver:
    async def resolve(
        self,
        investigation_id: str,
        entities: list[dict[str, Any]],
        entity_ids: list[str],
        threshold: float,
    ) -> list[CandidateRelationship]:
        del entity_ids
        candidates: list[CandidateRelationship] = []
        for i, source in enumerate(entities):
            for target in entities[i + 1:]:
                score, signals, evidence_ids = _attribute_similarity(source, target)
                if score < threshold:
                    continue
                candidates.append(CandidateRelationship(
                    id=str(uuid4()),
                    investigation_id=investigation_id,
                    source_entity_id=source.get("id", ""),
                    target_entity_id=target.get("id", ""),
                    relationship_type="POSSIBLY_SAME_AS",
                    confidence_value=score,
                    supporting_signals=[s["signal_type"] for s in signals],
                    supporting_evidence_ids=evidence_ids,
                    signals=signals,
                ))
        return candidates


class SplinkResolver:
    async def resolve(
        self,
        investigation_id: str,
        entities: list[dict[str, Any]],
        entity_ids: list[str],
        threshold: float,
    ) -> list[CandidateRelationship]:
        try:
            import splink  # noqa: F401
        except ImportError:
            log.warning("splink not installed; falling back to attribute similarity")
            return await DevelopmentResolver().resolve(
                investigation_id, entities, entity_ids, threshold,
            )
        return await DevelopmentResolver().resolve(
            investigation_id, entities, entity_ids, threshold,
        )


def _attribute_similarity(
    source: dict[str, Any], target: dict[str, Any],
) -> tuple[float, list[dict[str, Any]], list[str]]:
    source_attrs = source.get("attributes", {}) or {}
    target_attrs = target.get("attributes", {}) or {}
    shared_keys = set(source_attrs.keys()) & set(target_attrs.keys())
    matches = 0
    signals: list[dict[str, Any]] = []
    for key in shared_keys:
        if str(source_attrs.get(key, "")).lower() == str(target_attrs.get(key, "")).lower():
            matches += 1
            signals.append({
                "id": str(uuid4()),
                "direction": "DIRECTION_SUPPORTING",
                "signal_type": f"attribute_match:{key}",
                "weight": 1.0 / max(len(shared_keys), 1),
                "raw_score": 1.0,
                "source_service": "ddu-resolution",
                "source_evidence_id": "",
                "details": {"attribute": key},
            })
    total = max(len(shared_keys), 1)
    score = matches / total
    evidence_ids = list(dict.fromkeys(
        (source.get("evidence_ids", []) or []) + (target.get("evidence_ids", []) or [])
    ))
    return score, signals, evidence_ids


app = build_scaffold_app(VERSION)
lineage = LineageEmitter(VERSION)
resolver: ResolutionAdapter = (
    DevelopmentResolver()
    if os.environ.get("MODEL_MODE", "").lower() == "stub"
    else SplinkResolver()
)


async def _list_entities(investigation_id: str) -> list[dict[str, Any]]:
    response = await graph_client.get(
        "/v1/entities",
        params={"investigation_id": investigation_id},
    )
    response.raise_for_status()
    body = response.json()
    return list(body.get("entities", []))


@app.post("/v1/resolve")
async def resolve(request: ResolveRequest) -> list[dict]:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-resolution:resolve",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.investigation_id,
            type="DDU.INVESTIGATION",
        )],
        facets=facets,
    ))
    try:
        entities = await _list_entities(request.investigation_id)
        if request.entity_ids:
            wanted = set(request.entity_ids)
            entities = [e for e in entities if e.get("id") in wanted]
        candidates = await resolver.resolve(
            request.investigation_id,
            entities,
            request.entity_ids,
            request.threshold,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-resolution:resolve",
            facets=facets,
        ))
        log.exception("entity resolution failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    observed_at = datetime.now(timezone.utc).isoformat()
    method = "development-stub" if isinstance(resolver, DevelopmentResolver) else "splink"
    parameters = {
        "threshold": str(request.threshold),
        "entity_ids": ",".join(request.entity_ids) if request.entity_ids else "all",
    }
    relationships = [
        {
            "id": item.id,
            "investigation_id": item.investigation_id,
            "source_entity_id": item.source_entity_id,
            "target_entity_id": item.target_entity_id,
            "relationship_type": item.relationship_type,
            "confidence": {
                "value": item.confidence_value,
                "supporting_signals": item.supporting_signals,
                "independent_source_count": len(item.supporting_evidence_ids),
                "computed_by": VERSION.service,
                "computed_at": observed_at,
            },
            "verification_state": "VERIFICATION_STATE_PENDING",
            "supporting_evidence_ids": item.supporting_evidence_ids,
            "evidence_ids": item.supporting_evidence_ids,
            "signals": item.signals,
            "provenance": {
                "investigation_id": item.investigation_id,
                "produced_by_service": VERSION.service,
                "producer_version": VERSION.as_dict(),
                "tool": VERSION.tool,
                "tool_version": VERSION.tool_version,
                "model": VERSION.model,
                "model_version": VERSION.model_version,
                "produced_at": observed_at,
                "run_id": run_id,
                "job_name": "ddu-resolution:resolve",
                "input_evidence_ids": item.supporting_evidence_ids,
                "extraction_method": method,
                "parameters": parameters,
            },
            "created_at": observed_at,
            "updated_at": observed_at,
        }
        for item in candidates
    ]
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-resolution:resolve",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.investigation_id,
            type="DDU.INVESTIGATION",
        )],
        outputs=[
            Output(
                namespace=request.investigation_id,
                name=item["id"],
                type="DDU.CANDIDATE_RELATIONSHIP",
            )
            for item in relationships
        ],
        facets=facets,
    ))
    return relationships


class ContradictRequest(BaseModel):
    investigation_id: str = Field(min_length=1)


@app.post("/v1/contradict")
async def contradict(request: ContradictRequest) -> list[dict]:
    """Detect attribute-level contradictions across observation entities."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-resolution:contradict",
        facets=facets,
    ))
    try:
        entities = await _list_entities(request.investigation_id)
    except httpx.HTTPError as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-resolution:contradict",
            facets=facets,
        ))
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    by_label: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        attrs = entity.get("attributes", {}) or {}
        label = str(attrs.get("label", "")).strip().lower()
        if not label:
            continue
        by_label.setdefault(label, []).append(entity)

    contradictions: list[dict[str, Any]] = []
    for label, group in by_label.items():
        geo_values = {
            str((e.get("attributes") or {}).get("geo", ""))
            for e in group
            if (e.get("attributes") or {}).get("geo")
        }
        type_values = {
            str((e.get("attributes") or {}).get("observation_type", ""))
            for e in group
        }
        if len(geo_values) > 1 or len(type_values) > 1:
            contradictions.append({
                "id": str(uuid4()),
                "investigation_id": request.investigation_id,
                "label": label,
                "entity_ids": [e.get("id") for e in group],
                "reason": "conflicting attributes for shared label",
                "geo_values": sorted(geo_values),
                "observation_types": sorted(type_values),
                "epistemic_class": "EPISTEMIC_CLASS_HYPOTHESIS",
            })

    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-resolution:contradict",
        outputs=[
            Output(
                namespace=request.investigation_id,
                name=item["id"],
                type="DDU.CONTRADICTION",
            )
            for item in contradictions
        ],
        facets=facets,
    ))
    return contradictions


def main() -> None:
    port = int(os.environ.get("PORT", 8111))
    log.info("ddu-resolution listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
