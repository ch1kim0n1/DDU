"""HTTP client for retrieving immutable evidence through service contracts."""
from __future__ import annotations

import os

import httpx


class EvidenceClient:
    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (
            base_url
            or os.environ.get("DDU_STORAGE_URL", "")
            or "http://localhost:8003"
        ).rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=60.0)

    async def fetch(
        self,
        evidence_id: str,
        investigation_id: str,
    ) -> tuple[bytes, dict]:
        metadata_response = await self._client.get(
            f"{self._base_url}/v1/evidence/{evidence_id}",
            params={"investigation_id": investigation_id},
            headers={"X-Investigation-Id": investigation_id},
        )
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        download_url = metadata.get("download_url")
        if not download_url:
            raise RuntimeError("storage response did not include download_url")
        content_response = await self._client.get(str(download_url))
        content_response.raise_for_status()
        return content_response.content, metadata
