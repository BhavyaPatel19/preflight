.PHONY: help install test lint fmt typecheck up down db db-start db-stop db-status ollama-start ollama-stop demo check

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
# The corpus's lexical channel ranks ~100k tsvectors per query (1.1 GB of TOAST); with the
# 128 MB default they are re-read from disk every time (1.7 s), with 2 GB they stay resident
# (130 ms). Only touched pages become resident, and db-stop frees everything.
PG_SHARED_BUFFERS ?= 2GB

db-start:  ## start native Postgres (Homebrew postgresql@17 + pgvector) on :5433 — no login service
	$(PGBIN)/pg_ctl -D $(PGDATA) -l $(PGDATA)/server.log -o "-c shared_buffers=$(PG_SHARED_BUFFERS)" start

db-stop:  ## stop native Postgres
	$(PGBIN)/pg_ctl -D $(PGDATA) stop

db-status:  ## is native Postgres running?
	@$(PGBIN)/pg_ctl -D $(PGDATA) status || true

# Per-finding model calls are issued concurrently (PREFLIGHT_LLM_CONCURRENCY, default 4);
# they only overlap if the server batches them. Measured on an M5 24 GB (evals/latency):
# without OLLAMA_NUM_PARALLEL four concurrent requests share one slot (13.5 tok/s aggregate);
# with it they batch (31 tok/s) and the briefing's narrative stage halves.
OLLAMA_NUM_PARALLEL ?= 4

ollama-start:  ## start Ollama with request batching (no login service; free the RAM with ollama-stop)
	OLLAMA_NUM_PARALLEL=$(OLLAMA_NUM_PARALLEL) nohup ollama serve > /tmp/ollama.log 2>&1 &
	@sleep 2 && curl -sf http://localhost:11434/api/version >/dev/null && echo "ollama up (parallel=$(OLLAMA_NUM_PARALLEL))"

ollama-stop:  ## stop Ollama and unload the model
	-pkill -x ollama

up:  ## start the full Docker stack (postgres :5432, redis, minio, langfuse, scheduler)
	docker compose up -d

down:  ## stop the stack
	docker compose down

db:  ## apply db/*.sql migrations to $$DATABASE_URL
	for f in db/*.sql; do psql "$${DATABASE_URL:-postgresql://preflight:preflight@localhost:5433/preflight}" -v ON_ERROR_STOP=1 -f $$f; done

demo:  ## decode the bundled example NOTAMs
	.venv/bin/python -m preflight.decode.notam --demo
