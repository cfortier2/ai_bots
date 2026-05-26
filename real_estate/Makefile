# ─────────────────────────────────────────────────────────────────────────────
# Boat Storage Facility Finder — Makefile
# ─────────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON := python
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
ALEMBIC := $(VENV)/bin/alembic

# Load .env if it exists (for make targets that need env vars)
-include .env
export

# ─── Help ─────────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "  Boat Storage Facility Finder"
	@echo "  ════════════════════════════"
	@echo ""
	@echo "  Setup:"
	@echo "    make venv           Create Python virtual environment + install deps"
	@echo "    make install        Install/upgrade dependencies"
	@echo ""
	@echo "  Database:"
	@echo "    make db-up          Start PostgreSQL+PostGIS container"
	@echo "    make db-down        Stop database container"
	@echo "    make db-reset       Stop, remove volume, restart, re-migrate"
	@echo "    make migrate        Run Alembic migrations (upgrade head)"
	@echo "    make db-shell       Open psql shell"
	@echo ""
	@echo "  Ingest:"
	@echo "    make ingest-parcels Download + load PCPAO parcel shapefile"
	@echo "    make ingest-water   Download + load NHD waterbodies/flowlines"
	@echo "    make ingest-ramps   Download + load FWC boat ramps"
	@echo "    make ingest-marinas Query OSM for marinas"
	@echo "    make ingest-all     Run all ingest stages"
	@echo ""
	@echo "  Processing:"
	@echo "    make score          Filter candidates + compute proximity + score"
	@echo ""
	@echo "  Export:"
	@echo "    make export         Export CSV + GeoJSON + summary report"
	@echo ""
	@echo "  Pipeline:"
	@echo "    make pipeline       Full end-to-end run"
	@echo ""
	@echo "  Testing:"
	@echo "    make test           Run test suite"
	@echo "    make test-smoke     Run smoke tests only (DB connection + PostGIS)"
	@echo ""

# ─── Setup ────────────────────────────────────────────────────────────────────
.PHONY: venv
venv:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt
	@echo "✓ venv ready — activate with: source $(VENV)/bin/activate"

.PHONY: install
install:
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt

# ─── Database ─────────────────────────────────────────────────────────────────
.PHONY: db-up
db-up:
	docker compose up -d db
	@echo "Waiting for PostGIS to be healthy..."
	@until docker compose exec db pg_isready -U $${POSTGRES_USER:-boat} -d $${POSTGRES_DB:-boat_storage_db} > /dev/null 2>&1; do \
		echo "  Still waiting..."; sleep 2; done
	@echo "✓ Database is ready"

.PHONY: db-down
db-down:
	docker compose stop db

.PHONY: db-reset
db-reset:
	docker compose down -v
	docker compose up -d db
	@echo "Waiting for PostGIS to be healthy..."
	@until docker compose exec db pg_isready -U $${POSTGRES_USER:-boat} -d $${POSTGRES_DB:-boat_storage_db} > /dev/null 2>&1; do \
		echo "  Still waiting..."; sleep 2; done
	@echo "✓ Database reset — running migrations..."
	@$(MAKE) migrate

.PHONY: migrate
migrate:
	@if [ ! -f $(ALEMBIC) ]; then \
		echo "ERROR: venv not found. Run: make venv"; exit 1; fi
	$(ALEMBIC) upgrade head
	@echo "✓ Migrations applied"

.PHONY: db-shell
db-shell:
	docker compose exec db psql -U $${POSTGRES_USER:-boat} -d $${POSTGRES_DB:-boat_storage_db}

# ─── Ingest ───────────────────────────────────────────────────────────────────
.PHONY: ingest-parcels
ingest-parcels:
	$(VENV_PYTHON) -m src.ingest.ingest_parcels

.PHONY: ingest-water
ingest-water:
	$(VENV_PYTHON) -m src.ingest.ingest_water

.PHONY: ingest-ramps
ingest-ramps:
	$(VENV_PYTHON) -m src.ingest.ingest_ramps

.PHONY: ingest-marinas
ingest-marinas:
	$(VENV_PYTHON) -m src.ingest.ingest_marinas

.PHONY: ingest-all
ingest-all: ingest-parcels ingest-water ingest-ramps ingest-marinas

# ─── Processing ───────────────────────────────────────────────────────────────
.PHONY: score
score:
	$(VENV_PYTHON) -m src.processing.filter_candidates
	$(VENV_PYTHON) -m src.processing.compute_proximity
	$(VENV_PYTHON) -m src.processing.score_candidates

# ─── Export ───────────────────────────────────────────────────────────────────
.PHONY: export
export:
	$(VENV_PYTHON) -m src.export.export_outputs

# ─── Full Pipeline ────────────────────────────────────────────────────────────
.PHONY: pipeline
pipeline: db-up migrate ingest-all score export
	@echo ""
	@echo "✓ Pipeline complete. Check output/ for results."

# ─── Tests ────────────────────────────────────────────────────────────────────
.PHONY: test
test:
	$(VENV_PYTHON) -m pytest tests/ -v --tb=short

.PHONY: test-smoke
test-smoke:
	$(VENV_PYTHON) -m pytest tests/test_smoke.py -v --tb=short

# ─── Utility ──────────────────────────────────────────────────────────────────
.PHONY: dirs
dirs:
	mkdir -p data/raw data/processed output logs

.PHONY: clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
