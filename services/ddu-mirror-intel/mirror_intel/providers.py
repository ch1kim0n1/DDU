"""Deployment readiness for optional external providers."""

from __future__ import annotations

import os
import shutil
from typing import Any

from .llm import get_llm


def truthy(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def provider_status() -> dict[str, Any]:
    eleven_key = bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())
    eleven_voice = bool(os.environ.get("ELEVENLABS_VOICE_ID", "").strip())
    providers = {
        "hibp": {
            "configured": bool(os.environ.get("HIBP_API_KEY", "").strip()),
            "fallback": "labelled-cache",
        },
        "sherlock": {
            "configured": (
                shutil.which("sherlock") is not None
                and truthy("MIRROR_SHERLOCK_LIVE")
            ),
            "fallback": "labelled-cache",
        },
        "elevenlabs_stt": {
            "configured": eleven_key,
            "fallback": "typed-input",
        },
        "elevenlabs_tts": {
            "configured": eleven_key and eleven_voice,
            "fallback": "browser-speech-synthesis",
        },
        "llm": {
            "configured": get_llm().provider.name != "offline",
            "provider": get_llm().provider.name,
            "fallback": "deterministic-local",
        },
    }
    require_live = truthy("MIRROR_REQUIRE_LIVE_PROVIDERS")
    require_voice = truthy("MIRROR_REQUIRE_ELEVENLABS")
    missing: list[str] = []
    if require_live:
        missing.extend(
            name for name in ("hibp", "sherlock") if not providers[name]["configured"]
        )
    if require_voice:
        missing.extend(
            name
            for name in ("elevenlabs_stt", "elevenlabs_tts")
            if not providers[name]["configured"]
        )
    return {
        "providers": providers,
        "require_live_providers": require_live,
        "require_elevenlabs": require_voice,
        "ready": not missing,
        "missing_required": missing,
    }
