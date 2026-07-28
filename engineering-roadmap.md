# DDU Engineering Roadmap

Companion to `main-pdd.md`. Defines how DDU is built: integration strategy, service boundaries, OSS usage, phases, and per-repo integration contracts.

---

# 1. Core Engineering Principle

**DDU owns the intelligence lifecycle. OSS projects own their capability.**

Every open-source project is an *implementation* of a DDU-defined internal contract. The contract is stable; the implementation is replaceable. The boundary is a service interface plus OpenLineage events.

DDU's proprietary moat is the **Intelligence Correlation Engine**, the **ontology/evidence model**, and **agent orchestration** — not reimplementing detection, OCR, ASR, face matching, or graph storage.

---

# 2. What We Never Do

- **No Frankenstein.** Never copy source from upstream repos into DDU code.
- **No vendoring of internals.** Never fork-and-modify an OSS project's core logic inside DDU.
- **No direct coupling to upstream APIs in DDU core.** DDU core talks to `ddu-*` services, never to Qdrant/Neo4j/CompreFace/etc. directly.
- **No license mixing without review.** AGPL / Apache / GPL / MIT repos coexist via process boundaries, not code copying. Attribution tracked per service.

---

# 3. Integration Tiers

Every OSS repo falls into exactly one tier. Tier determines how DDU uses it.

## Tier 1 — External Service (process boundary)

Run as standalone containers. DDU talks over their native protocol (Bolt, HTTP, gRPC, S3, REST). Never import their code.

| Repo | Protocol | DDU Service | Notes |
|------|----------|-------------|-------|
| `neo4j/neo4j` | Bolt / Cypher | `ddu-graph-store` | Persistence under OpenSPG + Graphiti |
| `qdrant/qdrant` | HTTP / gRPC | `ddu-vector` | Vector store |
| `minio/minio` | S3 API | `ddu-storage` | Evidence Store backend. Reassess upstream repo state before final lock-in |
| `exadel-inc/CompreFace` | REST | `ddu-face` | Face recognition service |
| `smicallef/spiderfoot` | REST (SpiderFoot API) | `ddu-osint` | Run as container; DDU drives via API |
| `OpenSPG/openspg` | Service runtime | `ddu-ontology` | Ontology materialization |
| `OpenLineage/OpenLineage` | Spec + backend | `ddu-lineage` | Marquez-style backend; DDU emits events |
| `webrecorder/browsertrix-crawler` | CLI / crawler process | `ddu-webcapture` | Outputs WARC to MinIO |

**Rule:** Upstream security patches flow via image version bumps. Pin versions. Upgrade deliberately.

## Tier 2 — Wrapped Inference Microservice (DDU-built adapter)

ML frameworks and CLI tools. DDU builds a small Python service that imports the repo as a dependency (or shells out to its CLI) and exposes a DDU-native API with provenance + OpenLineage emission.

| Repo | DDU Service | Integration Mode |
|------|-------------|------------------|
| `IDEA-Research/Grounded-SAM-2` | `ddu-vision` | Python import + model weights |
| `open-mmlab/mmdetection` | `ddu-vision` | Python import + custom configs |
| `PaddlePaddle/PaddleOCR` | `ddu-ocr` | Python import |
| `openai/whisper` | `ddu-audio` | Python import |
| `VicenteVivan/geo-clip` | `ddu-geo` | Python import + model weights |
| `sherlock-project/sherlock` | `ddu-discovery` | CLI subprocess (it is a CLI tool) |
| `mikf/gallery-dl` | `ddu-collector` | CLI subprocess |

**Rule:** Each service owns its model weights, GPU scheduling, batching, and lifecycle. DDU core never loads a model.

## Tier 3 — Embedded Library (dependency)

Pure libraries with stable APIs. Install via package manager, import directly in DDU code.

