# Third-Party Notices

DDU incorporates or depends on the following open-source components. Tier 1
components run as separate processes/containers and are not linked into DDU
binaries. Tier 2/3 components are wrapped or imported behind DDU service
contracts.

## Tier 1 (external services)

| Component | License | Notes |
|-----------|---------|-------|
| Neo4j Community | GPLv3 | Graph store backend via `ddu-graph-store` |
| MinIO | AGPLv3 | Object storage via `ddu-storage` / `ddu-evidence` |
| Qdrant | Apache-2.0 | Vector store via `ddu-vector` |
| Marquez / OpenLineage | Apache-2.0 | Lineage backend via `ddu-lineage` |
| SpiderFoot | MIT | OSINT backend via `ddu-osint` |
| CompreFace | Apache-2.0 | Face recognition via `ddu-face` |
| Browsertrix | AGPLv3 | Web capture via `ddu-webcapture` |
| PostgreSQL | PostgreSQL License | Supporting datastores for Marquez/CompreFace |

## Tier 2 / 3 (wrapped inference & libraries)

| Component | License | Used by |
|-----------|---------|---------|
| Grounded SAM 2 | Apache-2.0 | `ddu-vision` |
| MMDetection | Apache-2.0 | `ddu-vision` specialized detect |
| PaddleOCR / PaddlePaddle | Apache-2.0 | `ddu-ocr` |
| GeoCLIP | MIT | `ddu-geo` |
| Whisper | MIT | `ddu-audio` |
| Sherlock | MIT | `ddu-discovery` |
| gallery-dl | GPL-2.0 | `ddu-collector` (subprocess) |
| LangGraph | MIT | `ddu-agent` |
| Splink | MIT | `ddu-resolution` |
| Graphiti | Apache-2.0 | `ddu-temporal` |
| Cytoscape.js | MIT | `ddu-ui` |
| MapLibre GL JS | BSD-3-Clause | `ddu-ui` |
| chi | MIT | `ddu-api` |
| FastAPI / Uvicorn | MIT | Python services |
| httpx | BSD-3-Clause | Python HTTP clients |

## Policy

- AGPLv3 and GPLv3 components remain **Tier 1 process boundaries** only.
- DDU does not copy source from `open-source/` reference clones into runtime code.
- Model weights are pinned and reported via `/versionz` and lineage events.
