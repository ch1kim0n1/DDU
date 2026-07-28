"""FastAPI scaffold builder for DDU Python services.

Provides /healthz, /versionz, and a root info endpoint. Services extend
the returned app with their own routes.
"""

from __future__ import annotations

from fastapi import FastAPI

from ddu_common.version import ServiceVersion


def build_scaffold_app(version: ServiceVersion) -> FastAPI:
    app = FastAPI(
        title=version.service,
        version=version.service_version,
        docs_url="/docs",
        redoc_url=None,
    )

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"state": "HEALTHY", "service": version.service}

    @app.get("/versionz")
    async def versionz() -> dict:
        return version.as_dict()

    @app.get("/")
    async def root() -> dict:
        return {
            "service": version.service,
            "version": version.service_version,
            "status": "scaffold",
            "endpoints": ["GET /healthz", "GET /versionz"],
        }

    return app
