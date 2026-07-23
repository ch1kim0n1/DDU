"""Whisper audio transcription service."""
from __future__ import annotations

import asyncio
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
log = logging.getLogger("ddu-audio")

VERSION = from_env(ServiceVersion(
    service="ddu-audio",
    service_version="0.0.1-dev",
    tool="whisper",
    tool_version="3.0.0",
    model="whisper",
    model_version=os.environ.get("WHISPER_MODEL", "base"),
))


class TranscribeRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    language: str | None = None


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    confidence: float
    start_ms: int
    end_ms: int


class AudioAdapter(Protocol):
    def transcribe(self, content: bytes, language: str | None) -> list[TranscriptSegment]: ...


class DevelopmentAudio:
    def transcribe(self, content: bytes, language: str | None) -> list[TranscriptSegment]:
        del content, language
        return [TranscriptSegment("development audio transcript", 0.5, 0, 1500)]


class WhisperAdapter:
    def __init__(self) -> None:
        self._model = None

    def _load(self) -> None:
        import whisper

        model_name = os.environ.get("WHISPER_MODEL", "base")
        self._model = whisper.load_model(model_name)

    def transcribe(self, content: bytes, language: str | None) -> list[TranscriptSegment]:
        if self._model is None:
            self._load()
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".bin") as handle:
            handle.write(content)
            handle.flush()
            result = self._model.transcribe(handle.name, language=language)
        segments: list[TranscriptSegment] = []
        for item in result.get("segments", []) or []:
            segments.append(TranscriptSegment(
                str(item.get("text", "")).strip(),
                float(item.get("avg_logprob", -1.0) + 1.0) if item.get("avg_logprob") is not None else 0.5,
                int(float(item.get("start", 0)) * 1000),
                int(float(item.get("end", 0)) * 1000),
            ))
        if not segments and result.get("text"):
            segments.append(TranscriptSegment(str(result["text"]).strip(), 0.5, 0, 0))
        return segments


app = build_scaffold_app(VERSION)
evidence_client = EvidenceClient()
lineage = LineageEmitter(VERSION)
audio_adapter: AudioAdapter = (
    DevelopmentAudio()
    if model_mode_is_stub()
    else WhisperAdapter()
)


@app.post("/v1/transcribe")
async def transcribe(request: TranscribeRequest) -> list[dict]:
    run_id = lineage.new_run_id()
    facets = {"dduInvestigation": {"investigation_id": request.investigation_id}}
    lineage.emit(Event(
        event_type="START",
        run_id=run_id,
        job_name="ddu-audio:transcribe",
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
        segments = await asyncio.to_thread(audio_adapter.transcribe, content, request.language)
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, ImportError) as exc:
        lineage.emit(Event(
            event_type="FAIL",
            run_id=run_id,
            job_name="ddu-audio:transcribe",
            facets=facets,
        ))
        log.exception("audio transcription failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    observed_at = datetime.now(timezone.utc).isoformat()
    method = "development-stub" if isinstance(audio_adapter, DevelopmentAudio) else "whisper"
    observations = []
    for item in segments:
        observations.append({
            "id": str(uuid4()),
            "investigation_id": request.investigation_id,
            "evidence_id": request.evidence_id,
            "type": "OBSERVATION_TYPE_AUDIO_TRANSCRIPT",
            "label": item.text,
            "detector_confidence": item.confidence,
            "attributes": {
                "start_ms": str(item.start_ms),
                "end_ms": str(item.end_ms),
                "language": request.language or "",
                "epistemic_class": "EPISTEMIC_CLASS_OBSERVATION",
            },
            "text": {"text": item.text, "language": request.language or ""},
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
                "job_name": "ddu-audio:transcribe",
                "input_evidence_ids": [request.evidence_id],
                "extraction_method": method,
                "parameters": {"language": request.language or ""},
            },
            "observed_at": observed_at,
        })
    lineage.emit(Event(
        event_type="COMPLETE",
        run_id=run_id,
        job_name="ddu-audio:transcribe",
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
    port = int(os.environ.get("PORT", 8104))
    log.info("ddu-audio listening on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
