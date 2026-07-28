"""Graphiti-oriented temporal knowledge graph service.

Persists temporal events to Neo4j via ddu-graph-store (OpenSPG/Graphiti backend).
When graphiti-core is installed and GRAPHITI_ENABLED=1, also mirrors events into
Graphiti for episodic memory. MODEL_MODE=stub still persists durably.
"""
from __future__ import annotations

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
from ddu_common.runtime import model_mode_is_stub
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-temporal")

VERSION = from_env(ServiceVersion(
    service="ddu-temporal",
    service_version="0.0.1-dev",
    tool="graphiti",
    tool_version="0.5.0",
))

GRAPH_STORE_URL = os.environ.get("DDU_GRAPH_STORE_URL", "http://localhost:8004").rstrip("/")
GRAPHITI_ENABLED = os.environ.get("GRAPHITI_ENABLED", "").lower() in {"1", "true", "yes"}
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "ddudevpass")

graph_client = httpx.AsyncClient(base_url=GRAPH_STORE_URL, timeout=30.0)


class IngestEventRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    timestamp: str | None = None
    label: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)


class TemporalBackend(Protocol):
    async def add(self, event: dict[str, Any]) -> dict[str, Any]: ...
    async def timeline(self, investigation_id: str) -> list[dict[str, Any]]: ...


class GraphStoreTemporalBackend:
    """Durable temporal store backed by Neo4j through ddu-graph-store."""

    async def add(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "investigation_id": event["investigation_id"],
            "type": "ENTITY_TYPE_EVENT",
            "attributes": {
                "temporal_event": "1",
                "event_id": event["id"],
                "entity_id": event["entity_id"],
                "event_type": event["type"],
                "label": event.get("label", ""),
                "timestamp": event.get("timestamp", ""),
                **{f"attr_{k}": str(v) for k, v in (event.get("attributes") or {}).items()},
            },
            "evidence_ids": event.get("evidence_ids", []),
            "provenance": event.get("provenance", {}),
        }
        response = await graph_client.post("/v1/entities", json=payload)
        response.raise_for_status()
        created = response.json()
        event["graph_entity_id"] = created.get("id")
        return event

    async def timeline(self, investigation_id: str) -> list[dict[str, Any]]:
        response = await graph_client.get(
            "/v1/entities",
            params={"investigation_id": investigation_id, "type": "ENTITY_TYPE_EVENT"},
        )
        response.raise_for_status()
        events: list[dict[str, Any]] = []
        for entity in response.json().get("entities", []):
            attrs = entity.get("attributes", {}) or {}
            if attrs.get("temporal_event") != "1" and not attrs.get("event_type"):
                continue
            events.append({
                "id": attrs.get("event_id") or entity.get("id"),
                "investigation_id": investigation_id,
                "entity_id": attrs.get("entity_id", entity.get("id")),
                "type": attrs.get("event_type", "EVENT"),
                "label": attrs.get("label", ""),
                "timestamp": attrs.get("timestamp") or entity.get("created_at"),
                "attributes": {
                    key.removeprefix("attr_"): value
                    for key, value in attrs.items()
                    if key.startswith("attr_")
                },
                "graph_entity_id": entity.get("id"),
            })
        events.sort(key=lambda item: item.get("timestamp") or "")
        return events


class GraphitiTemporalBackend:
    """Optional Graphiti mirror; primary durability remains GraphStoreTemporalBackend."""

    def __init__(self, primary: GraphStoreTemporalBackend) -> None:
        self._primary = primary
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from graphiti_core import Graphiti  # type: ignore

        self._client = Graphiti(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        return self._client

    async def add(self, event: dict[str, Any]) -> dict[str, Any]:
        stored = await self._primary.add(event)
        try:
            client = self._ensure_client()
            await client.add_episode(
                name=stored.get("label") or stored.get("type") or "event",
                episode_body=(
                    f"investigation={stored['investigation_id']} "
                    f"entity={stored['entity_id']} type={stored['type']} "
                    f"label={stored.get('label', '')}"
                ),
                source_description="ddu-temporal",
                reference_time=datetime.fromisoformat(
                    stored["timestamp"].replace("Z", "+00:00")
                ) if stored.get("timestamp") else datetime.now(timezone.utc),
            )
            stored["graphiti_mirrored"] = True
        except Exception as exc:  # noqa: BLE001
            log.warning("graphiti episode mirror failed: %s", exc)
            stored["graphiti_mirrored"] = False
            stored["graphiti_error"] = str(exc)
        return stored

    async def timeline(self, investigation_id: str) -> list[dict[str, Any]]:
        return await self._primary.timeline(investigation_id)


def _build_store() -> TemporalBackend:
    primary = GraphStoreTemporalBackend()
    if GRAPHITI_ENABLED and not model_mode_is_stub():
        try:
            import graphiti_core  # noqa: F401
            log.info("GRAPHITI_ENABLED: using Graphiti + graph-store backend")
            return GraphitiTemporalBackend(primary)
        except ImportError:
            log.warning("graphiti-core not installed; using graph-store backend only")
    return primary


app = build_scaffold_app(VERSION)
lineage = LineageEmitter(VERSION)
store: TemporalBackend = _build_store()


@app.post("/v1/events")
async def ingest_event(request: IngestEventRequest) -> dict:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-temporal:ingest-event",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.entity_id,
            type="DDU.ENTITY",
        )],
        facets=facets,
    ))
    event = {
        "id": str(uuid4()),
        "investigation_id": request.investigation_id,
        "entity_id": request.entity_id,
        "type": request.event_type,
        "label": request.label or request.event_type,
        "timestamp": request.timestamp or datetime.now(timezone.utc).isoformat(),
        "attributes": request.attributes,
        "provenance": {
            "produced_by_service": VERSION.service,
            "run_id": run_id,
            "job_name": "ddu-temporal:ingest-event",
            "extraction_method": "graphiti" if GRAPHITI_ENABLED and not model_mode_is_stub() else "graph-store",
        },
    }
    try:
        event = await store.add(event)
    except httpx.HTTPError as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-temporal:ingest-event",
            facets=facets,
        ))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-temporal:ingest-event",
        outputs=[Output(
            namespace=request.investigation_id,
            name=event["id"],
            type="DDU.TEMPORAL_EVENT",
        )],
        facets=facets,
    ))
    return event


@app.get("/v1/timeline")
async def timeline(investigation_id: str) -> dict:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-temporal:timeline",
        facets=facets,
    ))
    try:
        events = await store.timeline(investigation_id)
        if not events:
            response = await graph_client.get(
                "/v1/entities",
                params={"investigation_id": investigation_id, "type": "ENTITY_TYPE_OBSERVATION"},
            )
            response.raise_for_status()
            for entity in response.json().get("entities", []):
                attrs = entity.get("attributes", {}) or {}
                events.append({
                    "id": entity.get("id"),
                    "investigation_id": investigation_id,
                    "entity_id": entity.get("id"),
                    "type": attrs.get("observation_type", "OBSERVATION"),
                    "label": attrs.get("label", ""),
                    "timestamp": attrs.get("observed_at") or entity.get("created_at"),
                    "evidence_id": attrs.get("evidence_id", ""),
                })
            events.sort(key=lambda item: item.get("timestamp") or "")
    except httpx.HTTPError as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-temporal:timeline",
            facets=facets,
        ))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-temporal:timeline",
        facets=facets,
    ))
    return {"events": events, "backend": type(store).__name__}


def main() -> None:
    port = int(os.environ.get("PORT", 8108))
    log.info("ddu-temporal listening on :%d backend=%s", port, type(store).__name__)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
