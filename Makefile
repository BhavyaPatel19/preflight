.PHONY: help install test lint fmt typecheck up down db db-start db-stop db-status demo check

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## create the venv and install locked dependencies
	uv sync

test:  ## run the test suite
	.venv/bin/python -m pytest

lint:  ## check style
	.venv/bin/ruff check src tests

fmt:  ## autoformat
	.venv/bin/ruff check --fix src tests
	.venv/bin/ruff format src tests

typecheck:  ## static types
	.venv/bin/mypy

check: lint typecheck test  ## everything CI runs

PGBIN ?= /opt/homebrew/opt/postgresql@17/bin
PGDATA ?= /opt/homebrew/var/postgresql@17

db-start:  ## start native Postgres (Homebrew postgresql@17 + pgvector) on :5433 — no login service
	$(PGBIN)/pg_ctl -D $(PGDATA) -l $(PGDATA)/server.log start

db-stop:  ## stop native Postgres
	$(PGBIN)/pg_ctl -D $(PGDATA) stop

db-status:  ## is native Postgres running?
	@$(PGBIN)/pg_ctl -D $(PGDATA) status || true

up:  ## start the full Docker stack (postgres :5432, redis, minio, langfuse, scheduler)
	docker compose up -d

down:  ## stop the stack
	docker compose down

db:  ## apply db/*.sql migrations to $$DATABASE_URL
	for f in db/*.sql; do psql "$${DATABASE_URL:-postgresql://preflight:preflight@localhost:5433/preflight}" -v ON_ERROR_STOP=1 -f $$f; done

demo:  ## decode the bundled example NOTAMs
	.venv/bin/python -m preflight.decode.notam --demo
