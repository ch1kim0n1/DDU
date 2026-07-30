"""Append-only action log.

Track 3 asks for "a simple action log". The cheap version records what the AI
did. This one records what the AI *proposed*, what the human *decided*, and
what the system *refused* — because a log that only contains successes can't
answer the question a reviewer actually has, which is "who authorized this?"

Properties that make it worth trusting:

* **Append-only in the API, not just by convention.** There is no update or
  delete method. ``entries`` returns copies.
* **Monotonic sequence numbers**, so a gap is detectable.
* **Refusals are first-class.** A blocked scan of an unverified target is a
  log entry, not a silent 403 in a webserver log nobody reads.
* **Redacted at write time.** Log lines are a classic leak path — someone
  logs the target for debugging and the value outlives the ephemeral session
  it was supposed to die with.
"""

from __future__ import annotations

import threading
from typing import Any, Iterator

from .redaction import scrub_text
from .schema import ActionLogEntry, Origin

#: Actions worth recording. A closed vocabulary keeps the log greppable and
#: makes an omission obvious in review.
PROPOSED = "agent.proposed"
APPROVED = "human.approved"
EDITED = "human.edited"
REJECTED_PROPOSAL = "human.rejected_proposal"
CANCELLED = "human.cancelled_scan"
EXECUTED = "agent.executed"
FAILED = "agent.failed"
FINDING_ADDED = "agent.finding_added"
FINDING_REJECTED = "human.rejected_finding"
FINDING_RESTORED = "human.restored_finding"
FINDING_EDITED = "human.edited_finding"
MARKED_FIXED = "human.marked_fixed"
FIX_REFUSED = "system.fix_refused"
TARGET_REFUSED = "system.target_refused"
INJECTION_QUARANTINED = "system.injection_quarantined"
PERSONA_CHANGED = "human.changed_persona"
SESSION_WIPED = "system.session_wiped"
REVEAL = "human.revealed_value"

#: Voice layer. The voice agent is a user-facing AI action, so a session where
#: someone asked it six questions should not read as a session where nothing
#: happened. VOICE_SCRUBBED is the one that earns its place in the pitch: it is
#: proof the STT → our-scrub → LLM interception point actually fired, rather
#: than a claim on a slide.
VOICE_TURN = "human.voice_turn"
VOICE_ANSWERED = "agent.voice_answered"
VOICE_SCRUBBED = "system.voice_pii_scrubbed"


class ActionLog:
    """Session-scoped, append-only, thread-safe."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._entries: list[ActionLogEntry] = []
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        actor: Origin = Origin.AGENT,
        subject: str = "",
        detail: str = "",
        **metadata: Any,
    ) -> ActionLogEntry:
        # Scrub here rather than at the call site. Call sites forget; a choke
        # point doesn't.
        entry = ActionLogEntry(
            seq=len(self._entries) + 1,
            session_id=self.session_id,
            actor=actor,
            action=action,
            subject=subject,
            detail=scrub_text(detail).text,
            metadata=metadata,
        )
        with self._lock:
            entry.seq = len(self._entries) + 1
            self._entries.append(entry)
        return entry

    def restore(self, entries: list[ActionLogEntry | dict[str, Any]]) -> None:
        """Hydrate entries loaded from the encrypted session backend.

        This is intentionally not exposed by the HTTP API; it exists only so
        a different worker can continue the same append-only sequence.
        """
        restored = [
            entry if isinstance(entry, ActionLogEntry) else ActionLogEntry.model_validate(entry)
            for entry in entries
        ]
        for expected, entry in enumerate(restored, start=1):
            if entry.session_id != self.session_id or entry.seq != expected:
                raise ValueError("invalid persisted action-log sequence")
        with self._lock:
            self._entries = restored

    def entries(self, since: int = 0, limit: int | None = None) -> list[ActionLogEntry]:
        with self._lock:
            window = self._entries[since:]
        return window[:limit] if limit else list(window)

    def tail(self, count: int = 20) -> list[ActionLogEntry]:
        with self._lock:
            return list(self._entries[-count:])

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[ActionLogEntry]:
        return iter(self.entries())

    def summary(self) -> dict[str, Any]:
        """Counts by action — the "what happened in this session" header.

        Surfacing the human-decision counts separately is the point: a session
        showing 6 proposals and 6 approvals reads very differently from one
        showing 6 proposals, 4 approvals, and 2 rejections, and the second is
        the one that demonstrates the human was actually in the loop.
        """
        counts: dict[str, int] = {}
        for entry in self.entries():
            counts[entry.action] = counts.get(entry.action, 0) + 1
        human = sum(v for k, v in counts.items() if k.startswith("human."))
        return {
            "total": len(self),
            "by_action": counts,
            "human_decisions": human,
            "refusals": counts.get(TARGET_REFUSED, 0) + counts.get(FIX_REFUSED, 0),
            "quarantined": counts.get(INJECTION_QUARANTINED, 0),
        }
