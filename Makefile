# DDU local orchestration
ROOT := $(abspath .)
COMPOSE := docker compose -f infra/docker-compose.yml
COMPOSE_DDU := docker compose -f infra/docker-compose.yml -f infra/docker-compose.ddu.yml
export MODEL_MODE ?= stub
export AUTH_MODE ?= dev
export DDU_ALLOW_ROLE_HEADER ?= true
export OPENLINEAGE_URL ?= http://localhost:8006

.PHONY: up down tier1 services logs ps smoke smoke-b smoke-c smoke-intel models health

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
