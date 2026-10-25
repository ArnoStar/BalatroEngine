# BalatroEngine (a library, nothing to serve): `make` lists the commands.
.DEFAULT_GOAL := help
.PHONY: help install test test-all lint check build

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

install: ## dependencies (the dev tools)
	uv sync

test: ## the tests (the oracle ones run when luajit and ../balatro_src are here)
	uv run pytest -m "not slow"

test-all: ## with the slow differential fuzz run against the original game
	uv run pytest

lint: ## ruff
	uv run ruff check .

check: test lint ## what CI runs

build: ## the wheel and the source archive, in dist/
	uv build
