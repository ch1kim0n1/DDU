# DDU Mirror — Production Deployment

## Prerequisites

- Domain with DNS A/AAAA records pointing at your host
- Docker + Docker Compose
- Secrets: `MIRROR_SESSION_ENCRYPTION_KEY`, identity verifier config, optional API keys

## Steps

1. Edit `infra/Caddyfile` — replace `yourdomain.example` with your domain.
2. Copy env values into the host environment or a secrets manager (Doppler / AWS Secrets Manager). Prefer `doppler run -- docker compose ...` over committing `.env`.
3. Set at minimum:
   - `MIRROR_ENV=production`
   - `MIRROR_IDENTITY_REQUIRED=1`
   - `MIRROR_REDIS_URL`
   - `MIRROR_SESSION_ENCRYPTION_KEY`
   - `MIRROR_UI_ORIGIN_REGEX=^https://yourdomain\\.example$`
4. Run the pre-deploy gate (must pass before every production deploy):

```bash
MIRROR_ENV=production MIRROR_IDENTITY_REQUIRED=1 \
  MIRROR_REDIS_URL=... MIRROR_SESSION_ENCRYPTION_KEY=... \
  MIRROR_UI_ORIGIN_REGEX='^https://yourdomain\.example$' \
  bash scripts/pre-deploy-check.sh
```

5. Deploy:

```bash
docker compose -f infra/docker-compose.prod.yml up -d --build
```

6. Verify:
   - `https://yourdomain.example/healthz`
   - `https://yourdomain.example/` loads the UI
   - WebSocket connects over `wss://`
   - Complete mock/real smoke checklist

## Redis

Provision Redis with AOF persistence (`appendonly yes`). Back up `dump.rdb` hourly. Store `MIRROR_SESSION_ENCRYPTION_KEY` separately — without it, encrypted sessions are unrecoverable.

## Optional integrations

- ElevenLabs: `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
- CompreFace: `COMPREFACE_URL`, `COMPREFACE_API_KEY` (keep off the public internet)
- Sentry: `SENTRY_DSN`, `VITE_SENTRY_DSN`

## Rollback

```bash
docker compose -f infra/docker-compose.prod.yml pull   # or rebuild previous tag
docker compose -f infra/docker-compose.prod.yml up -d
```

Keep the previous frontend image tag available so you can retarget `frontend` without rebuilding.
