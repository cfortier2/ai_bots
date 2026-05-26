# Boat Storage Facility Finder — Requirements Document

**Project:** High-and-Dry Boat Storage Site Identification Tool  
**Pilot Market:** Pinellas County, Florida  
**Author:** Forge (systems/infra engineer)  
**Status:** v1 Draft  
**Date:** 2026-05-25

---

## 1. Problem Statement

Commercial real estate investors looking to acquire and convert warehouse/industrial properties into high-and-dry boat storage facilities (forklift-racking model) have no tooling to systematically identify candidate properties. The selection criteria are highly specific:

- Large footprint (50,000–200,000 sq ft under roof)
- Industrial/warehouse zoning or compatible use
- Proximity to navigable waterways popular with recreational boaters
- Located in high-boating-density markets
- Favorable acquisition price per square foot relative to revenue potential

The proof-of-concept benchmark is a ~100,000 sq ft Oklahoma warehouse converted to boat storage generating **$40,000/month** in revenue. The investor needs to find comparable opportunities in Pinellas County, FL—a peninsula market with among the highest recreational boat registration density in the United States.

Manual searching via LoopNet/Crexi is slow, doesn't incorporate spatial proximity data, and provides no scoring against boating demand signals. This tool automates that search and produces a ranked shortlist.

---

## 2. User Stories

### Primary User: Commercial Real Estate Investor

| ID | As a... | I want to... | So that... |
|----|---------|-------------|------------|
| US-01 | CRE investor | See a ranked list of warehouse/industrial parcels in Pinellas County sorted by boat storage conversion potential | I can focus due diligence on the highest-probability deals |
| US-02 | CRE investor | Know the proximity of each candidate to navigable waterways and boat ramps | I understand the operational context and boater demand proximity |
| US-03 | CRE investor | Filter candidates by building size (sq ft), lot size, and assessed value | I can narrow to deals that fit my capital stack |
| US-04 | CRE investor | See ownership information and assessed value for each candidate | I know who to contact and roughly what the deal might cost |
| US-05 | CRE investor | Get a map-ready export of candidates | I can visualize candidates spatially and share with a broker |
| US-06 | CRE investor | See the data refreshed automatically without manual intervention | I don't have to babysit the data pipeline daily |

### Secondary User: Broker / Analyst

| ID | As a... | I want to... | So that... |
|----|---------|-------------|------------|
| US-07 | Broker/analyst | Export candidates to CSV/GeoJSON | I can load them into my own GIS or CRM tool |
| US-08 | Analyst | Understand the scoring methodology | I can explain the ranking to the investor |

---

## 3. Functional Requirements

### FR-01: Parcel Ingestion
- Ingest all Pinellas County parcels from the PCPAO shapefile and DOR NAL file
- Store parcel polygon geometry, parcel ID (PIN/STRAP), owner name, mailing address, site address, building square footage, lot size, assessed value, land use code, and last sale price/date
- Must support incremental re-ingestion when source data is updated

### FR-02: Candidate Filtering
- Filter parcels to "candidate" set using the following criteria:
  - DOR use code is in the industrial/warehouse set (see Section 7 — Data Requirements)
  - Building size ≥ 40,000 sq ft **OR** lot size ≥ 2 acres (allow slightly under threshold to avoid missing conversions)
  - Parcel is in Pinellas County (FIPS 103)
- Store filtered candidates separately from raw parcel table for query performance

### FR-03: Water Proximity Analysis
- Ingest NHD waterbody geometries for the Tampa Bay area (HUC-8 region 03090202 — Peace-Tampa Bay)
- Compute the straight-line distance from each candidate parcel's centroid to the nearest NHD navigable waterbody (ocean, bay, river, large lake — exclude drainage ditches)
- Store computed distance as a column on the candidate record
- Flag parcels where any part of the parcel boundary is within 0.25 miles of navigable water

### FR-04: Boat Ramp Proximity Analysis
- Ingest FWC boat ramp locations (point geometries)
- For each candidate, compute:
  - Distance to nearest public boat ramp
  - Count of public boat ramps within 5 miles
