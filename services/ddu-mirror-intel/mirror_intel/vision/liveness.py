"""Server-side liveness + biometric skip state.

The challenge itself runs in the browser (MediaPipe FaceMesh). The server
only tracks: challenge issued → one verified frame accepted → template TTL,
or an explicit skip that clears dangling face state (DoD).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any


CHALLENGES = ("blink", "turn_left", "turn_right")
TEMPLATE_TTL_SECONDS = 120


@dataclass
class LivenessState:
    challenge_id: str | None = None
    challenge: str | None = None
    issued_at: float | None = None
    passed: bool = False
    skipped: bool = False
    frame_sha256: str | None = None
    template_expires_at: float | None = None
    consent_logged: bool = False

    def public(self) -> dict[str, Any]:
        now = time.time()
        remaining = None
        if self.template_expires_at:
            remaining = max(0, int(self.template_expires_at - now))
        return {
            "challenge_id": self.challenge_id,
            "challenge": self.challenge,
            "passed": self.passed,
            "skipped": self.skipped,
            "template_ttl_seconds_remaining": remaining,
            "has_frame": bool(self.frame_sha256),
            "consent_logged": self.consent_logged,
        }


@dataclass
class LivenessStore:
    """In-process map session_id → liveness state.

    Session wipe / skip clears entries so nothing dangles (DoD).
    """

    _by_session: dict[str, LivenessState] = field(default_factory=dict)

    def get(self, session_id: str) -> LivenessState:
        state = self._by_session.get(session_id)
        if state is None:
            state = LivenessState()
            self._by_session[session_id] = state
        if (
            state.template_expires_at
            and state.template_expires_at < time.time()
            and state.passed
        ):
            # Ephemeral face template destroyed.
            state.frame_sha256 = None
            state.passed = False
            state.template_expires_at = None
        return state

    def start(self, session_id: str, challenge: str | None = None) -> LivenessState:
        state = LivenessState(
            challenge_id=f"lv_{secrets.token_hex(4)}",
            challenge=challenge or secrets.choice(CHALLENGES),
            issued_at=time.time(),
            passed=False,
            skipped=False,
            consent_logged=True,
        )
        self._by_session[session_id] = state
        return state

    def complete(
        self,
        session_id: str,
        *,
        challenge_id: str,
        frame_sha256: str,
        client_passed: bool,
    ) -> LivenessState:
        state = self.get(session_id)
        if state.skipped:
            raise ValueError("face path was skipped — no liveness to complete")
        if not state.challenge_id or state.challenge_id != challenge_id:
            raise ValueError("challenge_id mismatch or no challenge in flight")
        if not client_passed:
            # Failed challenge — clear frame, keep challenge so UI can retry.
            state.passed = False
            state.frame_sha256 = None
            state.template_expires_at = None
            return state
        # Only one verified frame is retained.
        state.passed = True
        state.frame_sha256 = frame_sha256
        state.template_expires_at = time.time() + TEMPLATE_TTL_SECONDS
        return state

    def skip(self, session_id: str) -> LivenessState:
        """Skip-face path — fully functional, no dangling biometric state."""
        state = LivenessState(skipped=True, consent_logged=True)
        self._by_session[session_id] = state
        return state

    def clear(self, session_id: str) -> None:
        self._by_session.pop(session_id, None)


# Process-wide store; session wipe calls clear().
liveness_store = LivenessStore()
