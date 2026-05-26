# Boat Storage Facility Finder — Project Context

**For:** Claude Code  
**From:** Gizmo (OpenClaw) + Forge (systems/infra agent)  
**Date:** 2026-05-26  
**Status:** Ready to implement

---

## The Idea

A commercial real estate investor wants to find warehouse/industrial properties in Pinellas County, FL that could be converted to **high-and-dry boat storage** facilities (forklift-racking model). The proof of concept: someone bought a ~100k sqft Oklahoma warehouse, converted it to boat storage, now generating $40k/month.

The tool identifies and ranks candidate properties using spatial data — proximity to navigable water, boat ramp density, marina density, parcel size, zoning, and boater demographics.

---

## What's Already Done

Forge (the architecture agent) has produced complete requirements and architecture documents:

- **`docs/requirements.md`** — problem statement, user stories, all functional/non-functional requirements, data sources with exact URLs, FL DOR land use codes, success criteria
- **`docs/architecture.md`** — full system design: PostgreSQL + PostGIS schema (8 tables), pipeline architecture diagram, data source evaluation with URLs and formats, scoring model (7 components), tech stack recommendations, Crexi/LoopNet reality check

**Read both docs before writing any code.**

---

## Tech Stack

- **Language:** Python (Chris is a Staff SWE, Python-primary)
- **Database:** PostgreSQL + PostGIS
- **Key libraries:** `geopandas`, `shapely`, `psycopg2`/`asyncpg`, `SQLAlchemy`, `alembic`, `fiona`, `pyproj`, `requests`, `pdfplumber`
- **Dev setup:** Docker for PostgreSQL + PostGIS locally
- **Orchestration:** `Makefile` + shell scripts, cron for automation
- **No web UI for v1** — CLI + CSV/GeoJSON exports

---

## Project Structure

```
/ai_bots/real_estate/
├── CONTEXT.md          ← you are here
├── docs/
│   ├── requirements.md
│   └── architecture.md
├── src/                ← all Python code goes here
│   ├── ingest/         ← one script per data source
│   ├── processing/     ← filter, proximity, scoring
│   └── export/         ← CSV, GeoJSON, reports
├── data/
│   ├── raw/            ← downloaded source files (gitignored)
│   └── processed/      ← intermediate spatial files
├── output/             ← timestamped report runs
├── migrations/         ← Alembic schema versions
├── tests/
├── Makefile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Pilot Scope: Pinellas County, FL

- Pinellas County FIPS: **103**
- NHD HUC-8 region: **03090202** (Peace-Tampa Bay)
- Target DOR use codes: **48** (primary), 40, 41, 49 (secondary)
- Target zoning: M-1, M-2, IW, IL

---

## Where to Start

1. Read `docs/requirements.md` and `docs/architecture.md`
2. Run `/autoplan` to build the implementation plan
3. Start with: `docker-compose.yml` + `Makefile` + PostGIS schema (`migrations/`) + first ingestion script (`src/ingest/ingest_parcels.py` for PCPAO data)
4. Validate spatial setup works before building the full pipeline

---

## Key Risk to Watch

`TOT_LVG_AR` in the DOR NAL files is unreliable for commercial building square footage. You'll need the Pinellas County Property Appraiser's separate commercial tabular download for accurate sqft. Architecture doc covers this.

---

## Collaboration

- This folder (`/ai_bots/real_estate/`) is the shared workspace between OpenClaw and Claude Code
- Gizmo (OpenClaw) can read/write files here for coordination
- Write progress notes or blockers to `CONTEXT.md` or a new `STATUS.md` file as you go
- The `output/` directory is where human-readable results land — Gizmo will check there