- Store both values on the candidate record

### FR-05: Marina Density Analysis
- Ingest marina/boat storage locations from OpenStreetMap (Overpass API)
- For each candidate, compute count of marinas within 10-mile radius
- High marina density = high boater demand = good signal

### FR-06: Scoring
- Compute a composite **Boat Storage Potential Score** (0–100) for each candidate
- Score must be explainable: individual sub-scores stored per component (see Section 6 for scoring model detail)
- Re-score automatically when underlying data is refreshed

### FR-07: Output / Reporting
- Export ranked candidate list to:
  - CSV with all fields + score
  - GeoJSON (parcel polygon + all attributes) for map visualization
- Reports stored to a designated output directory with timestamp
- Human-readable summary: top 20 candidates with address, size, score, score breakdown, owner, assessed value, nearest water distance, nearest boat ramp distance

### FR-08: Pipeline Orchestration
- All pipeline stages must be runnable individually (for debugging) and as a full end-to-end pipeline
- Pipeline must be idempotent: re-running should not create duplicate records
- Logging to stdout + file for each pipeline run

### FR-09: Data Freshness Tracking
- Track the ingest timestamp and source file date for each data layer
- Surface staleness warnings in reports when data is older than configured threshold

---

## 4. Non-Functional Requirements

### NFR-01: Operational Overhead
- **Target: ≤ 1–2 hours of human attention per day** in steady state
- Automated daily pipeline runs via cron; human reviews output reports, not raw data
- Pipeline failures must be clearly logged and alertable (file-based alert or simple email notification)

### NFR-02: Runtime Performance
- Full pipeline (ingest + score + export) must complete within 30 minutes on a modern laptop or small VPS
- Pinellas County has ~400,000 parcels; the candidate set after filtering will be ~2,000–5,000 parcels — queries against the candidate set must complete in seconds

### NFR-03: Data Volume
- Total PostgreSQL database size estimated at 2–5 GB for Pinellas County scope
- NHD waterbody dataset for Florida subset: ~500 MB on disk, ~200 MB in DB
- System must support expansion to additional Florida counties without schema changes

### NFR-04: Reproducibility
- All data transformations must be deterministic given the same source data
- Schema migrations must be versioned (Alembic)

### NFR-05: Maintainability
- Codebase is maintained by a solo engineer with ~1–2 hours/day
- Pipeline stages are independent Python scripts, not a monolith
- Clear README with setup, run instructions, and data source refresh procedures

### NFR-06: Local Development
- Must run entirely on a developer laptop (macOS or Linux) with Docker for PostgreSQL/PostGIS
- No cloud dependency for core pipeline (cloud deployment optional)

### NFR-07: Data Privacy
- All data sources are public records or open datasets — no PII concerns beyond property owner names (public record in Florida)

---

## 5. Data Requirements

### 5.1 Core Data Sources

| Source | What We Need | Format | Freshness Needed |
|--------|-------------|--------|-----------------|
| Pinellas County Property Appraiser (PCPAO) | Parcel polygons, land use code, building sq ft, assessed value, owner, sale history | Shapefile + CSV | Annual (updated April–October) |
| Florida DOR NAL files | Parcel attributes statewide, land use codes, valuations | CSV (pipe-delimited) | Annual |
| FWC Boat Ramp data | Public boat ramp locations, capacity | ArcGIS REST / Shapefile | Annual |
| USGS NHD (National Hydrography Dataset) | Waterbody polygons — bays, rivers, lakes, coastline | Shapefile / GeoPackage | Stable (update ~annually) |
| OpenStreetMap (Overpass API) | Marina locations, amenity=marina tags | GeoJSON via API | Live / monthly refresh |
| FWC Registered Boat Counts | Registered boats per county (demand proxy) | PDF/HTML report | Annual |
| US Census ACS 5-Year | Household income by census tract (boating income-correlation) | API | Annual |

### 5.2 Florida DOR Land Use Codes (Target Set)

Florida DOR uses a two-digit numeric code for property use. For this project, candidates must match one or more of:

