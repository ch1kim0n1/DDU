# ddu-webcapture

Scaffold. Implements:
- `GET /healthz` — health probe
- `GET /versionz` — service + tool + model version
- Lineage emitter wiring (best-effort)

## Run

```bash
go run . -port 8007
```

Environment:
- `PORT` — listen port (default 8007)
- `OPENLINEAGE_URL` — OpenLineage backend URL
- `OPENLINEAGE_NAMESPACE` — job namespace (default `ddu.dev`)
