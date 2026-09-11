.PHONY: help install test lint fmt typecheck up down db demo check

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## create the venv and install dev dependencies
	uv venv
	uv pip install -e .
	uv pip install pytest pytest-asyncio ruff mypy respx

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

up:  ## start postgres, redis, minio, langfuse
	docker compose up -d

down:  ## stop the stack
	docker compose down

db:  ## apply the schema
	psql "$${DATABASE_URL:-postgresql://preflight:preflight@localhost:5432/preflight}" -f db/001_init.sql

demo:  ## decode the bundled example NOTAMs
	.venv/bin/python -m preflight.decode.notam --demo