| Code | Description | Priority |
|------|-------------|----------|
| 48 | Warehousing, distribution terminals, trucking terminals, van and storage warehousing | **PRIMARY** |
| 40 | Vacant industrial | High (greenfield conversion) |
| 41 | Light manufacturing | High |
| 42 | Heavy industrial | Medium (may have remediation issues) |
| 49 | Open storage | Medium (large lot, buildable) |
| 91 | Utility, gas & electric (retired plants) | Low (opportunistic) |
| 39 | Hotels/motels (large footprint near water) | Low |

Code 48 is the bullseye. Codes 40, 41, 49 are the secondary sweep.

### 5.3 Pinellas County Zoning Cross-Reference

Pinellas County zoning districts compatible with boat storage operations:

| Zoning Code | Description |
|-------------|-------------|
| M-1 | Light manufacturing/warehouse |
| M-2 | General industrial |
| IW | Industrial warehouse (unincorporated Pinellas) |
| IL | Light industrial |
| CG / CG-1 | General commercial (marinas often here) |

Municipalities within Pinellas (Clearwater, St. Pete, Largo, Dunedin, etc.) have their own zoning codes — cross-reference required at offer stage, not filtering stage.

### 5.4 Data Access Notes

- PCPAO shapefiles: publicly downloadable, no auth required — `https://www.pcpao.gov/tools-data/maps-gis/shape-files`
- DOR NAL files: free download at `https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx`; Pinellas County file is `~103_NAL.zip`; FTP mirror at `ftp://sdrftp03.dor.state.fl.us/`
- FGDL statewide parcels (alternative): `https://fgdl.org` — includes polygon + NAL join in one ESRI geodatabase (GDB format, 2021 vintage available)
- FWC: `https://geodata.myfwc.com/arcgis/rest/services/` — query boat ramp feature service by county
- USGS NHD: download via TNM API — `https://tnmaccess.nationalmap.gov/api/v1/products?datasets=National%20Hydrography%20Dataset%20(NHD)%20Best%20Resolution&bbox={west,south,east,north}&outputFormat=JSON`
- OSM Overpass: `https://overpass-api.de/api/interpreter` — query by bbox + amenity=marina

---

## 6. Out of Scope (v1)

The following are explicitly deferred to future versions:

| Item | Rationale |
|------|-----------|
| Live Crexi / LoopNet listings | No public API; scraping is legally and operationally risky (see architecture.md for honest assessment) |
| Multi-county coverage | Start with Pinellas, validate model before expanding |
| Web UI / dashboard | CLI + exported CSV/GeoJSON is sufficient for v1 investor workflow |
| Property contact automation | Reaching out to owners requires business process decisions beyond v1 |
| Revenue projection modeling | Requires local market rate data not yet sourced |
| Permitting / zoning feasibility check | Too manual; requires municipality-by-municipality research |
| Waterfront parcels with dock access | Important but requires additional data layers (FDEP submerged lands, dock permits) |
| Real-time MLS / CoStar data | Commercial data feed costs $500–$2000/month; not v1 |
| Mobile app | No mobile use case identified yet |
| User authentication | Single-user tool, no auth needed |

---

## 7. Success Criteria

V1 is successful when:

1. **Pipeline runs end-to-end without manual intervention** — `make run` completes in < 30 minutes on a developer laptop
2. **Candidate list is generated** — at least 20 warehouse/industrial parcels identified in Pinellas County meeting size and land use criteria
3. **Spatial scoring is correct** — manually verify 5 random candidates: their distance-to-water and ramp-proximity values match what a map check confirms
4. **Top 10 candidates are plausible** — investor reviews the top 10 and at least 7 are considered "worth a second look" based on their domain knowledge
5. **Data is fresh and traceable** — every record in the output can be traced to its source data file and ingest timestamp
6. **Export formats work** — CSV opens cleanly in Excel; GeoJSON renders correctly in QGIS or kepler.gl

---

*Next: see `architecture.md` for system design, schema, pipeline, and tech stack.*
