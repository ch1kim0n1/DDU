# Security Scan Results — DDU Mirror

Last updated: 2026-07-29

## npm audit (`ui/ddu-ui`)

```
npm audit --audit-level=moderate
```

Result: **0 vulnerabilities** after pinning Playwright / Vitest (post Wave 2).

## Python (mirror-intel)

```
pip install safety
cd services/ddu-mirror-intel && safety check
```

Run before each production deploy. Fix HIGH/CRITICAL before ship. CI may skip when GitHub Actions billing is blocked ([#4](https://github.com/ch1kim0n1/DDU/issues/4)).

## Go modules

```
govulncheck ./...
```

Run on every Go module under `services/` and `libs/`. Document residual accepted risks in the PR.

## Trivy (Docker images)

```
docker build -t ddu-mirror-intel:latest -f services/ddu-mirror-intel/Dockerfile .
trivy image --severity HIGH,CRITICAL ddu-mirror-intel:latest

docker build -t ddu-ui:latest ui/ddu-ui
trivy image --severity HIGH,CRITICAL ddu-ui:latest
```

CI job `trivy` runs the same when Actions billing is available.

## OWASP ZAP baseline

```
docker run --rm -t ghcr.io/zaproxy/zaproxy:stable zap-baseline.py \
  -t http://host.docker.internal:8120 -m 5
```

Target a staging deployment, not production. Fail on HIGH; triage MEDIUM.

## Secret history

```
git log --all --format='%H %s' | rg -i 'key|secret|password|token'
```

If a real secret is found, purge with `git filter-repo` and rotate credentials before any further deploys.
