# License audit — DDU Mirror

Primary runtime stacks:

- Frontend (`ui/ddu-ui`): React, Vite, Three.js, MapLibre, Recharts, Sentry — MIT / Apache-2.0 compatible.
- Backend (`ddu-mirror-intel`): FastAPI, Pydantic, Redis, LangGraph, slowapi — MIT / BSD / Apache-2.0.

## Process

```bash
cd ui/ddu-ui && npx license-checker --summary
pip install pip-licenses && pip-licenses --from=mixed
```

Flag any GPL/AGPL runtime dependency before commercial distribution. Dev/test-only GPL tools are acceptable if not shipped in production images.

## Frontend summary (`npx license-checker --summary`)

| License | Count |
|---------|------:|
| MIT | 237 |
| ISC | 36 |
| Apache-2.0 | 14 |
| BSD-3-Clause | 10 |
| BSD-2-Clause | 4 |
| MPL-2.0 | 2 |
| Other (MIT-0, BlueOak, Custom GSAP, UNLICENSED local) | small |

No GPL/AGPL runtime packages found. GSAP uses its Standard license — confirm commercial terms before paid distribution.

Last reviewed: 2026-07-29.
