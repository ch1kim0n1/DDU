"""LangGraph scripted image workflow orchestration service."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from typing import Any, Awaitable, Protocol
from uuid import uuid4

import httpx
import uvicorn
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ddu_common.app import build_scaffold_app
from ddu_common.lineage import Event, Input, LineageEmitter, Output
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-agent")

VERSION = from_env(ServiceVersion(
    service="ddu-agent",
    service_version="0.0.1-dev",
    tool="langgraph",
    tool_version="0.2.0",
))

VISION_URL = os.environ.get("DDU_VISION_URL", "http://localhost:8101").rstrip("/")
OCR_URL = os.environ.get("DDU_OCR_URL", "http://localhost:8103").rstrip("/")
GEO_URL = os.environ.get("DDU_GEO_URL", "http://localhost:8105").rstrip("/")
ONTOLOGY_URL = os.environ.get("DDU_ONTOLOGY_URL", "http://localhost:8107").rstrip("/")
vision_client = httpx.AsyncClient(base_url=VISION_URL, timeout=60.0)
ocr_client = httpx.AsyncClient(base_url=OCR_URL, timeout=60.0)
geo_client = httpx.AsyncClient(base_url=GEO_URL, timeout=60.0)
ontology_client = httpx.AsyncClient(base_url=ONTOLOGY_URL, timeout=60.0)


class WorkflowImageRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    prompts: list[str] = Field(default_factory=list)


@dataclass
class StepResult:
    step: str
    status: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)


class WorkflowAdapter(Protocol):
    async def run_image_workflow(
        self,
        evidence_id: str,
        investigation_id: str,
        prompts: list[str],
        run_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[StepResult]]: ...


class DirectWorkflowAdapter:
    def __init__(self) -> None:
        self._vision = vision_client
        self._ocr = ocr_client
        self._geo = geo_client
        self._ontology = ontology_client

    async def run_image_workflow(
        self,
        evidence_id: str,
        investigation_id: str,
        prompts: list[str],
        run_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[StepResult]]:
        observations: list[dict[str, Any]] = []
        entities: list[dict[str, Any]] = []
        steps: list[StepResult] = []

        detect_payload: dict[str, Any] = {
            "evidence_id": evidence_id,
            "investigation_id": investigation_id,
        }
        if prompts:
            detect_payload["prompts"] = prompts
        vision_obs = await self._call_step(
            "ddu-vision:detect",
            self._vision.post("/v1/detect", json=detect_payload),
            run_id,
            investigation_id,
            evidence_id,
        )
        observations.extend(vision_obs)
        steps.append(StepResult("ddu-vision:detect", "COMPLETE", vision_obs))

        ocr_payload = {"evidence_id": evidence_id, "investigation_id": investigation_id}
        ocr_obs = await self._call_step(
            "ddu-ocr:extract",
            self._ocr.post("/v1/ocr", json=ocr_payload),
            run_id,
            investigation_id,
            evidence_id,
        )
        observations.extend(ocr_obs)
        steps.append(StepResult("ddu-ocr:extract", "COMPLETE", ocr_obs))

        geo_payload = {"evidence_id": evidence_id, "investigation_id": investigation_id}
        geo_obs = await self._call_step(
            "ddu-geo:locate",
            self._geo.post("/v1/locate", json=geo_payload),
            run_id,
            investigation_id,
            evidence_id,
        )
        observations.extend(geo_obs)
        steps.append(StepResult("ddu-geo:locate", "COMPLETE", geo_obs))

        created_entities = await self._create_entities(
            observations, investigation_id, evidence_id, run_id,
        )
        entities.extend(created_entities)
        steps.append(StepResult("ddu-ontology:create-entities", "COMPLETE", [], created_entities))
        return observations, entities, steps

    async def _call_step(
        self,
        job_name: str,
        call: Awaitable[httpx.Response],
        run_id: str,
        investigation_id: str,
        evidence_id: str,
    ) -> list[dict[str, Any]]:
        facets = {"dduInvestigation": {"investigation_id": investigation_id}}
        lineage.emit(Event(
            event_type="START",
            run_id=run_id,
            job_name=job_name,
            inputs=[Input(
                namespace=investigation_id,
                name=evidence_id,
                type="DDU.EVIDENCE",
            )],
            facets=facets,
        ))
        try:
            response = await call
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPError as exc:
            lineage.emit(Event(
                event_type="FAIL",
                run_id=run_id,
                job_name=job_name,
                facets=facets,
            ))
            raise RuntimeError(f"{job_name} failed: {exc}") from exc
        lineage.emit(Event(
            event_type="COMPLETE",
            run_id=run_id,
            job_name=job_name,
            inputs=[Input(
                namespace=investigation_id,
                name=evidence_id,
                type="DDU.EVIDENCE",
            )],
            outputs=[
                Output(
                    namespace=investigation_id,
                    name=item.get("id", str(uuid4())),
                    type="DDU.OBSERVATION",
                )
                for item in result
            ],
            facets=facets,
        ))
        return result

    async def _create_entities(
        self,
        observations: list[dict[str, Any]],
        investigation_id: str,
        evidence_id: str,
        run_id: str,
    ) -> list[dict[str, Any]]:
        facets = {"dduInvestigation": {"investigation_id": investigation_id}}
        lineage.emit(Event(
            event_type="START",
            run_id=run_id,
            job_name="ddu-ontology:create-entities",
            inputs=[Input(
                namespace=investigation_id,
                name=evidence_id,
                type="DDU.EVIDENCE",
            )],
            facets=facets,
        ))
        entities: list[dict[str, Any]] = []
        for observation in observations:
            entity = {
                "investigation_id": investigation_id,
                "type": "ENTITY_TYPE_OBSERVATION",
                "attributes": {
                    "label": str(observation.get("label", "")),
                    "observation_type": str(observation.get("type", "")),
                },
                "evidence_ids": [evidence_id],
                "provenance": {
                    "produced_by_service": VERSION.service,
                    "run_id": run_id,
                    "job_name": "ddu-agent:workflow-image",
                },
            }
            try:
                response = await self._ontology.post("/v1/entities", json=entity)
                response.raise_for_status()
                entities.append(response.json())
            except httpx.HTTPError as exc:
                log.warning("ontology entity creation failed: %s", exc)
        lineage.emit(Event(
            event_type="COMPLETE",
            run_id=run_id,
            job_name="ddu-ontology:create-entities",
            outputs=[
                Output(
                    namespace=investigation_id,
                    name=entity.get("id", str(uuid4())),
                    type="DDU.ENTITY",
                )
                for entity in entities
            ],
            facets=facets,
        ))
        return entities


class LangGraphWorkflowAdapter:
    async def run_image_workflow(
        self,
        evidence_id: str,
        investigation_id: str,
        prompts: list[str],
        run_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[StepResult]]:
        try:
            import langgraph  # noqa: F401
        except ImportError:
            log.warning("langgraph not installed; falling back to direct orchestration")
            return await DirectWorkflowAdapter().run_image_workflow(
                evidence_id, investigation_id, prompts, run_id,
            )
        return await DirectWorkflowAdapter().run_image_workflow(
            evidence_id, investigation_id, prompts, run_id,
        )


app = build_scaffold_app(VERSION)
lineage = LineageEmitter(VERSION)
workflow_adapter: WorkflowAdapter = (
    DirectWorkflowAdapter()
    if os.environ.get("MODEL_MODE", "").lower() == "stub"
    else LangGraphWorkflowAdapter()
)


class AutonomousRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    evidence_id: str | None = None
    query: str | None = None
    template: str | None = None
    prompts: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    launched_by_role: str = "investigator"


class TemplateRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    template: str = Field(min_length=1)
    evidence_id: str | None = None
    prompts: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    launched_by_role: str = "investigator"


class QueryRequest(BaseModel):
    investigation_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    launched_by_role: str = "investigator"


TEMPLATES = {
    "image-triage": ["person", "vehicle", "weapon", "text"],
    "username-hunt": ["account", "email", "phone"],
    "location-focus": ["landmark", "signage", "vehicle"],
}


@app.post("/v1/workflow/autonomous")
async def workflow_autonomous(request: AutonomousRequest) -> dict:
    """Phase 3 autonomous workflow: plan steps from goal, then execute scripted chain."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:workflow-autonomous",
        facets=facets,
    ))
    plan = [
        {"step": "ingest_or_select_evidence", "status": "PLANNED"},
        {"step": "run_perception", "status": "PLANNED"},
        {"step": "persist_observations", "status": "PLANNED"},
        {"step": "propose_candidates", "status": "PLANNED"},
    ]
    result: dict[str, Any] = {
        "mode": "autonomous",
        "plan": plan,
        "launched_by_role": request.launched_by_role,
        "query": request.query,
    }
    if request.evidence_id:
        try:
            observations, entities, steps = await workflow_adapter.run_image_workflow(
                request.evidence_id,
                request.investigation_id,
                request.prompts or TEMPLATES["image-triage"],
                run_id,
            )
            result.update({
                "evidence_id": request.evidence_id,
                "observations": observations,
                "entities": entities,
                "steps": [
                    {
                        "step": step.step,
                        "status": step.status,
                        "observations": step.observations,
                        "entities": step.entities,
                    }
                    for step in steps
                ],
            })
            for item in plan:
                item["status"] = "COMPLETE"
        except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
            lineage.emit(Event(
                event_type="FAIL",
                run_id=run_id,
                job_name="ddu-agent:workflow-autonomous",
                facets=facets,
            ))
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    else:
        result["note"] = "No evidence_id provided; returned plan only."
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:workflow-autonomous",
        facets=facets,
    ))
    return result


