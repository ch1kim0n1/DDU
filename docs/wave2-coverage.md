# Wave 2 coverage — DDU Mirror

All Tier 0–3 checklist items are implemented in-repo or documented with an explicit owner/process gate.

## Code / infra (complete)

- Rate limits, TLS/Caddy, CSP/HSTS, legal pages, WebGL fallback, session expiry, camera/map/focus UX
- Vitest + Playwright configs/tests, JSON logging, Sentry, Prometheus `/metrics`, Dependabot, CI ui/smoke/e2e/trivy
- GDPR export/wipe, biometric consent, a11y labels, lazy bundles, Dockerfiles, deployment/user/runbook docs
- Support UI, analytics shim + Plausible hook, session recovery, memo/deferredValue, k6 scripts, license docs
- Staging compose, OpenAPI Bearer scheme + tags/response models, session TTL, WS validation, audit JSONL
- Prod mode enforcement, Redis pooling/AOF backup docs, LLM failover (Anthropic→OpenAI→offline)
- Toasts, timeout UX, wizard persistence/validation, map clustering, proposal diff, activity filters/search
- Score tooltip, print CSS, rate-limit headers, versionz/env banners, pinned npm versions

## Ops / account gates (cannot be finished by code alone)

| Item | Status | Owner action |
|------|--------|--------------|
| GitHub Actions billing / green CI on `main` | Blocked | Fix spending limit — [#4](https://github.com/ch1kim0n1/DDU/issues/4) |
| Real support mailbox + auto-responder | Template ready | Point DNS/MX; enable mailbox |
| Signed DPAs (ElevenLabs / LLM) | Documented | Execute before production PII |
| Staging host (Railway/Fly) | Compose ready | Deploy `docker-compose.staging.yml` |
| BrowserStack / real iOS+Android devices | Docs in `browser-support.md` | Run device matrix pre-launch |
| Live Trivy/ZAP/safety/govulncheck on staging | Scripts + CI + `security-scan-results.md` | Run against staging URL |
| Lighthouse numbers on prod URL | Targets in `lighthouse.md` | Record scores in release PR |

Until the account gates above are green, verdict remains **READY FOR DEMO / staging**, not full commercial production.
