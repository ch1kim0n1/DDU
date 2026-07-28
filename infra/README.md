# DDU local development

Workflow A runs the Tier 1 containers, seven DDU backend services, three ML
services, and the React UI. Authentication is intentionally absent in this MVP;
investigation scope is carried in the path or `X-Investigation-Id`.

## Tier 1

```bash
cd infra
cp .env.example .env
docker compose up -d
docker compose ps
```

The example environment maps Marquez to `localhost:5002` because macOS commonly
reserves port 5000. Neo4j uses 7474/7687, Qdrant 6333/6334, MinIO 9000/9001,
CompreFace 8000, and SpiderFoot 5001.

Validate the compose file and core dependencies:

```bash
docker compose config --quiet
curl -fsS http://localhost:6333/healthz
curl -fsS http://localhost:9000/minio/health/live
curl -fsS http://localhost:5002/healthcheck
```

## Python environment

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e libs/ddu-py-common
pip install -e services/ddu-vision
pip install -e services/ddu-ocr
pip install -e services/ddu-geo
pip install -e services/ddu-ontology
```

Base installs keep model runtimes optional so CPU-only CI can import every
service. Install production model adapters on Python 3.11:

```bash
pip install -e 'services/ddu-vision[model]'
pip install -e 'services/ddu-ocr[model]'
pip install -e 'services/ddu-geo[model]'
```

## DDU services

Run each command in its own terminal from the repository root. All lineage
emitters target the DDU lineage proxy, which forwards to Marquez.

```bash
cd services/ddu-lineage
OPENLINEAGE_URL=http://localhost:5002 go run .
```

```bash
cd services/ddu-storage
OPENLINEAGE_URL=http://localhost:8006 go run .
```

```bash
cd services/ddu-graph-store
OPENLINEAGE_URL=http://localhost:8006 go run .
```

```bash
cd services/ddu-vector
OPENLINEAGE_URL=http://localhost:8006 go run .
```

```bash
cd services/ddu-ingest
OPENLINEAGE_URL=http://localhost:8006 go run .
```

For an end-to-end contract smoke without downloading model weights, set
`MODEL_MODE=stub`. Stub observations are explicitly marked
`extraction_method=development-stub` and must not be used as analytical output.
Omit this variable for Grounded SAM 2, PaddleOCR, and GeoCLIP inference.

```bash
cd services/ddu-vision
MODEL_MODE=stub OPENLINEAGE_URL=http://localhost:8006 ../../.venv/bin/python app.py
```

```bash
cd services/ddu-ocr
MODEL_MODE=stub OPENLINEAGE_URL=http://localhost:8006 ../../.venv/bin/python app.py
```

```bash
cd services/ddu-geo
MODEL_MODE=stub OPENLINEAGE_URL=http://localhost:8006 ../../.venv/bin/python app.py
```

```bash
cd services/ddu-ontology
OPENLINEAGE_URL=http://localhost:8006 ../../.venv/bin/python app.py
```

Start the gateway last:

```bash
cd services/ddu-api
OPENLINEAGE_URL=http://localhost:8006 go run .
```

The default ports are API 8001, ingest 8002, storage 8003, graph-store 8004,
vector 8005, lineage 8006, vision 8101, OCR 8103, geo 8105, and ontology 8107.
Each service provides `/healthz` and `/versionz`.

## UI and smoke test

The UI uses the repository-pinned pnpm version:

```bash
cd ui
npx --yes pnpm@10.26.2 install --filter @ddu/ddu-ui... --ignore-scripts
npx --yes pnpm@10.26.2 --filter @ddu/ddu-ui dev
```

Open `http://localhost:5173`. With all services running:

```bash
./infra/scripts/smoke.sh
```

The smoke creates an investigation, uploads a generated PNG, verifies persisted
observation entities and lineage runs, retrieves the evidence URL, and checks
the UI endpoint.

## Shutdown

Stop DDU service processes with `Ctrl-C`. Keep or destroy Tier 1 data with:

```bash
cd infra
docker compose down
docker compose down -v
```
