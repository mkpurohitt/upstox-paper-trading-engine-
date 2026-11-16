SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose
LITE_DB := sqlite+aiosqlite:///$(CURDIR)/var/algo.db

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install Python (uv) and Node (pnpm) dependencies
	uv sync
	pnpm install

dev: ## Full stack in Docker with hot reload (postgres/timescale, redis, api, workers, web)
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up --build

up: ## Full stack in Docker (detached)
	$(COMPOSE) up --build -d

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Tail logs
	$(COMPOSE) logs -f --tail=100

dev-lite: ## No Docker: SQLite + in-process workers, API on :8000 and web on :3000
	@mkdir -p var
	@echo "API  -> http://localhost:8000/docs   Web -> http://localhost:3000"
	@trap 'kill 0' EXIT; \
	(cd apps/api && DATABASE_URL=$(LITE_DB) EMBEDDED_WORKERS=true LOG_JSON=false uv run python -m app.seed && \
	 DATABASE_URL=$(LITE_DB) EMBEDDED_WORKERS=true LOG_JSON=false uv run uvicorn app.main:app --port 8000 --reload) & \
	(pnpm --filter @algo/web dev) & wait

migrate: ## Apply Alembic migrations
	cd apps/api && uv run alembic upgrade head

seed: ## Seed demo user, strategies and mock data
	cd apps/api && uv run python -m app.seed

test: test-api test-web ## Run all tests

test-api: ## Backend tests (pytest)
	uv run pytest -q

test-web: ## Frontend unit tests (vitest)
	pnpm --filter @algo/web test

e2e: ## Playwright smoke tests (expects web on :3000 and api on :8000)
	pnpm --filter @algo/web e2e

evals: ## Run AI evals (mock provider by default)
	uv run python evals/run_evals.py

lint: ## Lint Python + TypeScript
	uv run ruff check .
	pnpm --filter @algo/web lint

typecheck: ## mypy + tsc
	uv run mypy packages/py-common/algo_common services/strategy-engine/strategy_engine --ignore-missing-imports
	pnpm -r typecheck

fmt: ## Format code
	uv run ruff format .
	uv run ruff check --fix .

gen-api: ## Regenerate the typed TS client from the OpenAPI schema
	pnpm gen:api

zip: ## Package the repo as algo-platform.zip (no node_modules/.venv/build/.env)
	@rm -f algo-platform.zip
	git archive --format=zip --prefix=algo-platform/ -o algo-platform.zip HEAD
	@echo "wrote algo-platform.zip"

clean: ## Remove build artefacts
	rm -rf apps/web/.next var .pytest_cache .ruff_cache .mypy_cache
