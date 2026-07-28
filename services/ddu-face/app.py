"""CompreFace face/person similarity service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from typing import Protocol
from uuid import uuid4

import httpx
import uvicorn
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ddu_common.app import build_scaffold_app
from ddu_common.evidence_client import EvidenceClient
from ddu_common.lineage import Event, Input, LineageEmitter, Output
from ddu_common.runtime import model_mode_is_stub
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-face")

VERSION = from_env(ServiceVersion(
    service="ddu-face",
    service_version="0.0.1-dev",
    tool="compreface",
    tool_version="1.2.0",
    model="compreface",
    model_version="1.2.0",
))

COMPREFACE_URL = os.environ.get("COMPREFACE_URL", "http://localhost:8000").rstrip("/")
COMPREFACE_API_KEY = os.environ.get("COMPREFACE_API_KEY", "")


class FaceRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    subject_id: str | None = None


@dataclass(frozen=True)
class FaceMatch:
    subject_id: str
    confidence: float
    bbox: dict[str, float] | None


class FaceAdapter(Protocol):
    async def match(self, content: bytes, subject_id: str | None) -> list[FaceMatch]: ...


class DevelopmentFace:
    async def match(self, content: bytes, subject_id: str | None) -> list[FaceMatch]:
        del content
        return [FaceMatch(subject_id or "unknown-subject", 0.55, {
            "x": 0.2, "y": 0.2, "width": 0.3, "height": 0.4,
        })]


class CompreFaceAdapter:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def match(self, content: bytes, subject_id: str | None) -> list[FaceMatch]:
        headers = {"x-api-key": COMPREFACE_API_KEY} if COMPREFACE_API_KEY else {}
        files = {"file": ("evidence.bin", content, "application/octet-stream")}
        if subject_id:
            response = await self._client.post(
                f"/api/v1/recognition/faces/{subject_id}/verify",
                headers=headers,
                files=files,
            )
        else:
            response = await self._client.post(
                "/api/v1/recognition/recognize",
                headers=headers,
                files=files,
            )
        response.raise_for_status()
        body = response.json()
        matches: list[FaceMatch] = []
        for item in body.get("result", []) if isinstance(body, dict) else []:
            subjects = item.get("subjects") or []
            box = item.get("box") or {}
            bbox = None
            if box:
                bbox = {
                    "x": float(box.get("x_min", 0)),
                    "y": float(box.get("y_min", 0)),
                    "width": float(box.get("x_max", 0)) - float(box.get("x_min", 0)),
                    "height": float(box.get("y_max", 0)) - float(box.get("y_min", 0)),
                }
            if subjects:
                top = subjects[0]
                matches.append(FaceMatch(
                    str(top.get("subject", "unknown")),
                    float(top.get("similarity", 0.0)),
                    bbox,
                ))
            else:
                matches.append(FaceMatch("unmatched", 0.0, bbox))
        return matches


app = build_scaffold_app(VERSION)
evidence_client = EvidenceClient()
lineage = LineageEmitter(VERSION)
compreface_client = httpx.AsyncClient(base_url=COMPREFACE_URL, timeout=60.0)
face_adapter: FaceAdapter = (
    DevelopmentFace()
    if model_mode_is_stub()
    else CompreFaceAdapter(compreface_client)
)


@app.post("/v1/match")
async def match_faces(request: FaceRequest) -> list[dict]:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-face:match",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.evidence_id,
            type="DDU.EVIDENCE",
        )],
        facets=facets,
    ))
    try:
        content, _ = await evidence_client.fetch(
            request.evidence_id,
            request.investigation_id,
        )
        matches = await face_adapter.match(content, request.subject_id)
    except (httpx.HTTPError, RuntimeError, ValueError, OSError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-face:match",
            facets=facets,
        ))
        log.exception("face matching failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    observed_at = datetime.now(timezone.utc).isoformat()
    method = "development-stub" if isinstance(face_adapter, DevelopmentFace) else "compreface"
    observations = []
    for item in matches:
        observations.append({
            "id": str(uuid4()),
            "investigation_id": request.investigation_id,
            "evidence_id": request.evidence_id,
            "type": "OBSERVATION_TYPE_FACE",
            "label": item.subject_id,
            "detector_confidence": item.confidence,
            "attributes": {
                "subject_id": item.subject_id,
                "epistemic_class": "EPISTEMIC_CLASS_OBSERVATION",
            },
            "bbox": item.bbox,
            "provenance": {
                "investigation_id": request.investigation_id,
                "produced_by_service": VERSION.service,
                "producer_version": VERSION.as_dict(),
                "tool": VERSION.tool,
                "tool_version": VERSION.tool_version,
                "model": VERSION.model,
                "model_version": VERSION.model_version,
                "produced_at": observed_at,
                "run_id": run_id,
                "job_name": "ddu-face:match",
                "input_evidence_ids": [request.evidence_id],
                "extraction_method": method,
                "parameters": {"subject_id": request.subject_id or ""},
            },
            "observed_at": observed_at,
        })
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-face:match",
        outputs=[
            Output(
                namespace=request.investigation_id,
                name=item["id"],
                type="DDU.OBSERVATION",
            )
            for item in observations
        ],
        facets=facets,
    ))
    return observations


def main() -> None:
    port = int(os.environ.get("PORT", 8102))
    log.info("ddu-face listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
