# DDU local orchestration
ROOT := $(abspath .)
COMPOSE := docker compose -f infra/docker-compose.yml
COMPOSE_DDU := docker compose -f infra/docker-compose.yml -f infra/docker-compose.ddu.yml
export MODEL_MODE ?= stub
export AUTH_MODE ?= dev
export DDU_ALLOW_ROLE_HEADER ?= true
export OPENLINEAGE_URL ?= http://localhost:8006

.PHONY: up down tier1 services logs ps smoke smoke-b smoke-c smoke-intel models health test-mirror mirror

## Start Tier 1 backends only (Neo4j, MinIO, Qdrant, Marquez, ...)
tier1:
	$(COMPOSE) up -d
	$(COMPOSE) ps

## Start Tier 1 + all DDU service containers
up:
	$(COMPOSE_DDU) up -d --build
	$(COMPOSE_DDU) ps

## Stop everything (keep volumes)
down:
	$(COMPOSE_DDU) down

## Destroy volumes too
down-v:
	$(COMPOSE_DDU) down -v

## Host-process dev stack helper (Tier1 + print start commands)
dev: tier1
	@echo "Tier 1 is up. Start DDU services with:"
	@echo "  ./infra/scripts/dev-services.sh"

ps:
	$(COMPOSE_DDU) ps

logs:
	$(COMPOSE_DDU) logs -f --tail=200

health:
	@curl -fsS http://localhost:8001/healthz | jq '{state,bad:[.dependencies[]|select(.ok==false)|.name]}'

smoke:
	./infra/scripts/smoke.sh

smoke-b:
	./infra/scripts/smoke-workflow-b.sh

smoke-c:
	./infra/scripts/smoke-workflow-c.sh

smoke-intel:
	./infra/scripts/smoke-post-mvp.sh

models:
	./infra/scripts/bootstrap-models.sh

## Run every DDU Mirror test suite (Engineers A + B + C + D)
##
## Each service runs in its OWN pytest process, deliberately. Both mirror
## services follow the repo's one-app.py-per-service convention, so a single
## process resolves `import app` to whichever is first on sys.path and silently
## tests the wrong service. Don't "simplify" this into one pytest call.
PY ?= python
## Editable installs are on disk (`__editable__.ddu_py_common-*.pth` points at
## libs/ddu-py-common/src) but Homebrew's Python 3.14 ships a sitecustomize.py
## that drops those .pth entries, so `import ddu_common` fails even inside the
## venv. Passing the paths explicitly is interpreter-independent and works
## whether or not the editable hooks fire. Absolute, because the targets cd.
MIRROR_PYTHONPATH = $(CURDIR)/libs/ddu-py-common/src:$(CURDIR)/services/ddu-mirror-intel

test-mirror:
	@find services -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "── services/ddu-mirror (A: trust spine) ──"
	@cd services/ddu-mirror && PYTHONPATH="$(MIRROR_PYTHONPATH)" $(PY) -m pytest test_app.py -q
	@echo "── services/ddu-mirror-intel (B: intel · C: vision · D: voice) ──"
	@cd services/ddu-mirror-intel && PYTHONPATH="$(MIRROR_PYTHONPATH)" $(PY) -m pytest \
		test_app.py test_engineer_d_contract.py \
		test_production_runtime.py test_vision_engineer_c.py -q
	@echo "── ui/ddu-ui ──"
	@cd ui/ddu-ui && npm test --silent

## Start both Mirror services locally (offline-safe: no API keys needed)
mirror:
	@mkdir -p /tmp/ddu-stack-logs
	@cd services/ddu-mirror && PYTHONPATH="$(MIRROR_PYTHONPATH)" PORT=8130 \
		$(PY) app.py > /tmp/ddu-stack-logs/mirror-a.log 2>&1 &
	@cd services/ddu-mirror-intel && PYTHONPATH="$(MIRROR_PYTHONPATH)" \
		MIRROR_FORCE_OFFLINE=1 MIRROR_INTEL_PORT=8120 \
		$(PY) app.py > /tmp/ddu-stack-logs/mirror-b.log 2>&1 &
	@sleep 8
	@echo "trust spine  : http://localhost:8130/healthz"
	@echo "intel + HITL : http://localhost:8120/docs"
	@echo "UI           : cd ui/ddu-ui && npm run dev   → http://localhost:5173"
