PY := .venv/bin/python
RUN := PYTHONPATH=src $(PY)

.PHONY: install ingest serve dev powercontext verify test lint clean

install:
	python3 -m venv .venv
	$(PY) -m pip install -U pip
	$(PY) -m pip install -e ".[dev]"

ingest:
	$(RUN) -m reviewmate ingest data/samples

serve:
	$(RUN) -m uvicorn reviewmate.api:app --host 127.0.0.1 --port 8090

dev:
	$(RUN) -m uvicorn reviewmate.api:app --host 127.0.0.1 --port 8090 --reload

powercontext:
	mkdir -p data/powercontext
	POWERCONTEXT_SERVER_DATABASE_URL="sqlite+aiosqlite:////$(CURDIR)/data/powercontext/reviewmate.db" \
		powercontext server run --host 127.0.0.1 --port 8100

verify:
	$(RUN) scripts/verify.py

test:
	$(RUN) -m pytest

lint:
	.venv/bin/ruff check .

clean:
	rm -rf data/seekdb data/powercontext data/verification
