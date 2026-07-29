"""Deployment environment helpers for ddu-mirror-intel."""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("ddu-mirror-intel.env")


def mirror_env() -> str:
    return os.environ.get("MIRROR_ENV", "development").strip().lower() or "development"


def is_production() -> bool:
    return mirror_env() == "production"


def is_staging() -> bool:
    return mirror_env() == "staging"


def enforce_production_boot() -> None:
    """Fail closed when production is misconfigured."""
    if not is_production():
        return
    os.environ.setdefault("MIRROR_IDENTITY_REQUIRED", "1")
    missing: list[str] = []
    if not os.environ.get("MIRROR_REDIS_URL"):
        missing.append("MIRROR_REDIS_URL")
    if not os.environ.get("MIRROR_SESSION_ENCRYPTION_KEY"):
        missing.append("MIRROR_SESSION_ENCRYPTION_KEY")
    if os.environ.get("MIRROR_IDENTITY_REQUIRED", "1").lower() not in {"1", "true", "yes", "on"}:
        missing.append("MIRROR_IDENTITY_REQUIRED=1")
    if missing:
        log.error("production boot refused; missing %s", ", ".join(missing))
        sys.exit(2)
    if os.path.exists(".env") or os.path.exists("services/ddu-mirror-intel/.env"):
        log.warning(
            "production mode detected a local .env file; prefer a secrets manager "
            "(Doppler / AWS Secrets Manager) for production credentials"
        )


def refuse_dev_session_features(*, seed_mock: bool, session_id: str | None) -> str | None:
    """Return an error detail if production forbids the request shape."""
    if not is_production():
        return None
    if seed_mock:
        return "mock findings cannot be seeded in production"
    if session_id and session_id.startswith("sess_dev_"):
        return "development session ids are not allowed in production"
    return None
