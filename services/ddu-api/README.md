# ddu-api

Scaffold. Implements:
- `GET /healthz` — health probe
- `GET /versionz` — service + tool + model version
- Lineage emitter wiring (best-effort)

## Run

```bash
go run . -port 8001
```

Environment:
- `PORT` — listen port (default 8001)
- `OPENLINEAGE_URL` — OpenLineage backend URL
- `OPENLINEAGE_NAMESPACE` — job namespace (default `ddu.dev`)
