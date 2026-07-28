"""GeoCLIP image geolocation service."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import tempfile
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
log = logging.getLogger("ddu-geo")

VERSION = from_env(ServiceVersion(
    service="ddu-geo",
    service_version="0.0.1-dev",
    tool="geoclip",
    tool_version="1.2.0",
    model="GeoCLIP",
    model_version="1.2.0",
))


class LocateRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


@dataclass(frozen=True)
class LocationCandidate:
    label: str
    latitude: float
    longitude: float
    score: float
    radius_meters: float


class GeoAdapter(Protocol):
    def locate(self, content: bytes, top_k: int) -> list[LocationCandidate]: ...


class DevelopmentGeoAdapter:
    def locate(self, content: bytes, top_k: int) -> list[LocationCandidate]:
        del content
        values = [
            LocationCandidate("Austin, Texas", 30.2672, -97.7431, 0.5, 50000.0),
            LocationCandidate("San Antonio, Texas", 29.4241, -98.4936, 0.25, 100000.0),
        ]
        return values[:top_k]


class GeoCLIPAdapter:
    def __init__(self) -> None:
        self._model: object | None = None

    def _load(self) -> None:
        import torch
        from geoclip import GeoCLIP

        cache_dir = Path(os.environ.get(
            "MODEL_CACHE_DIR",
            "~/.cache/ddu/models/geoclip",
        )).expanduser()
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("TORCH_HOME", str(cache_dir / "torch"))
        os.environ.setdefault("HF_HOME", str(cache_dir / "huggingface"))
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        if self._device == "cpu":
            log.warning("CUDA unavailable; GeoCLIP is running on CPU")
        self._model = GeoCLIP(from_pretrained=True).to(self._device)
        self._model.eval()

    def locate(self, content: bytes, top_k: int) -> list[LocationCandidate]:
        if self._model is None:
            self._load()
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image_file:
            image_file.write(content)
            image_file.flush()
            coordinates, scores = self._model.predict(image_file.name, top_k)
        candidates: list[LocationCandidate] = []
        for index, (coordinate, score) in enumerate(
            zip(coordinates.tolist(), scores.tolist(), strict=True),
        ):
            latitude, longitude = float(coordinate[0]), float(coordinate[1])
            candidates.append(LocationCandidate(
                f"{latitude:.5f}, {longitude:.5f}",
                latitude,
                longitude,
                float(score),
                float(25000 * (index + 1)),
            ))
        return candidates


app = build_scaffold_app(VERSION)
evidence_client = EvidenceClient()
lineage = LineageEmitter(VERSION)
geo_adapter: GeoAdapter = (
    DevelopmentGeoAdapter()
    if model_mode_is_stub()
    else GeoCLIPAdapter()
)


@app.post("/v1/locate")
async def locate(request: LocateRequest) -> list[dict]:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-geo:locate",
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
        candidates = await asyncio.to_thread(
            geo_adapter.locate,
            content,
            request.top_k,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-geo:locate",
            facets=facets,
        ))
        log.exception("geolocation failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    observed_at = datetime.now(timezone.utc).isoformat()
    method = "development-stub" if isinstance(geo_adapter, DevelopmentGeoAdapter) else "geoclip"
    observations = [
        {
            "id": str(uuid4()),
            "investigation_id": request.investigation_id,
            "evidence_id": request.evidence_id,
            "type": "OBSERVATION_TYPE_LOCATION",
            "label": item.label,
            "detector_confidence": item.score,
            "attributes": {
                "rank": str(index + 1),
                "epistemic_class": "EPISTEMIC_CLASS_OBSERVATION",
            },
            "geo": {
                "latitude": item.latitude,
                "longitude": item.longitude,
                "radius_meters": item.radius_meters,
            },
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
                "job_name": "ddu-geo:locate",
                "input_evidence_ids": [request.evidence_id],
                "extraction_method": method,
                "parameters": {"top_k": str(request.top_k)},
            },
            "observed_at": observed_at,
        }
        for index, item in enumerate(candidates)
    ]
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-geo:locate",
        inputs=[Input(
            namespace=request.investigation_id,
            name=request.evidence_id,
            type="DDU.EVIDENCE",
        )],
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
    port = int(os.environ.get("PORT", 8105))
    log.info("ddu-geo listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
