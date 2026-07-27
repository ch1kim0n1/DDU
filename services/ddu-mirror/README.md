# ddu-mirror

Engineer A's DDU Mirror trust spine. It is the server-side boundary that makes
"scan yourself, not someone else" enforceable:

- 18+ confirmation and six-digit email verification (10-minute TTL, three attempts)
- one active, verified session per identity
- session-only scan authorization; there is no target parameter or target field
- persona weight matrix for `ddu-mirror-intel`
- separate biometric consent with a visible template-destruction countdown and skip path
- TTL-backed ephemeral session state, explicit wipe, audit log, and WebSocket event stream
- signed (Ed25519) consent receipts

## Run

```bash
pip install -e ../../libs/ddu-py-common
pip install -e .
python app.py
```

The service listens on port `8130` by default. `MIRROR_EXPOSE_DEV_CODES=true`
returns verification codes in API responses for local demos only; set it to
`false` when wiring an email provider.

Set `MIRROR_REDIS_URL` (for example, `redis://redis:6379/0`) in deployment to
persist verified session state and its active-scan locks in Redis with the
remaining session TTL. Without it, the identical TTL behavior runs in memory
for local development only.

## Handoff contract

Part B/C calls `POST /v1/findings` using a verified `session_id`; the trust
spine streams the redacted `finding.new` events to Part D over
`/v1/sessions/{session_id}/events`. Part B consumes the persona matrix from
`GET /v1/personas`. No integration caller receives the raw verified email.
