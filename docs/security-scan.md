# Security scan results — Wave 3

Last updated: 2026-07-29

## npm audit (`ui/ddu-ui`)

```
npm audit --audit-level=moderate
```

Result: **0 vulnerabilities** with exact dependency pins.

## Python safety

```
pip install safety
cd services/ddu-mirror-intel && safety check
```

Run before each production release. Document residual accepted findings in the release PR.

## Go govulncheck

```
govulncheck ./...
```

Run on every Go module under `services/` and `libs/`.

## Trivy

```
docker build -t ddu-mirror-intel:latest -f services/ddu-mirror-intel/Dockerfile .
trivy image --severity HIGH,CRITICAL ddu-mirror-intel:latest
```

CI job `trivy` runs when Actions billing is available.

## Git history secret scan

```
git log --all --format='%H %s' | rg -i 'key|secret|password|token'
```

Reviewed commit subjects. One historical subject referenced "persona key shorthand" (not a credential).
No live API keys/tokens were found in a targeted content scan of recent history.

If a real secret is ever found: **do not rewrite history without explicit approval** — rotate credentials first, then coordinate `git filter-repo`.
