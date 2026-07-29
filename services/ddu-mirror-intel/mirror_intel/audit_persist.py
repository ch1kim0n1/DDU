"""Append-only action log persistence for compliance audits.

File-backed by default; Redis list when ``MIRROR_REDIS_URL`` is set.
Never update or delete entries — only append / read.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("ddu-mirror-intel.audit")

_lock = threading.Lock()


class AuditPersist(Protocol):
    def append(self, session_id: str, entry: dict[str, Any]) -> None: ...

    def read(self, session_id: str) -> list[dict[str, Any]]: ...


class FileAuditPersist:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(os.environ.get("MIRROR_AUDIT_LOG_DIR", "logs/actions"))
        self._root.mkdir(parents=True, exist_ok=True)

    def append(self, session_id: str, entry: dict[str, Any]) -> None:
        path = self._root / f"{session_id}.jsonl"
        line = json.dumps(entry, separators=(",", ":"), sort_keys=True)
        with _lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def read(self, session_id: str) -> list[dict[str, Any]]:
        path = self._root / f"{session_id}.jsonl"
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("corrupt audit line in %s", path)
        return entries


class RedisAuditPersist:
    """Append-only Redis list: LPUSH audit:{session_id} {json}."""

    def __init__(self, redis_url: str, ttl_seconds: int | None = None) -> None:
        from redis import ConnectionPool, Redis

        self._ttl = int(
            ttl_seconds
            if ttl_seconds is not None
            else os.environ.get("MIRROR_SESSION_TTL_SECONDS", "1800")
        )
        pool = ConnectionPool.from_url(redis_url, max_connections=20)
        self._client = Redis(connection_pool=pool, decode_responses=True)

    def _key(self, session_id: str) -> str:
        return f"audit:{session_id}"

    def append(self, session_id: str, entry: dict[str, Any]) -> None:
        key = self._key(session_id)
        line = json.dumps(entry, separators=(",", ":"), sort_keys=True)
        self._client.lpush(key, line)
        if self._ttl > 0:
            self._client.expire(key, self._ttl)

    def read(self, session_id: str) -> list[dict[str, Any]]:
        key = self._key(session_id)
        # LPUSH stores newest first; reverse for chronological order.
        raw = self._client.lrange(key, 0, -1) or []
        entries: list[dict[str, Any]] = []
        for line in reversed(raw):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("corrupt audit entry for %s", session_id)
        return entries


def build_audit_persist() -> AuditPersist:
    redis_url = os.environ.get("MIRROR_REDIS_URL", "").strip()
    if redis_url:
        try:
            backend = RedisAuditPersist(redis_url)
            log.info("audit_persist: redis")
            return backend
        except Exception as exc:  # noqa: BLE001
            log.warning("audit_persist redis unavailable (%s); using file", exc)
    log.info("audit_persist: file")
    return FileAuditPersist()


_default: AuditPersist | None = None


def get_audit_persist() -> AuditPersist:
    global _default
    if _default is None:
        _default = build_audit_persist()
    return _default


def append_action(session_id: str, entry: dict[str, Any]) -> None:
    """Append one action-log entry. Never rewrite or delete."""
    get_audit_persist().append(session_id, entry)


def read_audit_log(session_id: str) -> list[dict[str, Any]]:
    return get_audit_persist().read(session_id)
