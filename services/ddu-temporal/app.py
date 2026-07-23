"""Graphiti temporal knowledge graph service."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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
graph_client = httpx.AsyncClient(base_url=GRAPH_STORE_URL, timeout=30.0)


class IngestEventRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    timestamp: str | None = None
    label: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)


@dataclass
class TemporalStore:
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def add(self, investigation_id: str, event: dict[str, Any]) -> dict[str, Any]:
        self.events.setdefault(investigation_id, []).append(event)
        self.events[investigation_id].sort(key=lambda item: item.get("timestamp") or "")
        return event

    def timeline(self, investigation_id: str) -> list[dict[str, Any]]:
        return list(self.events.get(investigation_id, []))


app = build_scaffold_app(VERSION)
lineage = LineageEmitter(VERSION)
store = TemporalStore()


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
            "extraction_method": (
                "development-stub"
                if os.environ.get("MODEL_MODE", "").lower() == "stub"
                else "graphiti"
            ),
        },
    }
    store.add(request.investigation_id, event)
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
    events = store.timeline(investigation_id)
    if not events:
        try:
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
    return {"events": events}


def main() -> None:
    port = int(os.environ.get("PORT", 8108))
    log.info("ddu-temporal listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