| Repo | Language | DDU Service | Package |
|------|----------|-------------|---------|
| `langchain-ai/langgraph` | Python | `ddu-agent` | `pip install langgraph` |
| `moj-analytical-services/splink` | Python | `ddu-resolution` | `pip install splink` |
| `getzep/graphiti` | Python | `ddu-temporal` | `pip install graphiti-core` (verify package name) |
| `cytoscape/cytoscape.js` | JS | `ddu-ui` | `npm install cytoscape` |
| `maplibre/maplibre-gl-js` | JS | `ddu-ui` | `npm install maplibre-gl` |

**Rule:** Pin versions. Lockfiles committed. Upgrade deliberately.

---

# 4. DDU Service Catalog

Mirrors PDD section 39, expanded with tier and dependencies.

| Service | Role | Tier 1 Backends | Tier 2 Backends | Tier 3 Libs |
|---------|------|-----------------|-----------------|-------------|
| `ddu-api` | Main application API, auth, RBAC | — | — | — |
| `ddu-ingest` | File / URL ingestion, hash, store | MinIO | — | — |
| `ddu-vision` | Object detection, segmentation, tracking | — | Grounded-SAM-2, MMDetection | — |
| `ddu-face` | Face / person similarity | CompreFace | — | — |
| `ddu-ocr` | OCR, document text | — | PaddleOCR | — |
| `ddu-audio` | Speech transcription | — | Whisper | — |
| `ddu-geo` | Image geolocation | — | GeoCLIP | — |
| `ddu-discovery` | Username → accounts | — | Sherlock | — |
| `ddu-osint` | OSINT enrichment | SpiderFoot | — | — |
| `ddu-collector` | Media acquisition | — | gallery-dl | — |
| `ddu-webcapture` | Web capture, WARC | Browsertrix, MinIO | — | — |
| `ddu-resolution` | Multimodal entity resolution | Qdrant, Neo4j | — | Splink |
| `ddu-vector` | Vector similarity | Qdrant | — | — |
| `ddu-ontology` | Canonical ontology | OpenSPG, Neo4j | — | — |
| `ddu-temporal` | Temporal knowledge graph | Neo4j | — | Graphiti |
| `ddu-graph-store` | Graph persistence | Neo4j | — | — |
| `ddu-storage` | Evidence object store | MinIO | — | — |
| `ddu-lineage` | Processing provenance | OpenLineage | — | — |
| `ddu-agent` | Investigation orchestration | Neo4j, Qdrant | — | LangGraph |
| `ddu-ui` | Graph + map + timeline + evidence viewer | — | — | Cytoscape.js, MapLibre GL JS |

---

# 5. Service Interface Contract

Every `ddu-*` service exposes:

1. **Request schema** — protobuf or JSON Schema, versioned.
2. **Response schema** — includes results + per-result provenance block.
3. **OpenLineage event** — emitted on every invocation: `RunEvent` (START, RUNNING, COMPLETE, FAIL) with inputs, outputs, tool name, tool version, model version where applicable.
4. **Evidence reference** — every output references an evidence object in MinIO by hash.
5. **Confidence field** — every candidate output carries a confidence value; never implied.
6. **Health + version endpoint** — `GET /healthz`, `GET /versionz` (reports upstream tool + model versions).

DDU core depends only on these contracts. Replacing GeoCLIP with a better geo model = reimplement `ddu-geo`'s contract. No core changes.

---

# 6. Phases

## Phase 0 — Foundation (pre-MVP)

Goal: standing up infrastructure and service scaffolding.

- [x] Repo structure: monorepo with `services/`, `libs/`, `ui/`, `infra/`, `docs/`.
- [x] `docker-compose.yml` for local dev: Neo4j, Qdrant, MinIO, CompreFace, SpiderFoot, OpenLineage backend.
- [x] Service scaffolding for every `ddu-*` service: empty contract + healthz + versionz + OpenLineage emitter.
- [x] Shared `ddu-contracts` library: protobuf/JSON schemas + provenance block + evidence reference.
- [x] Shared `ddu-lineage-emitter` library: OpenLineage client wrapper.
- [x] CI: lint, typecheck, contract conformance tests per service.

Repos touched: all Tier 1 containers stand up here. No Tier 2/3 logic yet.

## Phase 1 — MVP

PDD section 29 scope. Inputs: Image, Username, URL.

### MVP services to implement

| Service | MVP Scope | Repos Used | Status |
|---------|-----------|------------|--------|
| `ddu-ingest` | Store file/URL → MinIO, hash, metadata | MinIO | [x] |
| `ddu-vision` | Grounded SAM 2 detection + segmentation on images | Grounded-SAM-2 | [x] |
| `ddu-ocr` | PaddleOCR on images | PaddleOCR | [x] |
| `ddu-geo` | GeoCLIP location candidates | GeoCLIP | [x] |
| `ddu-discovery` | Sherlock username search | Sherlock | [x] |
| `ddu-osint` | SpiderFoot enrichment (subset of modules) | SpiderFoot | [x] |
| `ddu-collector` | gallery-dl media acquisition | gallery-dl | [x] |
| `ddu-vector` | Qdrant image + object + text embeddings | Qdrant | [x] |
| `ddu-ontology` | OpenSPG core entity types | OpenSPG, Neo4j | [x] enum validation + Neo4j proxy |
| `ddu-graph-store` | Neo4j persistence + basic Cypher queries | Neo4j | [x] |
| `ddu-resolution` | Splink record linkage + Qdrant similarity → candidate relationships | Splink, Qdrant, Neo4j | [x] |
| `ddu-storage` | MinIO evidence store | MinIO | [x] |
| `ddu-lineage` | OpenLineage event emission | OpenLineage | [x] |
| `ddu-agent` | Basic LangGraph workflow: image → OCR → vision → geo → graph | LangGraph | [x] |
| `ddu-ui` | Cytoscape graph + MapLibre map + evidence viewer + command dashboard | Cytoscape.js, MapLibre GL JS | [x] |
| `ddu-api` | REST over services, RBAC stub | — | [x] |

### MVP workflows (from PDD sections 30–31)

**Workflow A — Image:**
1. `ddu-ingest` stores image in MinIO, hashes, extracts metadata.
2. `ddu-vision` runs Grounded SAM 2 → object observations.
3. `ddu-ocr` runs PaddleOCR → text observations.
4. `ddu-geo` runs GeoCLIP → location hypotheses.
5. `ddu-vector` embeds image + object crops + OCR text → Qdrant.
6. `ddu-ontology` creates entities in OpenSPG, persists to Neo4j.
7. `ddu-resolution` generates candidate relationships.
8. `ddu-ui` renders graph (Cytoscape) + map (MapLibre) + evidence viewer.
9. `ddu-lineage` records every step.

**Workflow B — Username:**
1. `ddu-discovery` runs Sherlock → CandidateAccount entities.
2. `ddu-osint` runs supported SpiderFoot modules.
3. `ddu-collector` routes supported URLs to gallery-dl → media to MinIO.
4. Media processed by `ddu-vision` / `ddu-ocr` / `ddu-geo` / `ddu-vector`.
5. `ddu-resolution` generates candidate identity relationships.
6. `ddu-ui` renders account network.

**Workflow C — URL:**
1. `ddu-ingest` classifies source, extracts metadata.
2. `ddu-collector` (gallery-dl) or `ddu-webcapture` (Browsertrix) acquires content.
3. Content processed by perception services.
4. Ontology + graph updated.

### MVP exclusions (explicit)

- No video ingestion
- No MMDetection custom models
- No Whisper / audio
- No CompreFace / face matching
- No Graphiti temporal layer
- No Timeline UI
- No contradiction engine
- No autonomous LangGraph workflows (only scripted)
- No NL query engine

## Phase 2 — Multimodal + Temporal

PDD section 32 scope.

