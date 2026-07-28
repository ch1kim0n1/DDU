"""PaddleOCR PP-OCRv4 text extraction service."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import logging
import os
from pathlib import Path
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
log = logging.getLogger("ddu-ocr")

VERSION = from_env(ServiceVersion(
    service="ddu-ocr",
    service_version="0.0.1-dev",
    tool="paddleocr",
    tool_version="2.7.0.3",
    model="PP-OCRv4",
    model_version="4.0",
))


class OCRRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)


@dataclass(frozen=True)
class TextDetection:
    text: str
    confidence: float
    bbox: dict[str, float] | None


class OCRAdapter(Protocol):
    def extract(self, content: bytes) -> list[TextDetection]: ...


class DevelopmentOCR:
    def extract(self, content: bytes) -> list[TextDetection]:
        del content
        return [TextDetection("development OCR observation", 0.5, None)]


class PaddleOCRAdapter:
    def __init__(self) -> None:
        self._engine: object | None = None

    def _load(self) -> None:
        import paddle
        from paddleocr import PaddleOCR

        cache_dir = Path(os.environ.get(
            "MODEL_CACHE_DIR",
            "~/.cache/ddu/models/paddleocr",
        )).expanduser()
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("PADDLE_HOME", str(cache_dir))
        use_gpu = bool(paddle.device.is_compiled_with_cuda())
        if not use_gpu:
            log.warning("CUDA unavailable; PaddleOCR is running on CPU")
        self._engine = PaddleOCR(
            use_angle_cls=True,
            lang=os.environ.get("OCR_LANGUAGE", "en"),
            use_gpu=use_gpu,
            show_log=False,
        )

    def extract(self, content: bytes) -> list[TextDetection]:
        if self._engine is None:
            self._load()
        import numpy as np
        from PIL import Image

        image = Image.open(BytesIO(content)).convert("RGB")
        result = self._engine.ocr(np.asarray(image), cls=True)
        width, height = image.size
        detections: list[TextDetection] = []
        for page in result or []:
            for line in page or []:
                polygon, payload = line
                text, confidence = payload
                x_values = [float(point[0]) for point in polygon]
                y_values = [float(point[1]) for point in polygon]
                x_min, x_max = min(x_values), max(x_values)
                y_min, y_max = min(y_values), max(y_values)
                detections.append(TextDetection(
                    str(text),
                    float(confidence),
                    {
                        "x": x_min / width,
                        "y": y_min / height,
                        "width": (x_max - x_min) / width,
                        "height": (y_max - y_min) / height,
                    },
                ))
        return detections


app = build_scaffold_app(VERSION)
evidence_client = EvidenceClient()
lineage = LineageEmitter(VERSION)
ocr_adapter: OCRAdapter = (
    DevelopmentOCR()
    if model_mode_is_stub()
    else PaddleOCRAdapter()
)


@app.post("/v1/ocr")
async def ocr(request: OCRRequest) -> list[dict]:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-ocr:extract",
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
        detections = await asyncio.to_thread(ocr_adapter.extract, content)
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-ocr:extract",
            facets=facets,
        ))
        log.exception("OCR failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    observed_at = datetime.now(timezone.utc).isoformat()
    method = "development-stub" if isinstance(ocr_adapter, DevelopmentOCR) else "paddleocr"
    language = os.environ.get("OCR_LANGUAGE", "en")
    observations: list[dict] = []
    for item in detections:
        observation = {
            "id": str(uuid4()),
            "investigation_id": request.investigation_id,
            "evidence_id": request.evidence_id,
            "type": "OBSERVATION_TYPE_TEXT",
            "label": item.text,
            "detector_confidence": item.confidence,
            "attributes": {
                "language": language,
                "confidence": f"{item.confidence:.6f}",
                "epistemic_class": "EPISTEMIC_CLASS_OBSERVATION",
            },
            "text": {"text": item.text, "language": language},
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
                "job_name": "ddu-ocr:extract",
                "input_evidence_ids": [request.evidence_id],
                "extraction_method": method,
                "parameters": {"language": language},
            },
            "observed_at": observed_at,
        }
        if item.bbox is not None:
            observation["bbox"] = item.bbox
        observations.append(observation)

    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-ocr:extract",
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
    port = int(os.environ.get("PORT", 8103))
    log.info("ddu-ocr listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
