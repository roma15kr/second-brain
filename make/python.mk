# Python: uv (when uv.lock exists) or a local .venv, pytest, Ruff, mypy.
PY ?= $(if $(wildcard uv.lock),uv run python,$(if $(wildcard .venv/bin/python),.venv/bin/python,python3))
PY_TYPECHECK ?= $(PY) -m mypy .
PY_TEST ?= $(PY) -m pytest -q

.PHONY: install-python typecheck-python lint-python test-python fmt-python

install-python:
	@if [ -f uv.lock ] || { [ -f pyproject.toml ] && command -v uv > /dev/null; }; then \
	  uv sync; \
	else \
	  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && \
	  for f in requirements.txt requirements-dev.txt; do \
	    if [ -f $$f ]; then .venv/bin/pip install -q -r $$f; fi; \
	  done; \
	fi

typecheck-python:
	$(PY_TYPECHECK)

lint-python:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

test-python:
	$(PY_TEST)

# Fix first, then format: removing code can leave formatting that only `format` repairs.
fmt-python:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .
