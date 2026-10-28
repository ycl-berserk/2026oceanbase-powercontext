UV ?= uv
PY := .venv/bin/python
PC_DB := $(CURDIR)/data/powercontext/sdd.db
PC_URL ?= http://127.0.0.1:8102

.PHONY: setup ingest plan start status powercontext verify test test-workspace red-green clean

.venv/bin/python:
	$(UV) venv .venv --python 3.12

setup: .venv/bin/python
	$(UV) pip install --python $(PY) -e ".[dev]"

ingest:
	$(PY) -m sdd_context ingest

plan:
	$(PY) -m sdd_context plan --task "$(TASK)" --task-id "$(or $(TASK_ID),active)"

start:
	$(PY) -m sdd_context start --task-id "$(TASK_ID)" --items "$(ITEMS)"

status:
	$(PY) -m sdd_context status --task-id "$(TASK_ID)"

powercontext:
	mkdir -p data/powercontext
	POWERCONTEXT_SERVER_DATABASE_URL="sqlite+aiosqlite:///$(PC_DB)" \
		$(PY) -m powercontext.cli.app server run --host 127.0.0.1 --port 8102

verify:
	$(PY) scripts/verify.py

test: test-workspace

test-workspace:
	PYTHONPATH=workspace/src $(PY) -m pytest -q workspace/tests

red-green:
	bash scripts/demo_red_green.sh

clean:
	rm -rf data .pytest_cache .ruff_cache
