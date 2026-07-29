# AGENTS.md — DDU Engineering Conventions

Reference for any agent (human or AI) working in this repo.

## Project

DDU (Digital Detective Unit) — multimodal investigation / intelligence platform. Open-source-first, ontology-native, evidence-backed. See `main-pdd.md` (product) and `engineering-roadmap.md` (engineering).

## Repo Layout

```
DDU/
├── main-pdd.md               # product spec
├── engineering-roadmap.md    # engineering plan
├── README.md
├── AGENTS.md                 # this file
├── open-source/              # reference clones, NOT used at runtime
├── services/                 # ddu-* services (Go + Python)
│   ├── _scaffold/             # Go service generator
│   └── _py_scaffold/          # Python service generator
├── libs/
│   ├── ddu-contracts/         # protobuf schemas (language-agnostic)
│   ├── ddu-lineage-emitter/   # Go OpenLineage client
│   ├── ddu-evidence/          # Go S3 evidence store client
│   └── ddu-py-common/         # Python shared utilities
├── infra/
│   ├── docker-compose.yml     # Tier 1 external services
│   └── docker/                # compose support files
├── docs/                      # design docs
└── ui/                        # TS/React frontend (given)
```

## Languages

- **Go 1.23** — `ddu-api`, `ddu-ingest`, `ddu-storage`, `ddu-graph-store`, `ddu-vector`, `ddu-lineage`, `ddu-webcapture`, `ddu-collector`, `ddu-discovery`
- **Python 3.11+** — `ddu-vision`, `ddu-face`, `ddu-ocr`, `ddu-audio`, `ddu-geo`, `ddu-resolution`, `ddu-ontology`, `ddu-temporal`, `ddu-agent`, `ddu-osint`
- **TypeScript / React** — `ddu-ui`
- **Protobuf** — `libs/ddu-contracts/proto/` — single source of truth for service interfaces

## Build / Test Commands

### Go services and libs

```bash
# Build all Go modules
for d in libs/ddu-lineage-emitter libs/ddu-evidence services/ddu-*; do
  (cd "$d" && go build ./...)
done

# Test a single module
cd services/ddu-api && go test ./...

# Vet
cd services/ddu-api && go vet ./...

# Tidy
cd services/ddu-api && go mod tidy
```

### Python services and libs

```bash
# Create venv once
python3 -m venv .venv && source .venv/bin/activate

# Install common lib + a service
pip install -e libs/ddu-py-common
pip install -e services/ddu-vision

# Run a service
python services/ddu-vision/app.py

# Import smoke test
python -c "import sys; sys.path.insert(0, 'services/ddu-vision'); import app; print(app.VERSION.service)"
```

### Protobuf contracts

```bash
cd libs/ddu-contracts
buf lint
buf generate
```

### Docker compose (Tier 1 stack)

```bash
cd infra
cp .env.example .env
docker compose up -d
docker compose ps
docker compose down      # keep data
docker compose down -v   # destroy data
```

### Mirror UI + production stack

```bash
cd ui/ddu-ui && npm install && npm run build && npm run preview
cd ui/ddu-ui && npm test
cd ui/ddu-ui && npm run e2e
cd ui/ddu-ui && npm run bundle:analyze
# Production (TLS via Caddy):
docker compose -f infra/docker-compose.prod.yml up -d --build
```

`MIRROR_ENV` values: `development` (default), `staging`, `production`.
Production disables mock seeding / Swagger and expects identity + Redis.
Set `MIRROR_RATE_LIMIT=0` only for automated tests.

API versioning: responses include `X-API-Version`. Breaking changes increment the major
version; additive changes stay backward-compatible. Frontend expects major `1.0`.

```bash
# Integration / release gates
bash scripts/smoke-test.sh
bash scripts/verify-frontend.sh
bash scripts/verify-backend.sh
# Load tests (against staging)
k6 run tests/load/session-create.js
# Image scan
trivy image ddu-mirror-intel:latest
# Pre-deploy gate (must pass before every production deploy)
MIRROR_ENV=production MIRROR_IDENTITY_REQUIRED=1 \
  MIRROR_REDIS_URL=... MIRROR_SESSION_ENCRYPTION_KEY=... \
  MIRROR_UI_ORIGIN_REGEX='^https://yourdomain\.example$' \
  ./scripts/pre-deploy-check.sh
```

## Conventions

### Service interface contract

Every `ddu-*` service MUST expose:
- `GET /healthz` — returns `{"state": "HEALTHY"|"DEGRADED"|"UNHEALTHY", ...}`
- `GET /versionz` — returns `ServiceVersion` (service, service_version, tool, tool_version, model, model_version, git_commit, built_at)
- OpenLineage event emission on every invocation (best-effort, never panic)

Every derived artifact (observation, candidate relationship, entity) MUST carry:
- `Provenance` block
- `Confidence` value (for candidate outputs)
- `Evidence` reference (content hash)

### Epistemic discipline

Never collapse epistemic classes. `Observation != Inference != Hypothesis != Fact`. `CandidateRelationship` is never auto-promoted to `Relationship`. High-impact identity merges require human authorization (see `docs/auth-rbac.md`).

### Provenance

Every service invocation emits OpenLineage START + COMPLETE/FAIL events with `run_id`, `job_name`, inputs (evidence ids), outputs (evidence ids / entity ids). Use `libs/ddu-lineage-emitter` (Go) or `libs/ddu-py-common` (Python).

### Evidence immutability

Evidence is content-addressed (`sha256:...`). Same content → same id → same MinIO key. Never mutate. New versions create new evidence objects with `parent_evidence_ids` chain. Use `libs/ddu-evidence` (Go).

### Model weights

Pinned versions only. No `latest`. Stored in MinIO `ddu-models` bucket. See `docs/model-weights.md`. Every ML service reports `model_version` in `/versionz` and every lineage event.

### GPU

Local GPU primary, cloud fallback. ML services must boot on CPU (slow) for dev/CI. See `docs/gpu-strategy.md`.

### Auth / RBAC

Investigation-scoped roles. Agents inherit launching user's role, never escalate. See `docs/auth-rbac.md`.

### Open-source integration

- **Tier 1 (external service):** run as containers, talk via native protocol. Never import code.
- **Tier 2 (wrapped inference):** DDU-built service imports OSS as dep or shells out to CLI. Stable DDU-native API.
- **Tier 3 (embedded library):** install via package manager, pin version.

Never copy source from `open-source/` into DDU code. Those clones are reference only.

### Code style

- Go: `gofmt`, `goimports`, `golangci-lint`. Standard library first.
- Python: `ruff` (config TBD), `black` compatible. Type hints required on public functions.
- Protobuf: `buf lint` STANDARD rules. No breaking changes without version bump.

### Commit messages

Conventional Commits style:
```
feat(ddu-vision): add grounded-sam-2 inference endpoint
fix(ddu-evidence): handle minio not-found error code
docs(auth-rbac): add agent inheritance section
chore(infra): pin neo4j to 5.20.0
```

### Branches

- `main` — always green
- `feat/<scope>-<short>` — feature branches
- `fix/<scope>-<short>` — fix branches

### CI

`.github/workflows/ci.yml` runs on every push and PR:
- `contracts` — buf lint + breaking + generate
- `go` — per-module vet + build + test + golangci-lint
- `python` — per-module install + import smoke
- `compose-validate` — docker compose config check

## Verification Before Considering Work Done

1. Affected Go modules: `go build ./... && go vet ./... && go test ./...`
2. Affected Python modules: `pip install -e . && python -c "import app"`
3. Protobuf changes: `buf lint && buf generate`
4. Compose changes: `docker compose -f infra/docker-compose.yml config --quiet`
5. No direct DDU-core → OSS-backend calls (only via `ddu-*` service contracts)
6. Every new endpoint emits OpenLineage events
7. Every new derived artifact carries Provenance + Confidence + Evidence reference

## Don't

- Don't copy code from `open-source/` into DDU services.
- Don't bypass the service contract layer (DDU core never talks to Neo4j/Qdrant/MinIO directly).
- Don't auto-promote `CandidateRelationship` to `Relationship`.
- Don't commit secrets, model weights, or `.env` files.
- Don't use `latest` tags for any pinned dependency.
- Don't modify git config.
- Don't push without explicit user request.
