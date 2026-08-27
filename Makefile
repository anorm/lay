.POSIX:
.PHONY: help install uninstall test lint dev clean

BIN ?= $(HOME)/.local/bin

help:
	@echo "make install    install lay into $(BIN)"
	@echo "make uninstall  remove lay"
	@echo "make dev        create the development environment"
	@echo "make test       run the test suite"
	@echo "make clean      remove build and cache artefacts"

install:
	@command -v uv >/dev/null || { \
	  echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
	uv tool install --force --reinstall .
	@echo
	@echo "installed. make sure $(BIN) is on your PATH."

uninstall:
	uv tool uninstall lay

dev:
	uv sync

test: dev
	uv run ruff check
	uv run pyright
	uv run pytest -q

lint: dev
	uv run python -m compileall -q src

clean:
	rm -rf dist build .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