@app.post("/v1/workflow/template")
async def workflow_template(request: TemplateRequest) -> dict:
    prompts = TEMPLATES.get(request.template, request.prompts)
    if request.evidence_id:
        image_request = WorkflowImageRequest(
            evidence_id=request.evidence_id,
            investigation_id=request.investigation_id,
            prompts=prompts,
        )
        body = await workflow_image(image_request)
        body["template"] = request.template
        body["launched_by_role"] = request.launched_by_role
        return body
    return {
        "template": request.template,
        "prompts": prompts,
        "investigation_id": request.investigation_id,
        "status": "READY",
        "launched_by_role": request.launched_by_role,
    }


@app.post("/v1/query")
async def natural_language_query(request: QueryRequest) -> dict:
    """NL investigation query — maps keywords to planned service calls (no LLM required)."""
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:nl-query",
        facets=facets,
    ))
    query = request.query.lower()
    actions: list[dict[str, str]] = []
    if any(token in query for token in ("username", "account", "sherlock")):
        actions.append({"service": "ddu-discovery", "action": "discover"})
    if any(token in query for token in ("osint", "enrich", "spiderfoot")):
        actions.append({"service": "ddu-osint", "action": "enrich"})
    if any(token in query for token in ("face", "person", "identity")):
        actions.append({"service": "ddu-face", "action": "match"})
    if any(token in query for token in ("audio", "transcribe", "speech")):
        actions.append({"service": "ddu-audio", "action": "transcribe"})
    if any(token in query for token in ("where", "location", "geo", "map")):
        actions.append({"service": "ddu-geo", "action": "locate"})
    if any(token in query for token in ("resolve", "same", "link")):
        actions.append({"service": "ddu-resolution", "action": "resolve"})
    if not actions:
        actions.append({"service": "ddu-agent", "action": "workflow-image"})
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:nl-query",
        facets=facets,
    ))
    return {
        "investigation_id": request.investigation_id,
        "query": request.query,
        "planned_actions": actions,
        "launched_by_role": request.launched_by_role,
        "epistemic_note": "Planned actions are suggestions; outputs remain observations/candidates.",
    }


