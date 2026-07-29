# DDU Mirror — Ops Runbook

## Backend won't start

- Port 8120 in use: change `MIRROR_INTEL_PORT` or stop the other process.
- Missing Python deps: `pip install -e libs/ddu-py-common -e services/ddu-mirror-intel`.
- Check `MIRROR_ENV` and identity settings if production mode exits early.

## Sessions lost on restart

In-memory store is ephemeral. Set `MIRROR_REDIS_URL` + `MIRROR_SESSION_ENCRYPTION_KEY` for durable sessions.

## High error rate

- Check Sentry (`SENTRY_DSN`).
- Hit `/readyz` and `/metrics`.
- Verify Anthropic / ElevenLabs upstream status; offline mode is expected without keys.

## WebSocket failures

- Confirm reverse proxy forwards `/intel/ws/` with long timeouts (see `infra/Caddyfile`).
- Clients on HTTPS must use `wss://`.
- Unknown session closes with code 1008.

## Session creation failing

- 429: rate limit (5/hour/IP). Check logs for `rate_limit_hit`.
- 401: identity verifier required / bad bearer token.
- 400: mock seeding blocked in production identity mode.

## Redis persistence & backup

Production compose enables AOF (`appendonly yes`). Hourly snapshot:

```bash
redis-cli -a "$REDIS_PASSWORD" BGSAVE
# copy dump.rdb + appendonly.aof to durable backup storage
```

### Restore

1. Stop `mirror-intel` and `redis`.
2. Restore `dump.rdb` / AOF into the Redis volume.
3. Start Redis, then mirror-intel.
4. Confirm `/healthz` reports `session_store: ok`.

**Critical:** back up `MIRROR_SESSION_ENCRYPTION_KEY` separately. If the key is lost, encrypted sessions are unrecoverable even with a perfect Redis restore.

## Support process

Inbound: `support@ddu-mirror.local` (replace with real domain before launch).

Auto-responder draft:

> Thank you for contacting DDU Mirror support. We'll respond within 24 hours.
> For urgent issues, include your session ID (shown in the app header after a scan starts — never paste secrets).

Escalate production outages via the on-call channel; attach `/healthz`, `/readyz`, and recent Sentry events.
