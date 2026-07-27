"""PII-disciplined voice turns for DDU Mirror.

The boundary is intentionally explicit:

1. ElevenLabs receives the user-approved audio clip for transcription.
2. The transcript is scrubbed locally with ``redaction.scrub_text``.
3. Only the scrubbed transcript and de-identified finding structs reach the LLM.
4. The answer is scrubbed again before ElevenLabs text-to-speech.

Raw transcripts are never returned to the browser, written to the action log,
or placed in an LLM prompt. Rejected and contradicted findings are excluded
before narration or question answering, so the voice layer follows the same
live graph the score and 3D scene use.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from .llm import Tier, get_llm
from .redaction import assert_no_raw_pii, redact_findings, scrub_text
from .schema import Finding, SCORING_STATES
from .session import Session

ELEVENLABS_API = "https://api.elevenlabs.io/v1"
ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
}


class VoiceConfigurationError(RuntimeError):
    """Raised when a requested vendor capability has no configured credential."""


@dataclass
class VoiceAnswer:
    transcript: str
    transcript_redacted: bool
    replacements: dict[str, int]
    answer: str
    audio_base64: str | None
    audio_mime: str | None
    stt_provider: str
    tts_provider: str
    llm_provider: str
    offline: bool
    grounded_finding_ids: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "transcript": self.transcript,
            "transcript_redacted": self.transcript_redacted,
            "replacements": self.replacements,
            "answer": self.answer,
            "audio_base64": self.audio_base64,
            "audio_mime": self.audio_mime,
            "stt_provider": self.stt_provider,
            "tts_provider": self.tts_provider,
            "llm_provider": self.llm_provider,
            "offline": self.offline,
            "grounded_finding_ids": self.grounded_finding_ids,
        }


def _active_findings(session: Session) -> list[Finding]:
    return [
        finding
        for finding in session.findings
        if finding.verification_state in SCORING_STATES
    ]


def _session_terms(session: Session) -> list[str]:
    identity = session.identity
    return [
        *identity.emails,
        *identity.handles,
        *identity.account_urls,
    ]


def severity_narration(session: Session, limit: int = 5) -> tuple[str, list[str]]:
    """Deterministic narration over the live, non-rejected severity list."""
    active = sorted(
        _active_findings(session),
        key=lambda finding: (finding.severity_score, finding.confidence),
        reverse=True,
    )
    top = [finding for finding in active if finding.type.value != "seed_identity"][:limit]
    if not top:
        return (
            "There are no active exposure findings to narrate. Rejected and "
            "contradicted nodes are excluded.",
            [],
        )

    opening = (
        f"Your current exposure score is {session.score.score if session.score else 0} "
        f"out of 100. I am reading {len(top)} active findings from highest severity down."
    )
    items = []
    for index, finding in enumerate(top, start=1):
        permanence = (
            "It cannot be undone, so use the compensating control."
            if not finding.reversible
            else f"It is reversible with {finding.remediation.effort.value} effort."
        )
        items.append(
            f"Number {index}: {finding.severity.value}, {finding.label}. {permanence}"
        )
    return " ".join([opening, *items]), [finding.id for finding in top]


def _local_grounded_answer(
    session: Session, question: str, active: list[Finding]
) -> tuple[str, list[str]]:
    ranked = sorted(active, key=lambda finding: finding.severity_score, reverse=True)
    ranked = [finding for finding in ranked if finding.type.value != "seed_identity"]
    top = ranked[:3]
    lowered = question.lower()

    if not top:
        return (
            "There are no active findings in the graph. Rejected and contradicted "
            "nodes are not included in this answer.",
            [],
        )

    if any(word in lowered for word in ("fix", "first", "priority", "remed")):
        reversible = next((finding for finding in top if finding.reversible), None)
        target = reversible or top[0]
        prefix = (
            f"Start with {target.label}. "
            if target.reversible
            else f"The highest driver is {target.label}, but it is permanent. "
        )
        guidance = (
            target.remediation.action
            if target.reversible
            else target.remediation.compensating or target.remediation.action
        )
        return prefix + guidance, [target.id]

    if any(word in lowered for word in ("permanent", "irreversible", "undo")):
        permanent = [finding for finding in ranked if not finding.reversible][:3]
        if not permanent:
            return "None of the current active findings are classified as permanent.", []
        labels = ", ".join(finding.label for finding in permanent)
        return (
            f"The permanent exposures are {labels}. They remain in the score even "
            "after every reversible item is simulated as fixed.",
            [finding.id for finding in permanent],
        )

    labels = "; ".join(
        f"{finding.label}, {finding.severity.value}" for finding in top
    )
    return (
        f"The live graph has {len(ranked)} contributing findings. The leading "
        f"drivers are {labels}. I excluded every rejected or contradicted node.",
        [finding.id for finding in top],
    )


async def transcribe(audio: bytes, mime_type: str) -> str:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise VoiceConfigurationError(
            "ELEVENLABS_API_KEY is not configured; type a question or add the key "
            "to enable speech-to-text."
        )
    normalized_mime = (mime_type or "audio/webm").split(";", 1)[0].strip().lower()
    if normalized_mime not in ALLOWED_AUDIO_TYPES:
        raise ValueError(f"unsupported audio type {normalized_mime!r}")
    max_bytes = int(os.environ.get("MIRROR_VOICE_MAX_AUDIO_BYTES", "8388608"))
    if not audio or len(audio) > max_bytes:
        raise ValueError(f"audio must be between 1 and {max_bytes} bytes")
    model_id = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2")
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            f"{ELEVENLABS_API}/speech-to-text",
            headers={"xi-api-key": api_key},
            data={"model_id": model_id},
            files={"file": ("mirror-turn", audio, normalized_mime)},
        )
        response.raise_for_status()
        payload = response.json()
    return str(payload.get("text", "")).strip()


async def synthesize(text: str) -> tuple[str | None, str | None, str]:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if not api_key or not voice_id:
        return None, None, "browser"

    safe = scrub_text(text).text
    assert_no_raw_pii(safe, context="elevenlabs:tts")
    model_id = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            f"{ELEVENLABS_API}/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            params={"output_format": "mp3_44100_128"},
            json={"text": safe, "model_id": model_id},
        )
        response.raise_for_status()
    return base64.b64encode(response.content).decode("ascii"), "audio/mpeg", "elevenlabs"


async def answer_turn(
    session: Session,
    *,
    transcript: str | None = None,
    audio_base64: str | None = None,
    mime_type: str = "audio/webm",
    mode: str = "question",
) -> VoiceAnswer:
    stt_provider = "text"
    raw_transcript = transcript or ""
    if audio_base64:
        try:
            audio = base64.b64decode(audio_base64, validate=True)
        except ValueError as exc:
            raise ValueError("audio_base64 is not valid base64") from exc
        raw_transcript = await transcribe(audio, mime_type)
        stt_provider = "elevenlabs"
    elif mode == "narrate":
        stt_provider = "none"

    scrubbed = scrub_text(raw_transcript, extra_terms=_session_terms(session))
    active = _active_findings(session)

    if mode == "narrate":
        answer, grounded = severity_narration(session)
        provider = "local"
        offline = True
    else:
        local_answer, grounded = _local_grounded_answer(session, scrubbed.text, active)
        llm = get_llm()
        payload = {
            "question": scrubbed.text,
            "score": session.score.model_dump(mode="json") if session.score else {},
            "findings": redact_findings(active),
        }
        completion = llm.complete(
            [
                {
                    "role": "user",
                    "content": json.dumps(payload, separators=(",", ":"), default=str),
                }
            ],
            Tier.VOICE,
            system=(
                "You are DDU Mirror's defensive voice guide. Answer only from the "
                "provided de-identified score and findings. Never invent evidence, "
                "never mention suppressed findings, and be concise. When a finding "
                "is irreversible, recommend only its compensating control."
            ),
            max_tokens=300,
        )
        provider = completion.provider
        offline = completion.offline
        answer = (
            local_answer
            if completion.offline or completion.refused or not completion.text.strip()
            else completion.text.strip()
        )

    answer = scrub_text(answer, extra_terms=_session_terms(session)).text
    audio, audio_mime, tts_provider = await synthesize(answer)
    return VoiceAnswer(
        transcript=scrubbed.text,
        transcript_redacted=scrubbed.changed,
        replacements=scrubbed.replacements,
        answer=answer,
        audio_base64=audio,
        audio_mime=audio_mime,
        stt_provider=stt_provider,
        tts_provider=tts_provider,
        llm_provider=provider,
        offline=offline,
        grounded_finding_ids=grounded,
    )
