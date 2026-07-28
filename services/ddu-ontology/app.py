"""DDU ontology validation, custom type builder, and graph-store proxy."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import re
from typing import Any

import httpx
import uvicorn
from fastapi import HTTPException
from pydantic import BaseModel, Field

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

CORE_ENTITY_TYPES = {
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

TYPE_NAME_RE = re.compile(r"^ENTITY_TYPE_[A-Z][A-Z0-9_]*$")
GRAPH_STORE_URL = os.environ.get("DDU_GRAPH_STORE_URL", "http://localhost:8004").rstrip("/")
graph_client = httpx.AsyncClient(base_url=GRAPH_STORE_URL, timeout=10.0)
lineage = LineageEmitter(VERSION)
app = build_scaffold_app(VERSION)

# Cache + Neo4j (via graph-store) persistence for custom ontology types.
# OpenSPG uses Neo4j as its graph engine; custom types are stored as
# ENTITY_TYPE_CLAIM registry nodes with ddu_ontology_type=1.
_custom_types: dict[str, dict[str, dict[str, Any]]] = {}
_next_type_number = 1000
_loaded_investigations: set[str] = set()


class CustomTypeRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    parent_type: str = "ENTITY_TYPE_OBJECT"
    attributes: list[str] = Field(default_factory=list)


async def _load_custom_types(investigation_id: str) -> None:
    if investigation_id in _loaded_investigations:
        return
    try:
        response = await graph_client.get(
            "/v1/entities",
            params={"investigation_id": investigation_id, "type": "ENTITY_TYPE_CLAIM"},
        )
        response.raise_for_status()
        registry = _custom_types.setdefault(investigation_id, {})
        for entity in response.json().get("entities", []):
            attrs = entity.get("attributes", {}) or {}
            if attrs.get("ddu_ontology_type") != "1":
                continue
            name = attrs.get("type_name", "")
            if not name:
                continue
            number = int(attrs.get("type_number", "1000"))
            global _next_type_number
            _next_type_number = max(_next_type_number, number + 1)
            registry[name] = {
                "name": name,
                "number": number,
                "description": attrs.get("description", ""),
                "parent_type": attrs.get("parent_type", "ENTITY_TYPE_OBJECT"),
                "attributes": [a for a in attrs.get("attribute_keys", "").split(",") if a],
                "investigation_id": investigation_id,
                "created_at": attrs.get("created_at") or entity.get("created_at", ""),
                "graph_entity_id": entity.get("id"),
            }
        _loaded_investigations.add(investigation_id)
    except httpx.HTTPError as exc:
        log.warning("ontology registry load failed for %s: %s", investigation_id, exc)


async def _persist_custom_type(meta: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "investigation_id": meta["investigation_id"],
        "type": "ENTITY_TYPE_CLAIM",
        "attributes": {
            "ddu_ontology_type": "1",
            "type_name": meta["name"],
            "type_number": str(meta["number"]),
            "description": meta.get("description", ""),
            "parent_type": meta.get("parent_type", "ENTITY_TYPE_OBJECT"),
            "attribute_keys": ",".join(meta.get("attributes") or []),
            "created_at": meta.get("created_at", ""),
            "backend": "openspg-neo4j",
        },
        "evidence_ids": [],
        "provenance": {
            "produced_by_service": VERSION.service,
            "job_name": "ddu-ontology:create-type",
            "extraction_method": "openspg-neo4j-registry",
        },
    }
    response = await graph_client.post("/v1/entities", json=payload)
    response.raise_for_status()
    created = response.json()
    meta["graph_entity_id"] = created.get("id")
    return meta


def _all_types(investigation_id: str | None = None) -> dict[str, int]:
    types = dict(CORE_ENTITY_TYPES)
    if investigation_id:
        for name, meta in _custom_types.get(investigation_id, {}).items():
            types[name] = int(meta["number"])
    else:
        for registry in _custom_types.values():
            for name, meta in registry.items():
                types[name] = int(meta["number"])
    return types


def _normalize_type_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name.strip()).upper()
    if not cleaned.startswith("ENTITY_TYPE_"):
        cleaned = "ENTITY_TYPE_" + cleaned
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not TYPE_NAME_RE.match(cleaned):
        raise HTTPException(status_code=422, detail="invalid entity type name")
    return cleaned


@app.get("/v1/entity-types")
async def entity_types(investigation_id: str | None = None) -> dict[str, Any]:
    if investigation_id:
        await _load_custom_types(investigation_id)
    types = _all_types(investigation_id)
    custom = []
    if investigation_id:
        custom = list(_custom_types.get(investigation_id, {}).values())
    return {
        "entity_types": [
            {"name": name, "number": number, "custom": name not in CORE_ENTITY_TYPES}
            for name, number in types.items()
        ],
        "custom_types": custom,
        "backend": "openspg-neo4j",
    }


@app.post("/v1/entity-types", status_code=201)
async def create_entity_type(request: CustomTypeRequest) -> dict[str, Any]:
    """Custom ontology builder — persist investigation-scoped types to Neo4j/OpenSPG."""
    global _next_type_number
    await _load_custom_types(request.investigation_id)
    name = _normalize_type_name(request.name)
    if name in CORE_ENTITY_TYPES:
        raise HTTPException(status_code=409, detail="cannot redefine a core entity type")
    registry = _custom_types.setdefault(request.investigation_id, {})
    if name in registry:
        raise HTTPException(status_code=409, detail="entity type already exists")
    parent = request.parent_type
    if parent not in _all_types(request.investigation_id):
        raise HTTPException(status_code=422, detail="parent_type is unknown")

    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-ontology:create-type",
        facets=facets,
    ))
    meta = {
        "name": name,
        "number": _next_type_number,
        "description": request.description,
        "parent_type": parent,
        "attributes": request.attributes,
        "investigation_id": request.investigation_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        meta = await _persist_custom_type(meta)
    except httpx.HTTPError as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-ontology:create-type",
            facets=facets,
        ))
        raise HTTPException(status_code=503, detail=f"ontology persistence failed: {exc}") from exc
    _next_type_number += 1
    registry[name] = meta
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-ontology:create-type",
        outputs=[Output(
            namespace=request.investigation_id,
            name=name,
            type="DDU.ONTOLOGY_TYPE",
        )],
        facets=facets,
    ))
    return meta


@app.get("/v1/schema")
async def schema(investigation_id: str | None = None) -> dict[str, Any]:
    if investigation_id:
        await _load_custom_types(investigation_id)
    return {
        "core_entity_types": list(CORE_ENTITY_TYPES)[1:],
        "custom_types": (
            list(_custom_types.get(investigation_id, {}).values())
            if investigation_id
            else [item for reg in _custom_types.values() for item in reg.values()]
        ),
        "builder": {
            "mode": "openspg-neo4j-registry",
            "note": "Custom types persist as Neo4j Claim nodes via ddu-graph-store (OpenSPG backend).",
        },
    }


@app.post("/v1/entities", status_code=201)
async def create_entity(entity: dict[str, Any]) -> dict[str, Any]:
    investigation_id = str(entity.get("investigation_id", ""))
    if not investigation_id:
        raise HTTPException(status_code=422, detail="investigation_id is required")
    entity_type = str(entity.get("type", ""))
    allowed = _all_types(investigation_id)
    if entity_type not in allowed or entity_type == "ENTITY_TYPE_UNSPECIFIED":
        raise HTTPException(
            status_code=422,
            detail={"field": "type", "allowed_values": [n for n in allowed if n != "ENTITY_TYPE_UNSPECIFIED"]},
        )

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
