# Makefile — every run command for Test by Token lives here.
#
# services/api (FastAPI + Playwright) and services/engine (Flask-era UTS core,
# Selenium) keep PERMANENTLY SEPARATE virtualenvs. Selenium and Playwright must
# never share a process — see tbt_api/engines/uts_workspace.py and CLAUDE.md §5.
# Every target below runs each service's own .venv explicitly; none of them
# ever activates one venv and then touches the other service's code.

SHELL := /bin/bash

# This machine's Homebrew Python 3.12 has a broken pyexpat/libexpat link.
# This works around it for every venv-creation and run target below; it is a
# no-op (just an unused extra library path) on a machine that doesn't need it.
export DYLD_LIBRARY_PATH := /opt/homebrew/opt/expat/lib:$(DYLD_LIBRARY_PATH)

PYTHON ?= /opt/homebrew/bin/python3.12

API_DIR := services/api
ENGINE_DIR := services/engine
WEB_DIR := services/web

API_PY := $(API_DIR)/.venv/bin/python
ENGINE_PY := $(ENGINE_DIR)/.venv/bin/python

.PHONY: setup-api setup-engine api web engine-scan engine-run test clean

setup-api:
	$(PYTHON) -m venv $(API_DIR)/.venv
	$(API_PY) -m pip install --upgrade pip
	$(API_PY) -m pip install -r $(API_DIR)/requirements.txt
	$(API_PY) -m playwright install chromium

setup-engine:
	$(PYTHON) -m venv $(ENGINE_DIR)/.venv
	$(ENGINE_PY) -m pip install --upgrade pip
	$(ENGINE_PY) -m pip install -r $(ENGINE_DIR)/requirements.txt

# NOT port 8000 — docs/SETUP.md is stale, the real port is 8001.
api:
	cd $(API_DIR) && .venv/bin/python -m uvicorn tbt_api.main:app --reload --port 8001

web:
	python3 -m http.server 5500 --directory $(WEB_DIR)

# Cycle 1: login + crawl + list modules, no test cases yet.
engine-scan:
	cd $(ENGINE_DIR) && .venv/bin/python -m uts_engine.cli --scan-only

# Cycle 2: generate test cases for config/app-input.json's "module" and run them.
engine-run:
	cd $(ENGINE_DIR) && .venv/bin/python -m uts_engine.cli --run

test:
	cd $(API_DIR) && .venv/bin/python -m pytest tests -q
	cd $(ENGINE_DIR) && .venv/bin/python -m pytest tests -q

clean:
	rm -rf $(API_DIR)/.venv $(ENGINE_DIR)/.venv
	rm -rf $(API_DIR)/shots
	rm -rf $(ENGINE_DIR)/generated $(ENGINE_DIR)/reports $(ENGINE_DIR)/logs \
	       $(ENGINE_DIR)/manual-tests $(ENGINE_DIR)/alm-output $(ENGINE_DIR)/xpedite-output
	find . -name "__pycache__" -not -path "./reference/*" -exec rm -rf {} + 2>/dev/null || true
