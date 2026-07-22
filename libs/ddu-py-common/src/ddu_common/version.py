"""Service version model. Reported at /versionz and embedded in lineage events."""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict


@dataclass
class ServiceVersion:
    service: str
    service_version: str
    tool: str = ""
    tool_version: str = ""
    model: str = ""
    model_version: str = ""
    git_commit: str = "unknown"
    built_at: str = "unknown"

    def as_dict(self) -> dict:
        return asdict(self)


def from_env(default: ServiceVersion) -> ServiceVersion:
    """Override fields from DDU_* env vars. Useful in containers."""
    return ServiceVersion(
        service=default.service,
        service_version=os.environ.get("DDU_SERVICE_VERSION", default.service_version),
        tool=os.environ.get("DDU_TOOL", default.tool),
        tool_version=os.environ.get("DDU_TOOL_VERSION", default.tool_version),
        model=os.environ.get("DDU_MODEL", default.model),
        model_version=os.environ.get("DDU_MODEL_VERSION", default.model_version),
        git_commit=os.environ.get("DDU_GIT_COMMIT", default.git_commit),
        built_at=os.environ.get("DDU_BUILT_AT", default.built_at),
    )
