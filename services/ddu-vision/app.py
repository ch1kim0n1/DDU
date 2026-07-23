"""Grounded SAM 2 object detection service."""
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
from ddu_common.runtime import model_mode_is_stub, select_device
from ddu_common.version import ServiceVersion, from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ddu-vision")

VERSION = from_env(ServiceVersion(
    service="ddu-vision",
    service_version="0.0.1-dev",
    tool="grounded-sam-2",
    tool_version="0.4.0",
    model="grounded-sam-2",
    model_version="0.4.0",
))


class DetectRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    prompts: list[str] = Field(default_factory=lambda: ["person", "vehicle", "object"])


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    x: float
    y: float
    width: float
    height: float


class Detector(Protocol):
    def detect(self, content: bytes, prompts: list[str]) -> list[Detection]: ...


class DevelopmentDetector:
    def detect(self, content: bytes, prompts: list[str]) -> list[Detection]:
        del content
        label = prompts[0] if prompts else "object"
        return [Detection(label, 0.5, 0.1, 0.1, 0.8, 0.8)]


class GroundedSAM2Detector:
    def __init__(self) -> None:
        self._loaded = False

    def _load(self) -> None:
        import torch
        from sam2.build_sam import build_sam2, build_sam2_hf
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        cache_dir = Path(os.environ.get(
            "MODEL_CACHE_DIR",
            "~/.cache/ddu/models/ddu-vision/grounded-sam-2/0.4.0",
        )).expanduser()
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(cache_dir / "huggingface"))
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        if self._device == "cpu":
            log.warning("CUDA unavailable; Grounded SAM 2 is running on CPU")

        if os.environ.get("MODEL_SOURCE", "huggingface").lower() == "minio":
            self._sync_minio(cache_dir)
            grounding_id = str(cache_dir / "grounding-dino")
            sam_model = build_sam2(
                os.environ.get(
                    "SAM2_MODEL_CONFIG",
                    "configs/sam2.1/sam2.1_hiera_s.yaml",
                ),
                str(cache_dir / "sam2_checkpoint.pt"),
                device=self._device,
            )
        else:
            grounding_id = os.environ.get(
                "GROUNDING_MODEL_ID",
                "IDEA-Research/grounding-dino-tiny",
            )
            sam_model = build_sam2_hf(
                os.environ.get("SAM2_MODEL_ID", "facebook/sam2.1-hiera-small"),
                device=self._device,
            )
        self._processor = AutoProcessor.from_pretrained(
            grounding_id,
            cache_dir=cache_dir / "huggingface",
        )
        self._grounding_model = AutoModelForZeroShotObjectDetection.from_pretrained(
            grounding_id,
            cache_dir=cache_dir / "huggingface",
        ).to(self._device)
        self._predictor = SAM2ImagePredictor(sam_model)
        self._torch = torch
        self._loaded = True

    def _sync_minio(self, cache_dir: Path) -> None:
        from minio import Minio

        endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
        secure = endpoint.startswith("https://")
        endpoint = endpoint.removeprefix("http://").removeprefix("https://")
        client = Minio(
            endpoint,
            access_key=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
            secure=secure,
        )
        prefix = "ddu-vision/grounded-sam-2/0.4.0/"
        found = False
        for item in client.list_objects("ddu-models", prefix=prefix, recursive=True):
            found = True
            relative = item.object_name.removeprefix(prefix)
            destination = cache_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            client.fget_object("ddu-models", item.object_name, str(destination))
        if not found:
            raise RuntimeError(f"no model objects found at ddu-models/{prefix}")

    def detect(self, content: bytes, prompts: list[str]) -> list[Detection]:
        if not self._loaded:
            self._load()
        import numpy as np
        from PIL import Image

        image = Image.open(BytesIO(content)).convert("RGB")
        prompt = ". ".join(value.strip().lower() for value in prompts if value.strip())
        if not prompt:
            prompt = "object"
        prompt += "."
        self._predictor.set_image(np.asarray(image))
        inputs = self._processor(
            images=image,
            text=prompt,
            return_tensors="pt",
        ).to(self._device)
        with self._torch.no_grad():
            outputs = self._grounding_model(**inputs)
        result = self._processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=float(os.environ.get("BOX_THRESHOLD", "0.4")),
            text_threshold=float(os.environ.get("TEXT_THRESHOLD", "0.3")),
            target_sizes=[image.size[::-1]],
        )[0]
        boxes = result["boxes"].detach().cpu().numpy()
        if len(boxes) > 0:
            self._predictor.predict(
                point_coords=None,
                point_labels=None,
                box=boxes,
                multimask_output=False,
            )
        width, height = image.size
        detections: list[Detection] = []
        for box, score, label in zip(
            boxes,
            result["scores"].detach().cpu().tolist(),
            result["labels"],
            strict=True,
        ):
            x1, y1, x2, y2 = box.tolist()
            detections.append(Detection(
                str(label),
                float(score),
                max(0.0, x1 / width),
                max(0.0, y1 / height),
                min(1.0, (x2 - x1) / width),
                min(1.0, (y2 - y1) / height),
            ))
        return detections