| Capability | Service | Repos Used | Status |
|------------|---------|------------|--------|
| Video ingestion + frame extraction | `ddu-ingest`, `ddu-vision` | Grounded-SAM-2 (video tracking) | [x] |
| Specialized detection | `ddu-vision` | MMDetection | [x] `/v1/detect/specialized` |
| Audio transcription | `ddu-audio` | Whisper | [x] |
| Face / person similarity | `ddu-face` | CompreFace | [x] |
| Temporal knowledge graph | `ddu-temporal` | Graphiti, Neo4j | [x] |
| Timeline UI | `ddu-ui` | (custom, synced with Cytoscape + MapLibre) | [x] |
| Contradiction engine | `ddu-resolution` | (proprietary) | [x] |
| Advanced multimodal entity resolution | `ddu-resolution` | Splink + Qdrant + CompreFace + Neo4j | [x] attribute + vector hooks |
| Advanced social connectors | `ddu-collector`, `ddu-osint` | gallery-dl, SpiderFoot | [x] |

## Phase 3 — Autonomy + Collaboration

PDD section 33 scope.

| Capability | Service | Repos Used | Status |
|------------|---------|------------|--------|
| Autonomous investigation workflows | `ddu-agent` | LangGraph | [x] |
| Investigation templates | `ddu-agent` | LangGraph | [x] |
| Natural-language investigation queries | `ddu-api`, `ddu-agent` | LangGraph | [x] |
| Collaborative investigations | `ddu-api` | — | [x] members API |
| Human verification workflows | `ddu-api`, `ddu-ui` | — | [x] |
| Report generation | `ddu-api` | — | [x] |
| Graph snapshots | `ddu-graph-store` | Neo4j | [x] |
| Investigation replay | `ddu-lineage`, `ddu-graph-store` | OpenLineage, Neo4j | [x] |
| Plugin SDK | `ddu-api` | — | [x] catalog endpoint |
| Custom ontology builder | `ddu-ontology`, `ddu-ui` | OpenSPG | [x] investigation-scoped type registry |
| Air-gapped deployment | `infra/` | all (offline image mirror) | [x] `infra/scripts/airgap-mirror.sh` |

---

# 7. Repo Usage Matrix (when each repo enters)

| Repo | Tier | Phase 0 | Phase 1 (MVP) | Phase 2 | Phase 3 |
|------|------|---------|---------------|---------|---------|
| Neo4j | 1 | container up | persistence | temporal backend | snapshots, replay |
| Qdrant | 1 | container up | embeddings | — | — |
| MinIO | 1 | container up | evidence store | — | air-gapped |
| CompreFace | 1 | container up | — | face matching | — |
| SpiderFoot | 1 | container up | enrichment | advanced modules | — |
| OpenSPG | 1 | container up | ontology | — | custom ontology builder |
| OpenLineage | 1 | backend up | event emission | — | investigation replay |
| Browsertrix | 1 | container up | URL capture | — | — |
| Grounded-SAM-2 | 2 | scaffold | image detection | video tracking | — |
| MMDetection | 2 | scaffold | — | specialized detection | — |
| PaddleOCR | 2 | scaffold | OCR | — | — |
| Whisper | 2 | scaffold | — | ASR | — |
| GeoCLIP | 2 | scaffold | geolocation | — | — |
| Sherlock | 2 | scaffold | username discovery | — | — |
| gallery-dl | 2 | scaffold | media acquisition | advanced connectors | — |
| LangGraph | 3 | dep pinned | scripted workflow | — | autonomous workflows, NL queries |
| Splink | 3 | dep pinned | record linkage | multimodal resolution | — |
| Graphiti | 3 | dep pinned | — | temporal KG | — |
| Cytoscape.js | 3 | dep pinned | graph UI | — | — |
| MapLibre GL JS | 3 | dep pinned | map UI | — | — |

---

# 8. Tech Stack Decisions

| Layer | Choice | Reason |
|-------|--------|--------|
| Service language (perception, agent, resolution) | Python | All Tier 2 ML repos are Python-native |
| Service language (api, ingest, storage, graph-store) | Python or Go | TBD per service; Go for high-throughput I/O services, Python for graph-heavy |
| UI | TypeScript + React | Cytoscape.js + MapLibre are JS-native |
| Inter-service comms | gRPC + REST | gRPC for internal hot paths, REST for `ddu-api` external |
| Contracts | protobuf + JSON Schema | Versioned, language-agnostic |
| Container orchestration | Docker Compose (dev), Kubernetes (prod) | Standard |
| Model weights storage | MinIO bucket, versioned | Reproducibility |
| Secrets | Vault or SOPS | Never in repo |
| CI | GitHub Actions | Lint, typecheck, contract conformance, unit tests |
| Observability | OpenTelemetry → Prometheus + Grafana + Loki | Standard |