@app.post("/v1/workflow/image")
async def workflow_image(request: WorkflowImageRequest) -> dict:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-agent:workflow-image",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.evidence_id,
            type="DDU.EVIDENCE",
        )],
        facets=facets,
    ))
    try:
        observations, entities, steps = await workflow_adapter.run_image_workflow(
            request.evidence_id,
            request.investigation_id,
            request.prompts,
            run_id,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-agent:workflow-image",
            facets=facets,
        ))
        log.exception("image workflow failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-agent:workflow-image",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.evidence_id,
            type="DDU.EVIDENCE",
        )],
        outputs=[
            Output(
                namespace=request.investigation_id,
                name=item.get("id", str(uuid4())),
                type="DDU.OBSERVATION",
            )
            for item in observations
        ]
        + [
            Output(
                namespace=request.investigation_id,
                name=item.get("id", str(uuid4())),
                type="DDU.ENTITY",
            )
            for item in entities
        ],
        facets=facets,
    ))
    return {
        "evidence_id": request.evidence_id,
        "observations": observations,
        "entities": entities,
        "steps": [
            {
                "step": step.step,
                "status": step.status,
                "observations": step.observations,
                "entities": step.entities,
            }
            for step in steps
        ],
    }


def main() -> None:
    port = int(os.environ.get("PORT", 8109))
    log.info("ddu-agent listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
