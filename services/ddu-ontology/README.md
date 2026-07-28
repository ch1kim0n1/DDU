# ddu-ontology

Scaffold. Implements:
- `GET /healthz`
- `GET /versionz`
- Lineage emitter wiring (best-effort)

## Run

```bash
pip install -e ../../libs/ddu-py-common
pip install -e .
python app.py
```

Environment:
- `PORT` — listen port (default 8107)
- `OPENLINEAGE_URL` — OpenLineage backend URL
- `OPENLINEAGE_NAMESPACE` — job namespace (default `ddu.dev`)
- `DDU_*` — version overrides
