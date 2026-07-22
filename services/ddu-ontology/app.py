"""DDU ontology validation and graph-store proxy."""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import uvicorn
from fastapi import HTTPException

from ddu_common.app import build_scaffold_app
from ddu_common.lineage import Event, Input, LineageEmitter, Output
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-ontology")

VERSION = from_env(ServiceVersion(
    service="ddu-ontology",
    service_version="0.0.1-dev",
    tool="ddu-schema-validator",
    tool_version="1.0.0",
))

ENTITY_TYPES = {
    "ENTITY_TYPE_UNSPECIFIED": 0,
    "ENTITY_TYPE_PERSON": 1,
    "ENTITY_TYPE_ACCOUNT": 2,
    "ENTITY_TYPE_USERNAME": 3,
    "ENTITY_TYPE_ORGANIZATION": 4,
    "ENTITY_TYPE_LOCATION": 5,
    "ENTITY_TYPE_OBJECT": 6,
    "ENTITY_TYPE_VEHICLE": 7,
    "ENTITY_TYPE_IMAGE": 8,
    "ENTITY_TYPE_VIDEO": 9,
    "ENTITY_TYPE_AUDIO": 10,
    "ENTITY_TYPE_DOCUMENT": 11,
    "ENTITY_TYPE_POST": 12,
    "ENTITY_TYPE_EVENT": 13,
    "ENTITY_TYPE_OBSERVATION": 14,
    "ENTITY_TYPE_EVIDENCE": 15,
    "ENTITY_TYPE_SOURCE": 16,
    "ENTITY_TYPE_CLAIM": 17,
    "ENTITY_TYPE_HYPOTHESIS": 18,
    "ENTITY_TYPE_INVESTIGATION": 19,
    "ENTITY_TYPE_CANDIDATE_ACCOUNT": 20,
}
GRAPH_STORE_URL = os.environ.get("DDU_GRAPH_STORE_URL", "http://localhost:8004").rstrip("/")
graph_client = httpx.AsyncClient(base_url=GRAPH_STORE_URL, timeout=10.0)
lineage = LineageEmitter(VERSION)
app = build_scaffold_app(VERSION)


@app.get("/v1/entity-types")
async def entity_types() -> dict[str, list[dict[str, int | str]]]:
    return {
        "entity_types": [
            {"name": name, "number": number}
            for name, number in ENTITY_TYPES.items()
        ]
    }


@app.post("/v1/entities", status_code=201)
async def create_entity(entity: dict[str, Any]) -> dict[str, Any]:
    entity_type = str(entity.get("type", ""))
    if entity_type not in ENTITY_TYPES or entity_type == "ENTITY_TYPE_UNSPECIFIED":
        raise HTTPException(
            status_code=422,
            detail={"field": "type", "allowed_values": list(ENTITY_TYPES)[1:]},
        )
    investigation_id = str(entity.get("investigation_id", ""))
    if not investigation_id:
        raise HTTPException(status_code=422, detail="investigation_id is required")

    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-ontology:validate-entity",
        inputs=[
            Input(
                namespace=investigation_id,
                name=str(entity.get("id", "new-entity")),
                type="DDU.ENTITY",
            )
        ],
        facets=facets,
    ))
    try:
        response = await graph_client.post("/v1/entities", json=entity)
    except httpx.HTTPError as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-ontology:validate-entity",
            facets=facets,
        ))
        raise HTTPException(status_code=502, detail="graph-store unavailable") from exc
    if response.status_code >= 400:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-ontology:validate-entity",
            facets=facets,
        ))
        raise HTTPException(status_code=response.status_code, detail=response.text[:1024])

    created = response.json()
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-ontology:validate-entity",
        outputs=[
            Output(
                namespace=investigation_id,
                name=str(created.get("id", entity.get("id", ""))),
                type="DDU.ENTITY",
            )
        ],
        facets=facets,
    ))
    return created


def main() -> None:
    port = int(os.environ.get("PORT", 8107))
    log.info("ddu-ontology listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