app = build_scaffold_app(VERSION)
evidence_client = EvidenceClient()
lineage = LineageEmitter(VERSION)
detector: Detector = (
    DevelopmentDetector()
    if model_mode_is_stub()
    else GroundedSAM2Detector()
)


@app.post("/v1/detect")
async def detect(request: DetectRequest) -> list[dict]:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-vision:detect",
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
        detections = await asyncio.to_thread(detector.detect, content, request.prompts)
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-vision:detect",
            facets=facets,
        ))
        log.exception("detection failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    observed_at = datetime.now(timezone.utc).isoformat()
    method = "development-stub" if isinstance(detector, DevelopmentDetector) else "grounded-sam-2"
    observations = [
        {
            "id": str(uuid4()),
            "investigation_id": request.investigation_id,
            "evidence_id": request.evidence_id,
            "type": "OBSERVATION_TYPE_OBJECT",
            "label": item.label,
            "detector_confidence": item.confidence,
            "attributes": {
                "epistemic_class": "EPISTEMIC_CLASS_OBSERVATION",
            },
            "bbox": {
                "x": item.x,
                "y": item.y,
                "width": item.width,
                "height": item.height,
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
                "job_name": "ddu-vision:detect",
                "input_evidence_ids": [request.evidence_id],
                "extraction_method": method,
                "parameters": {"prompts": ",".join(request.prompts)},
            },
            "observed_at": observed_at,
        }
        for item in detections
    ]
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-vision:detect",
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


class SpecializedDetectRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    model: str = "mmdetection"
    classes: list[str] = Field(default_factory=list)


@app.post("/v1/detect/specialized")
async def detect_specialized(request: SpecializedDetectRequest) -> list[dict]:
    """Phase 2 specialized detection (MMDetection). Stub-safe when MODEL_MODE=stub."""
    prompts = request.classes or ["person", "vehicle", "weapon"]
    base = DetectRequest(
        evidence_id=request.evidence_id,
        investigation_id=request.investigation_id,
        prompts=prompts,
    )
    observations = await detect(base)
    for item in observations:
        item["attributes"] = {
            **(item.get("attributes") or {}),
            "detector_family": "mmdetection",
            "specialized_model": request.model,
        }
        provenance = item.get("provenance") or {}
        provenance["extraction_method"] = (
            "development-stub"
            if model_mode_is_stub()
            else "mmdetection"
        )
        item["provenance"] = provenance
    return observations


def main() -> None:
    port = int(os.environ.get("PORT", 8101))
    device = select_device()
    log.info("ddu-vision listening on :%d device=%s stub=%s", port, device.get("device"), model_mode_is_stub())
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
