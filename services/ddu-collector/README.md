# ddu-collector

Scaffold. Implements:
- `GET /healthz` — health probe
- `GET /versionz` — service + tool + model version
- Lineage emitter wiring (best-effort)

## Run

```bash
go run . -port 8008
```

Environment:
- `PORT` — listen port (default 8008)
- `OPENLINEAGE_URL` — OpenLineage backend URL
- `OPENLINEAGE_NAMESPACE` — job namespace (default `ddu.dev`)
