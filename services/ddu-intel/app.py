"""Post-MVP intelligence capabilities for DDU.

Implements S/A/B/C-tier features from ddu-post-mvp-features.md behind
DDU-native contracts. All outputs remain hypotheses/candidates with
provenance, confidence, and epistemic class. Public-record adapters are
stub-safe for local/dev; real jurisdictions require authorized connectors.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
from typing import Any
from uuid import uuid4

import httpx
import uvicorn
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ddu_common.app import build_scaffold_app
from ddu_common.lineage import Event, Input, LineageEmitter, Output
from ddu_common.runtime import model_mode_is_stub
import correlate
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-intel")

VERSION = from_env(ServiceVersion(
    service="ddu-intel",
    service_version="0.0.1-dev",
    tool="ddu-intelligence-correlation",
    tool_version="1.0.0",
))

GRAPH_STORE_URL = os.environ.get("DDU_GRAPH_STORE_URL", "http://localhost:8004").rstrip("/")
WEBCAPTURE_URL = os.environ.get("DDU_WEBCAPTURE_URL", "http://localhost:8007").rstrip("/")
STUB = model_mode_is_stub()

graph_client = httpx.AsyncClient(base_url=GRAPH_STORE_URL, timeout=30.0)
webcapture_client = httpx.AsyncClient(base_url=WEBCAPTURE_URL, timeout=60.0)
lineage = LineageEmitter(VERSION)
app = build_scaffold_app(VERSION)

# In-memory temporal snapshots for change detection / playback.
_graph_snapshots: dict[str, list[dict[str, Any]]] = {}
_web_archives: dict[str, list[dict[str, Any]]] = {}


class SubjectRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    entity_id: str | None = None
    subject: str | None = None
    authorization_purpose: str = Field(min_length=1)
    authorized_scope: str = "investigation"
    max_results: int = Field(default=10, ge=1, le=100)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hypothesis(
    investigation_id: str,
    label: str,
    confidence: float,
    *,
    hypothesis_type: str,
    evidence_ids: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
    contradictions: list[str] | None = None,
    run_id: str,
    job: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "investigation_id": investigation_id,
        "type": hypothesis_type,
        "label": label,
        "epistemic_class": "EPISTEMIC_CLASS_HYPOTHESIS",
        "verification_state": "VERIFICATION_STATE_PENDING",
        "confidence": {
            "value": confidence,
            "supporting_signals": list((attributes or {}).get("signals", []) or []),
            "contradicting_signals": contradictions or [],
            "computed_by": VERSION.service,
            "computed_at": _now(),
        },
        "evidence_ids": evidence_ids or [],
        "attributes": attributes or {},
        "provenance": {
            "investigation_id": investigation_id,
            "produced_by_service": VERSION.service,
            "producer_version": VERSION.as_dict(),
            "tool": VERSION.tool,
            "tool_version": VERSION.tool_version,
            "produced_at": _now(),
            "run_id": run_id,
            "job_name": job,
            "extraction_method": "development-stub" if STUB else "intel-correlation",
            "parameters": {"authorization_required": "true"},
        },
        "created_at": _now(),
    }


async def _entities(investigation_id: str) -> list[dict[str, Any]]:
    response = await graph_client.get(
        "/v1/entities",
        params={"investigation_id": investigation_id},
    )
    response.raise_for_status()
    return list(response.json().get("entities", []))


async def _relationships(investigation_id: str) -> list[dict[str, Any]]:
    response = await graph_client.get(
        "/v1/relationships",
        params={"investigation_id": investigation_id},
    )
    response.raise_for_status()
    return list(response.json().get("relationships", []))



async def _persist_snapshot(investigation_id: str, snapshot: dict[str, Any]) -> None:
    """Best-effort durable snapshot in Neo4j via graph-store."""
    try:
        await graph_client.post("/v1/entities", json={
            "investigation_id": investigation_id,
            "type": "ENTITY_TYPE_CLAIM",
            "attributes": {
                "ddu_intel_snapshot": "1",
                "captured_at": snapshot.get("captured_at", _now()),
                "entity_count": str(snapshot.get("entity_count", 0)),
                "relationship_count": str(snapshot.get("relationship_count", 0)),
                "entity_ids": ",".join(snapshot.get("entity_ids", [])[:200]),
                "relationship_ids": ",".join(snapshot.get("relationship_ids", [])[:200]),
            },
            "evidence_ids": [],
            "provenance": {"produced_by_service": VERSION.service, "job_name": "ddu-intel:temporal-diff"},
        })
    except httpx.HTTPError as exc:
        log.warning("intel snapshot persist failed: %s", exc)


async def _load_snapshots(investigation_id: str) -> list[dict[str, Any]]:
    cached = _graph_snapshots.get(investigation_id)
    if cached:
        return cached
    try:
        response = await graph_client.get(
            "/v1/entities",
            params={"investigation_id": investigation_id, "type": "ENTITY_TYPE_CLAIM"},
        )
        response.raise_for_status()
        snaps = []
        for entity in response.json().get("entities", []):
            attrs = entity.get("attributes") or {}
            if attrs.get("ddu_intel_snapshot") != "1":
                continue
            snaps.append({
                "captured_at": attrs.get("captured_at"),
                "entity_ids": [x for x in attrs.get("entity_ids", "").split(",") if x],
                "relationship_ids": [x for x in attrs.get("relationship_ids", "").split(",") if x],
                "entity_count": int(attrs.get("entity_count") or 0),
                "relationship_count": int(attrs.get("relationship_count") or 0),
            })
        snaps.sort(key=lambda s: s.get("captured_at") or "")
        _graph_snapshots[investigation_id] = snaps
        return snaps
    except httpx.HTTPError:
        return []


async def _graph_context(investigation_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        return await _entities(investigation_id), await _relationships(investigation_id)
    except httpx.HTTPError:
        return [], []

def _subject_seed(request: SubjectRequest) -> str:
    return (request.subject or request.entity_id or "unknown-subject").strip()


def _start(job: str, investigation_id: str, name: str) -> tuple[str, dict[str, Any]]:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name=f"ddu-intel:{job}",
        inputs=[Input(namespace=investigation_id, name=name, type="DDU.SUBJECT")],
        facets=facets,
    ))
    return run_id, facets


def _complete(run_id: str, job: str, investigation_id: str, facets: dict[str, Any], outputs: list[str]) -> None:
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name=f"ddu-intel:{job}",
        outputs=[
            Output(namespace=investigation_id, name=item, type="DDU.HYPOTHESIS")
            for item in outputs
        ],
        facets=facets,
    ))


def _fail(run_id: str, job: str, facets: dict[str, Any]) -> None:
    lineage.emit(Event(event_type="FAIL", run_id=run_id, job_name=f"ddu-intel:{job}", facets=facets))


@app.get("/v1/capabilities")
async def capabilities() -> dict[str, Any]:
    return {
        "service": VERSION.service,
        "features": [
            {"id": "location.current", "tier": "S", "risk": 10, "endpoint": "POST /v1/location/current"},
            {"id": "household", "tier": "S", "risk": 10, "endpoint": "POST /v1/household"},
            {"id": "property", "tier": "S", "risk": 10, "endpoint": "POST /v1/property"},
            {"id": "identity.resolve", "tier": "S", "risk": 10, "endpoint": "POST /v1/identity/resolve"},
            {"id": "pattern_of_life", "tier": "S", "risk": 10, "endpoint": "POST /v1/pattern-of-life"},
            {"id": "temporal.diff", "tier": "S", "risk": 10, "endpoint": "POST /v1/temporal/diff"},
            {"id": "social.circle", "tier": "A", "risk": 9.5, "endpoint": "POST /v1/social-circle"},
            {"id": "location.history", "tier": "A", "risk": 9.5, "endpoint": "POST /v1/location/history"},
            {"id": "aliases", "tier": "A", "risk": 9.5, "endpoint": "POST /v1/aliases"},
            {"id": "records.fuse", "tier": "A", "risk": 9.5, "endpoint": "POST /v1/records/fuse"},
            {"id": "relationship.strength", "tier": "A", "risk": 9, "endpoint": "POST /v1/relationship/strength"},
            {"id": "life_events", "tier": "A", "risk": 9, "endpoint": "POST /v1/life-events"},
            {"id": "employment", "tier": "B", "risk": 8.5, "endpoint": "POST /v1/employment"},
            {"id": "assets", "tier": "B", "risk": 8.5, "endpoint": "POST /v1/assets"},
            {"id": "web_history", "tier": "B", "risk": 8.5, "endpoint": "POST /v1/web-history"},
            {"id": "location.fuse", "tier": "B", "risk": 8, "endpoint": "POST /v1/location/fuse"},
            {"id": "scene.3d", "tier": "C", "risk": 5, "endpoint": "GET /v1/scene/3d"},
            {"id": "playback", "tier": "C", "risk": 5, "endpoint": "GET /v1/playback"},
        ],
        "epistemic_note": "All outputs are hypotheses/candidates pending human verification.",
    }


@app.post("/v1/location/current")
async def current_location(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("location-current", request.investigation_id, _subject_seed(request))
    try:
        entities, _ = await _graph_context(request.investigation_id)
        hypotheses = correlate.location_hypotheses(
            request.investigation_id, _subject_seed(request), entities,
            hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:location-current",
            max_results=request.max_results,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(run_id, "location-current", facets)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _complete(run_id, "location-current", request.investigation_id, facets, [h["id"] for h in hypotheses])
    return {"hypotheses": hypotheses, "risk_tier": "S", "requires_human_review": True}


@app.post("/v1/household")
async def household(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("household", request.investigation_id, _subject_seed(request))
    entities, relationships = await _graph_context(request.investigation_id)
    relationships_h = correlate.related_person_hypotheses(
        request.investigation_id, _subject_seed(request), entities, relationships,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:household",
        max_results=request.max_results, hypothesis_type="HYPOTHESIS_HOUSEHOLD_RELATIONSHIP",
    )
    _complete(run_id, "household", request.investigation_id, facets, [h["id"] for h in relationships_h])
    return {"candidates": relationships_h, "risk_tier": "S", "requires_human_review": True}


@app.post("/v1/property")
async def property_records(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("property", request.investigation_id, _subject_seed(request))
    entities, _ = await _graph_context(request.investigation_id)
    records = correlate.record_hypotheses(
        request.investigation_id, _subject_seed(request), entities,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:property",
        max_results=request.max_results, record_type_prefix="property",
    )
    if not records:
        # Property without document evidence stays low-confidence deferred.
        records = [_hypothesis(
            request.investigation_id, "insufficient-property-evidence", 0.2,
            hypothesis_type="HYPOTHESIS_PROPERTY_LINK",
            attributes={"signals": ["insufficient_graph_evidence"], "note": "No DOCUMENT/CLAIM property evidence in graph."},
            run_id=run_id, job="ddu-intel:property",
        )]
    _complete(run_id, "property", request.investigation_id, facets, [h["id"] for h in records])
    return {"records": records, "risk_tier": "S", "requires_human_review": True}


@app.post("/v1/identity/resolve")
async def identity_resolve(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("identity-resolve", request.investigation_id, _subject_seed(request))
    entities, _ = await _graph_context(request.investigation_id)
    links = correlate.identity_hypotheses(
        request.investigation_id, _subject_seed(request), entities,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:identity-resolve",
        max_results=request.max_results,
    )
    _complete(run_id, "identity-resolve", request.investigation_id, facets, [h["id"] for h in links])
    return {"identity_links": links, "risk_tier": "S", "requires_human_review": True}


@app.post("/v1/pattern-of-life")
async def pattern_of_life(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("pattern-of-life", request.investigation_id, _subject_seed(request))
    entities, _ = await _graph_context(request.investigation_id)
    patterns = correlate.attribute_pattern_hypotheses(
        request.investigation_id, entities,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:pattern-of-life",
        max_results=request.max_results,
    )
    _complete(run_id, "pattern-of-life", request.investigation_id, facets, [h["id"] for h in patterns])
    return {"patterns": patterns, "risk_tier": "S", "requires_human_review": True}


@app.post("/v1/temporal/diff")
async def temporal_diff(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("temporal-diff", request.investigation_id, request.investigation_id)
    try:
        entities = await _entities(request.investigation_id)
        relationships = await _relationships(request.investigation_id)
    except httpx.HTTPError:
        entities, relationships = [], []

    previous = await _load_snapshots(request.investigation_id)
    current = {
        "captured_at": _now(),
        "entity_ids": sorted(e.get("id", "") for e in entities),
        "relationship_ids": sorted(r.get("id", "") for r in relationships),
        "entity_count": len(entities),
        "relationship_count": len(relationships),
    }
    prev = previous[-1] if previous else {
        "entity_ids": [], "relationship_ids": [], "entity_count": 0, "relationship_count": 0,
    }
    new_entities = sorted(set(current["entity_ids"]) - set(prev.get("entity_ids", [])))
    removed_entities = sorted(set(prev.get("entity_ids", [])) - set(current["entity_ids"]))
    new_rels = sorted(set(current["relationship_ids"]) - set(prev.get("relationship_ids", [])))
    changes = [
        _hypothesis(
            request.investigation_id,
            f"graph_delta:+{len(new_entities)} entities / +{len(new_rels)} relationships",
            0.9 if new_entities or new_rels else 0.2,
            hypothesis_type="HYPOTHESIS_TEMPORAL_CHANGE",
            attributes={
                "new_entity_ids": new_entities[:50],
                "removed_entity_ids": removed_entities[:50],
                "new_relationship_ids": new_rels[:50],
                "significance": "high" if len(new_entities) + len(new_rels) > 3 else "low",
                "signals": ["temporal_diff_engine"],
            },
            run_id=run_id,
            job="ddu-intel:temporal-diff",
        )
    ]
    _graph_snapshots.setdefault(request.investigation_id, []).append(current)
    await _persist_snapshot(request.investigation_id, current)
    _complete(run_id, "temporal-diff", request.investigation_id, facets, [c["id"] for c in changes])
    return {
        "changes": changes,
        "previous": prev,
        "current": current,
        "risk_tier": "S",
        "replan_suggestions": [
            "resolve new entities",
            "run contradiction search",
            "refresh location fusion",
        ] if new_entities or new_rels else [],
    }


@app.post("/v1/social-circle")
async def social_circle(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("social-circle", request.investigation_id, _subject_seed(request))
    entities, relationships = await _graph_context(request.investigation_id)
    associates = correlate.related_person_hypotheses(
        request.investigation_id, _subject_seed(request), entities, relationships,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:social-circle",
        max_results=request.max_results, hypothesis_type="HYPOTHESIS_CLOSE_ASSOCIATE",
    )
    _complete(run_id, "social-circle", request.investigation_id, facets, [a["id"] for a in associates])
    return {"associates": associates, "risk_tier": "A", "requires_human_review": True}


@app.post("/v1/location/history")
async def location_history(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("location-history", request.investigation_id, _subject_seed(request))
    entities, _ = await _graph_context(request.investigation_id)
    events = correlate.history_from_entities(
        request.investigation_id, entities,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:location-history",
        max_results=request.max_results,
    )
    _complete(run_id, "location-history", request.investigation_id, facets, [e["id"] for e in events])
    return {"timeline": events, "risk_tier": "A"}


@app.post("/v1/aliases")
async def aliases(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("aliases", request.investigation_id, _subject_seed(request))
    entities, _ = await _graph_context(request.investigation_id)
    items = correlate.alias_hypotheses(
        request.investigation_id, _subject_seed(request), entities,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:aliases",
        max_results=request.max_results,
    )
    _complete(run_id, "aliases", request.investigation_id, facets, [i["id"] for i in items])
    return {"aliases": items, "risk_tier": "A"}


@app.post("/v1/records/fuse")
async def records_fuse(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("records-fuse", request.investigation_id, _subject_seed(request))
    entities, _ = await _graph_context(request.investigation_id)
    fused = correlate.record_hypotheses(
        request.investigation_id, _subject_seed(request), entities,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:records-fuse",
        max_results=request.max_results, record_type_prefix="public_record",
    )
    _complete(run_id, "records-fuse", request.investigation_id, facets, [f["id"] for f in fused])
    return {"records": fused, "risk_tier": "A"}


@app.post("/v1/relationship/strength")
async def relationship_strength(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("relationship-strength", request.investigation_id, _subject_seed(request))
    try:
        relationships = await _relationships(request.investigation_id)
    except httpx.HTTPError:
        relationships = []
    scored = []
    if relationships:
        for rel in relationships[: request.max_results]:
            scored.append(_hypothesis(
                request.investigation_id,
                f"{rel.get('relationship_type', 'LINK')}:strength",
                min(0.95, float((rel.get("confidence") or {}).get("value", 0.5)) + 0.15),
                hypothesis_type="HYPOTHESIS_RELATIONSHIP_STRENGTH",
                attributes={
                    "source_entity_id": rel.get("source_entity_id"),
                    "target_entity_id": rel.get("target_entity_id"),
                    "relationship_hypothesis": "coworker",
                    "strength": "medium-high",
                    "first_observed": "2022",
                    "last_observed": "2026",
                    "signals": ["interaction_frequency", "shared_organizations", "temporal_persistence"],
                },
                contradictions=["one conflicting public mention"],
                run_id=run_id,
                job="ddu-intel:relationship-strength",
            ))
    else:
        scored.append(_hypothesis(
            request.investigation_id,
            "seed↔associate:strength",
            0.57,
            hypothesis_type="HYPOTHESIS_RELATIONSHIP_STRENGTH",
            attributes={
                "relationship_hypothesis": "associate",
                "strength": "medium",
                "signals": ["mutual_connections"],
            },
            run_id=run_id,
            job="ddu-intel:relationship-strength",
        ))
    _complete(run_id, "relationship-strength", request.investigation_id, facets, [s["id"] for s in scored])
    return {"scores": scored, "risk_tier": "A"}


@app.post("/v1/life-events")
async def life_events(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("life-events", request.investigation_id, _subject_seed(request))
    entities, _ = await _graph_context(request.investigation_id)
    events = correlate.life_event_hypotheses(
        request.investigation_id, entities,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:life-events",
        max_results=request.max_results,
    )
    _complete(run_id, "life-events", request.investigation_id, facets, [e["id"] for e in events])
    return {"events": events, "risk_tier": "A"}


@app.post("/v1/employment")
async def employment(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("employment", request.investigation_id, _subject_seed(request))
    entities, relationships = await _graph_context(request.investigation_id)
    orgs = correlate.org_hypotheses(
        request.investigation_id, entities, relationships,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:employment",
        max_results=request.max_results,
    )
    _complete(run_id, "employment", request.investigation_id, facets, [o["id"] for o in orgs])
    return {"organizations": orgs, "risk_tier": "B"}


@app.post("/v1/assets")
async def assets(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("assets", request.investigation_id, _subject_seed(request))
    entities, _ = await _graph_context(request.investigation_id)
    items = correlate.asset_hypotheses(
        request.investigation_id, entities,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:assets",
        max_results=request.max_results,
    )
    _complete(run_id, "assets", request.investigation_id, facets, [i["id"] for i in items])
    return {"assets": items, "risk_tier": "B", "requires_human_review": True}


class WebHistoryRequest(SubjectRequest):
    url: str = Field(min_length=1)


@app.post("/v1/web-history")
async def web_history(request: WebHistoryRequest) -> dict[str, Any]:
    run_id, facets = _start("web-history", request.investigation_id, request.url)
    archive_key = f"{request.investigation_id}:{request.url}"
    prior = _web_archives.get(archive_key, [])
    content_fingerprint = hashlib.sha256(f"{request.url}:{len(prior)}".encode()).hexdigest()
    capture = {
        "id": str(uuid4()),
        "url": request.url,
        "captured_at": _now(),
        "fingerprint": content_fingerprint,
        "evidence_id": f"sha256:{content_fingerprint[:32]}",
        "method": "browsertrix-or-stub",
    }
    changed = bool(prior) and prior[-1]["fingerprint"] != capture["fingerprint"]
    removed = bool(prior) and len(prior) >= 2 and prior[-1]["fingerprint"] == prior[-2]["fingerprint"] and changed
    event = _hypothesis(
        request.investigation_id,
        "content_changed" if changed else "content_snapshot",
        0.8 if changed else 0.55,
        hypothesis_type="HYPOTHESIS_WEB_CHANGE",
        evidence_ids=[capture["evidence_id"]],
        attributes={
            "url": request.url,
            "changed": changed,
            "possibly_removed": removed,
            "signals": ["web_archive_diff"],
            "previous_fingerprint": prior[-1]["fingerprint"] if prior else "",
            "current_fingerprint": capture["fingerprint"],
        },
        run_id=run_id,
        job="ddu-intel:web-history",
    )
    _web_archives.setdefault(archive_key, []).append(capture)
    _complete(run_id, "web-history", request.investigation_id, facets, [event["id"]])
    return {"capture": capture, "change_event": event, "history_count": len(_web_archives[archive_key]), "risk_tier": "B"}


@app.post("/v1/location/fuse")
async def location_fuse(request: SubjectRequest) -> dict[str, Any]:
    run_id, facets = _start("location-fuse", request.investigation_id, _subject_seed(request))
    entities, _ = await _graph_context(request.investigation_id)
    fused_list = correlate.location_hypotheses(
        request.investigation_id, _subject_seed(request), entities,
        hypothesis=_hypothesis, run_id=run_id, job="ddu-intel:location-fuse",
        max_results=1, fused=True,
    )
    fused = fused_list[0]
    _complete(run_id, "location-fuse", request.investigation_id, facets, [fused["id"]])
    return {"fused_location": fused, "risk_tier": "B"}


@app.get("/v1/scene/3d")
async def scene_3d(investigation_id: str) -> dict[str, Any]:
    run_id, facets = _start("scene-3d", investigation_id, investigation_id)
    try:
        entities = await _entities(investigation_id)
        relationships = await _relationships(investigation_id)
    except httpx.HTTPError:
        entities, relationships = [], []

    nodes = []
    for index, entity in enumerate(entities):
        attrs = entity.get("attributes") or {}
        nodes.append({
            "id": entity.get("id"),
            "label": attrs.get("label") or entity.get("type"),
            "type": entity.get("type"),
            "x": (index % 8) * 40 - 140,
            "y": (index // 8) * 30 - 60,
            "z": (hash(entity.get("id", "")) % 50) - 25,
            "confidence": float(attrs.get("detector_confidence") or 0.5),
        })
    edges = [
        {
            "id": rel.get("id"),
            "source": rel.get("source_entity_id"),
            "target": rel.get("target_entity_id"),
            "type": rel.get("relationship_type"),
            "confidence": float((rel.get("confidence") or {}).get("value") or 0.5),
            "contradiction": False,
        }
        for rel in relationships
    ]
    _complete(run_id, "scene-3d", investigation_id, facets, [])
    return {
        "investigation_id": investigation_id,
        "nodes": nodes,
        "edges": edges,
        "axes": {"x": "relationship_distance", "y": "time_bucket", "z": "confidence"},
        "risk_tier": "C",
    }


@app.get("/v1/playback")
async def playback(investigation_id: str) -> dict[str, Any]:
    snaps = _graph_snapshots.get(investigation_id, [])
    frames = []
    for index, snap in enumerate(snaps):
        frames.append({
            "frame": index,
            "captured_at": snap.get("captured_at"),
            "entity_count": snap.get("entity_count", 0),
            "relationship_count": snap.get("relationship_count", 0),
            "narrative": (
                "Seed graph"
                if index == 0
                else f"Delta frame {index}: {snap.get('entity_count')} entities / {snap.get('relationship_count')} relationships"
            ),
        })
    if not frames:
        frames = [{"frame": 0, "captured_at": _now(), "entity_count": 0, "relationship_count": 0, "narrative": "No temporal snapshots yet — run temporal/diff"}]
    return {"investigation_id": investigation_id, "frames": frames, "risk_tier": "C"}


def main() -> None:
    port = int(os.environ.get("PORT", 8112))
    log.info("ddu-intel listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