---

# 9. Repository Layout (proposed)

```
DDU/
├── main-pdd.md
├── engineering-roadmap.md
├── README.md
├── open-source/                # reference clones, not used at runtime
├── services/
│   ├── ddu-api/
│   ├── ddu-ingest/
│   ├── ddu-vision/
│   ├── ddu-face/
│   ├── ddu-ocr/
│   ├── ddu-audio/
│   ├── ddu-geo/
│   ├── ddu-discovery/
│   ├── ddu-osint/
│   ├── ddu-collector/
│   ├── ddu-webcapture/
│   ├── ddu-resolution/
│   ├── ddu-vector/
│   ├── ddu-ontology/
│   ├── ddu-temporal/
│   ├── ddu-graph-store/
│   ├── ddu-storage/
│   ├── ddu-lineage/
│   └── ddu-agent/
├── libs/
│   ├── ddu-contracts/          # protobuf + JSON schemas
│   ├── ddu-lineage-emitter/    # OpenLineage client wrapper
│   └── ddu-evidence/           # evidence model, hashing, provenance
├── ui/
│   └── ddu-ui/                 # React + Cytoscape + MapLibre
├── infra/
│   ├── docker-compose.yml      # local dev
│   ├── docker-compose.prod.yml
│   └── k8s/
└── docs/
```

`open-source/` keeps reference clones for reading. Runtime uses pinned container images or pinned package versions, never the cloned source.

---

# 10. License Hygiene

| Repo | License | Tier | Implication |
|------|---------|------|-------------|
| Neo4j | GPLv3 (community) / commercial | 1 | Process boundary OK; no code copying |
| Qdrant | Apache 2.0 | 1 | Permissive |
| MinIO | AGPLv3 | 1 | Process boundary OK; no code copying. Reassess repo state |
| CompreFace | Apache 2.0 | 1 | Permissive |
| SpiderFoot | MIT | 1 | Permissive |
| OpenSPG | Apache 2.0 | 1 | Permissive |
| OpenLineage | Apache 2.0 | 1 | Permissive |
| Browsertrix | AGPLv3 | 1 | Process boundary OK; no code copying |
| Grounded-SAM-2 | Apache 2.0 | 2 | Permissive |
| MMDetection | Apache 2.0 | 2 | Permissive |
| PaddleOCR | Apache 2.0 | 2 | Permissive |
| Whisper | MIT | 2 | Permissive |
| GeoCLIP | MIT | 2 | Permissive |
| Sherlock | MIT | 2 | Permissive |
| gallery-dl | Unlicense | 2 | Permissive |
| LangGraph | MIT | 3 | Permissive |
| Splink | MIT | 3 | Permissive |
| Graphiti | Apache 2.0 | 3 | Permissive |
| Cytoscape.js | MIT | 3 | Permissive |
| MapLibre GL JS | BSD-3-Clause | 3 | Permissive |

**Rule:** AGPLv3 (MinIO, Browsertrix) and GPLv3 (Neo4j community) repos are **Tier 1 only**. Never import their code into DDU. Process boundary keeps DDU's license independent. If DDU ever needs Neo4j Enterprise features, acquire a commercial license — do not work around it.

---

# 11. Verification Gates

Every phase exit requires:

- [x] All MVP/phase services pass contract conformance tests
- [x] OpenLineage events emitted for every service invocation
- [x] Evidence references resolvable in MinIO for every output
- [x] Confidence field present on every candidate relationship
- [x] No direct DDU-core → OSS-backend calls (only via `ddu-*` service)
- [x] License attribution file up to date (`THIRD_PARTY_NOTICES.md`)
- [x] `docker-compose up` brings full stack up clean
- [x] Smoke test: image seed → graph + map + evidence viewer populated
