# Boat Storage Facility Finder — Architecture Design

**Project:** High-and-Dry Boat Storage Site Identification Tool  
**Pilot Market:** Pinellas County, Florida  
**Author:** Forge (systems/infra engineer)  
**Status:** v1 Draft  
**Date:** 2026-05-25

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES (external)                       │
│                                                                      │
│  PCPAO Shapefile   DOR NAL CSV   FWC ArcGIS   NHD Shapefile  OSM   │
│  (parcels+geo)     (attributes)  (boat ramps)  (water bodies) (marinas)│
└──────┬─────────────────┬──────────────┬──────────────┬──────────┬───┘
       │                 │              │              │          │
       ▼                 ▼              ▼              ▼          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     INGESTION LAYER (Python scripts)                 │
│                                                                      │
│  ingest_parcels.py  ingest_nal.py  ingest_ramps.py  ingest_nhd.py  │
│  ingest_marinas.py  ingest_census.py                                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  writes to
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     PostgreSQL + PostGIS Database                     │
│                                                                      │
│  raw.parcels_raw   raw.nal_raw    geo.water_bodies  geo.boat_ramps  │
│  geo.marinas       ref.land_use_codes               ref.census_acs  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  reads from / writes to
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     PROCESSING LAYER (Python + PostGIS SQL)          │
│                                                                      │
│  filter_candidates.py   compute_proximity.py   score_candidates.py   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  writes to
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     OUTPUT LAYER                                      │
│                                                                      │
│  candidates table      scored_candidates view                         │
│  export_csv.py         export_geojson.py    generate_report.py       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  writes to
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  output/YYYY-MM-DD/                                                  │
│  ├── candidates_ranked.csv                                           │
│  ├── candidates.geojson                                              │
│  └── summary_report.txt                                              │
└─────────────────────────────────────────────────────────────────────┘
```

**Orchestration:** A single `Makefile` + shell script (`run_pipeline.sh`) chains the stages. A cron job on the host calls `run_pipeline.sh` daily or weekly depending on data source update frequency.

---

## 2. Data Sources

### 2.1 Pinellas County Property Appraiser (PCPAO)

| Attribute | Detail |
|-----------|--------|
| **URL** | `https://www.pcpao.gov/tools-data/maps-gis/shape-files` |
| **What it provides** | Parcel polygon geometries; parcel ID fields (PARCELNO, PARCEL_ID, STRAP, PARCELID) for joining to DOR NAL; parcel boundaries are the authoritative spatial layer |
| **Access method** | Direct download (zip containing shapefile). Page has links to the most recent polygon shapefile and point shapefile. No API/token required. |
| **Format** | ESRI Shapefile (NAD83 HARN State Plane Florida West, WKID 2882 / EPSG:2882). Reproject to EPSG:4326 on ingest. |
| **Update frequency** | Updated throughout the year; major refresh in May (after April 1 DOR submission deadline). Check `Last Modified` date on download page. |
| **Key fields** | `PARCELNO` (links to DOR map data), `PARCEL_ID` (links to NAL/SDF tabular), `STRAP` (links to PAO tabular downloads) |
| **Pinellas note** | This is county-specific — only covers Pinellas parcels. ~400,000 parcels total. |

### 2.2 Florida DOR NAL Files (Name–Address–Legal)

| Attribute | Detail |
|-----------|--------|
| **URL** | `https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx` |
| **FTP mirror** | `ftp://sdrftp03.dor.state.fl.us/Tax Roll Data/` |
| **What it provides** | Tabular parcel attributes: owner name, mailing address, site address, land use code (DOR use code 00–99), building sq ft, lot size, just value, assessed value, taxable value, most recent sale price + date |
| **Access method** | Free download. Pinellas County file is county code 103. File pattern: `103_NAL.zip`. Contains pipe-delimited ("|") flat file. No API; bulk download only. |
| **Format** | Pipe-delimited text, fixed field schema documented in DOR Users Guide PDF (linked on portal page) |
| **Update frequency** | Published July 1 (preliminary), October (initial final), post-certification (final). Use the October or final roll. |
| **Key fields** | `PARCEL_ID` (join key to PCPAO), `DOR_UC` (DOR use code — the land use classifier), `TOT_LVG_AR` (total living area / building sq ft for residential) — for commercial use `ACT_YR_BLT`, `NO_BULDNG`, `NO_RES_UNT`; look also at `SPEC_FEAT_VAL` for dock/water feature value |
| **Pinellas note** | Pinellas file is ~100 MB uncompressed. Full Florida NAL is ~4 GB — only download the 103 (Pinellas) county file for v1. |

### 2.3 FWC Boat Ramp Data

| Attribute | Detail |
|-----------|--------|
| **URL** | `https://geodata.myfwc.com/arcgis/rest/services/` |
| **Service path** | Look under `/fishing/` or `/recreation/` folder — historically the **Fishing Access** and **Boating Access** feature services. The primary endpoint is `https://geodata.myfwc.com/arcgis/rest/services/fishing/FWC_Fishing_Facilities/MapServer`. Layer 0 contains boat ramps. |
| **What it provides** | Public boat ramp point locations, facility name, county, ramp type (paved/unpaved), number of lanes, parking capacity |
| **Access method** | ArcGIS REST Feature Service. Query with `?f=json&where=COUNTY='PINELLAS'&outFields=*&returnGeometry=true`. No auth required. |
| **Format** | GeoJSON or Esri JSON via REST query |
| **Update frequency** | Infrequent (FWC updates as facilities change). Refresh annually. |
| **Pinellas note** | Pinellas has ~40–60 public boat ramps. Filter `COUNTY = 'PINELLAS'` or query by bounding box. |

**Fallback:** If the FWC ArcGIS service is down or restructured, query OSM Overpass for `leisure=slipway` within Pinellas County bounding box (see §2.6).

### 2.4 USGS NHD (National Hydrography Dataset)

| Attribute | Detail |
|-----------|--------|
| **URL** | `https://www.usgs.gov/national-hydrography/access-national-hydrography-products` |
| **TNM Download API** | `https://tnmaccess.nationalmap.gov/api/v1/products?datasets=National%20Hydrography%20Dataset%20(NHD)%20Best%20Resolution&bbox=-82.9,27.5,-82.2,28.1&outputFormat=JSON` |
| **Direct HUC download** | `https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/HU8/HighResolution/Shape/NHD_H_03090202_HU8_Shape.zip` — this is HUC-8 03090202 (Peace-Tampa Bay), which covers Pinellas County. |
| **What it provides** | `NHDWaterbody` layer: polygon geometries for bays, lakes, rivers, reservoirs, coastline. `NHDFlowline` layer: river/stream centerlines with navigability classification (FCode). |
| **Access method** | Direct S3 download (no auth). The HUC-8 zip is ~50–100 MB. |
| **Format** | Shapefile (ESRI NAD83 geographic). Load `NHDWaterbody.shp` and `NHDFlowline.shp`. |
| **Key fields** | `FCode` (feature type code): 39004 = Bay/Estuary, 36100 = Lake/Pond, 46006 = Perennial stream. Filter to FCode values relevant to boating (exclude ephemeral streams, canals < 20ft wide, stormwater). |
| **Update frequency** | NHD Best Resolution is updated periodically. For v1, a one-time load is sufficient; re-load annually. |
| **Pinellas note** | Tampa Bay (FCode 39004) is the primary body. St. Johns River is HUC 03080103. Old Tampa Bay, Boca Ciega Bay, and the Gulf coastline all fall in 03090202. |

**NHD FCode reference for waterbody filtering:**

| FCode | FType | Keep? |
|-------|-------|-------|
| 39004 | Bay/Estuary | ✅ Yes |
| 39010 | Bay/Estuary with lock | ✅ Yes |
| 36100 | Lake/Pond (perennial) | ✅ Yes if area > 10 acres |
| 46006 | Stream/River (perennial) | ✅ Yes if Strahler order ≥ 4 |
| 46003 | Intermittent stream | ❌ No |
| 33600 | Canal/Ditch | ✅ Only if width estimate > 50 ft |
| 53700 | Playa | ❌ No |

### 2.5 NOAA Nautical Charts (Navigable Waterways)

| Attribute | Detail |
|-----------|--------|
| **URL** | `https://www.charts.noaa.gov/InteractiveCatalog/nrnc.shtml` |
| **ENC download** | `https://www.charts.noaa.gov/ENCs/` — Electronic Navigation Charts |
| **What it provides** | Authoritative navigable waterway polygons and depth contours. NOAA chart coverage for Pinellas is charts 11413 and 11416 (Tampa Bay, St. Petersburg area). |
| **Access method** | Free download (ENC format = ISO 8211). Parsing requires GDAL (`ogrinfo -al`) or `fiona`. Complex to work with. |
| **v1 recommendation** | **Defer.** Use NHD as the waterbody proxy for v1. NHD is sufficient to identify parcels adjacent to Tampa Bay and the Gulf. Add NOAA ENC in v2 to validate navigability depth. |
| **Format** | ISO 8211 / S-57 vector chart format |

### 2.6 OpenStreetMap (Marina & Waterway Data)

| Attribute | Detail |
|-----------|--------|
| **URL** | `https://overpass-api.de/api/interpreter` |
| **What it provides** | Marina locations (`amenity=marina`), boat storage (`leisure=boat_storage`), slipways (`leisure=slipway`), waterways (`waterway=*`) |
| **Access method** | Overpass QL query via HTTP POST. Free, no auth. Rate-limited — do not hammer it. |
| **Format** | JSON or GeoJSON output |
| **Example query (Pinellas County bbox):** | |

```
[out:json][timeout:60];
(
  node["amenity"="marina"](27.5,-82.9,28.1,-82.2);
  way["amenity"="marina"](27.5,-82.9,28.1,-82.2);
  node["leisure"="slipway"](27.5,-82.9,28.1,-82.2);
  node["leisure"="boat_storage"](27.5,-82.9,28.1,-82.2);
);
out body geom;
```

| **Update frequency** | Query fresh monthly. Store results to DB. |
| **Pinellas note** | OSM marina coverage in Pinellas is good (~80% of major facilities tagged). Supplement with FWC data. |

### 2.7 FWC Registered Boat Counts by County

| Attribute | Detail |
|-----------|--------|
| **URL** | `https://myfwc.com/boating/recreational-boating/annual-reports/` |
| **What it provides** | Annual count of registered recreational vessels by Florida county. Pinellas is typically in the top 5 statewide by count. |
| **Access method** | PDF report download. Extract via `pdfplumber` or `tabula-py`. |
| **Format** | PDF table. One-time manual extract is acceptable for v1 — store as a constant in a config file. |
| **Update frequency** | Annual. Use as a scalar multiplier in the county-level demand scoring. |
| **v1 handling** | Store as a config constant (`PINELLAS_REGISTERED_BOATS = 46000` — verify from latest report). |

### 2.8 US Census ACS (Income / Demographics)

| Attribute | Detail |
|-----------|--------|
| **URL** | `https://api.census.gov/data/2022/acs/acs5` |
| **What it provides** | Median household income by census tract (`B19013_001E`). Boating participation is correlated with income — use as a demand weight. |
| **Access method** | REST API, free, API key optional (register free at `api.census.gov`). Query by state (12 = Florida), county (103 = Pinellas), and tract. |
| **Format** | JSON |
| **Example query:** | `https://api.census.gov/data/2022/acs/acs5?get=NAME,B19013_001E&for=tract:*&in=state:12+county:103` |
| **Update frequency** | Annual (5-year ACS). Load once, refresh annually. |

---

## 3. Database Schema (PostgreSQL + PostGIS)

### 3.1 Schema Layout

```
boat_storage_db
├── raw          -- raw ingested data, minimal transformation
├── geo          -- spatial reference layers
├── ref          -- lookup/reference tables
└── public       -- processed candidates and scores
```

### 3.2 Table Definitions

#### `raw.parcels_geo`
Parcel polygons from PCPAO shapefile.

```sql
CREATE TABLE raw.parcels_geo (
    id              SERIAL PRIMARY KEY,
    parcelno        TEXT NOT NULL,        -- DOR map data join key
    parcel_id       TEXT NOT NULL,        -- NAL join key
    strap           TEXT,                 -- PAO tabular join key
    geom            GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    ingest_ts       TIMESTAMPTZ DEFAULT NOW(),
    source_file     TEXT                  -- filename of source shapefile
);

CREATE INDEX idx_parcels_geo_geom ON raw.parcels_geo USING GIST(geom);
CREATE INDEX idx_parcels_geo_parcel_id ON raw.parcels_geo(parcel_id);
CREATE INDEX idx_parcels_geo_parcelno ON raw.parcels_geo(parcelno);
```

#### `raw.nal_attributes`
DOR NAL file attributes, joined to parcels by `parcel_id`.

```sql
CREATE TABLE raw.nal_attributes (
    id              SERIAL PRIMARY KEY,
    parcel_id       TEXT NOT NULL,        -- join key to parcels_geo
    county_no       SMALLINT,             -- 103 = Pinellas
    dor_uc          SMALLINT,             -- DOR use code (land use)
    owner_name      TEXT,
    mail_addr1      TEXT,
    mail_addr2      TEXT,
    mail_city       TEXT,
    mail_state      CHAR(2),
    mail_zip        TEXT,
    site_addr       TEXT,
    site_city       TEXT,
    site_zip        TEXT,
    jv              NUMERIC(14,2),        -- just (market) value
    av_sd           NUMERIC(14,2),        -- assessed value (school district)
    tv_sd           NUMERIC(14,2),        -- taxable value
    lnd_val         NUMERIC(14,2),        -- land value
    bldg_val        NUMERIC(14,2),        -- building value
    tot_lvg_ar      INTEGER,              -- total living area sq ft
    no_buldng       SMALLINT,             -- number of buildings
    act_yr_blt      SMALLINT,             -- actual year built
    sale_prc        NUMERIC(14,2),        -- most recent sale price
    sale_yr         SMALLINT,
    sale_mo         SMALLINT,
    spec_feat_val   NUMERIC(14,2),        -- special features (dock, pool, etc.)
    lot_size        NUMERIC(12,2),        -- lot size in acres or sq ft (check DOR guide)
    ingest_ts       TIMESTAMPTZ DEFAULT NOW(),
    roll_year       SMALLINT,             -- NAL roll year
    roll_type       TEXT                  -- 'preliminary', 'initial_final', 'final'
);

CREATE INDEX idx_nal_parcel_id ON raw.nal_attributes(parcel_id);
CREATE INDEX idx_nal_dor_uc ON raw.nal_attributes(dor_uc);
```

#### `geo.water_bodies`
NHD waterbody polygons.

```sql
CREATE TABLE geo.water_bodies (
    id              SERIAL PRIMARY KEY,
    permanent_id    TEXT,                 -- NHD COMID / Permanent_Identifier
    fcode           INTEGER,              -- NHD FCode (39004 = bay, 36100 = lake, etc.)
    ftype           TEXT,                 -- FType description
    gnis_name       TEXT,                 -- geographic name (e.g. "Tampa Bay")
    area_sqkm       NUMERIC(12,4),
    geom            GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    navigable       BOOLEAN DEFAULT FALSE, -- computed flag: FCode in navigable set
    ingest_ts       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_water_bodies_geom ON geo.water_bodies USING GIST(geom);
CREATE INDEX idx_water_bodies_fcode ON geo.water_bodies(fcode);
CREATE INDEX idx_water_bodies_navigable ON geo.water_bodies(navigable);
```

#### `geo.boat_ramps`
FWC public boat ramp locations.

```sql
CREATE TABLE geo.boat_ramps (
    id              SERIAL PRIMARY KEY,
    facility_name   TEXT,
    county          TEXT,
    ramp_type       TEXT,                 -- paved, unpaved, concrete, etc.
    num_lanes       SMALLINT,
    parking_spaces  INTEGER,
    public_access   BOOLEAN DEFAULT TRUE,
    geom            GEOMETRY(POINT, 4326) NOT NULL,
    source          TEXT DEFAULT 'FWC',
    ingest_ts       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_boat_ramps_geom ON geo.boat_ramps USING GIST(geom);
CREATE INDEX idx_boat_ramps_county ON geo.boat_ramps(county);
```

#### `geo.marinas`
Marina/boat storage locations from OSM.

```sql
CREATE TABLE geo.marinas (
    id              SERIAL PRIMARY KEY,
    osm_id          BIGINT,
    osm_type        TEXT,                 -- 'node' or 'way'
    name            TEXT,
    amenity         TEXT,                 -- marina, boat_storage, slipway
    capacity        INTEGER,
    geom            GEOMETRY(POINT, 4326) NOT NULL,
    source          TEXT DEFAULT 'OSM',
    ingest_ts       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_marinas_geom ON geo.marinas USING GIST(geom);
```

#### `geo.census_tracts`
ACS census tracts with income data.

```sql
CREATE TABLE geo.census_tracts (
    id              SERIAL PRIMARY KEY,
    geoid           TEXT UNIQUE NOT NULL, -- 11-digit FIPS tract ID
    name            TEXT,
    county_fips     TEXT,
    median_hh_income  INTEGER,            -- B19013_001E
    acs_year        SMALLINT,
    geom            GEOMETRY(MULTIPOLYGON, 4326),
    ingest_ts       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_census_geom ON geo.census_tracts USING GIST(geom);
```

#### `ref.dor_use_codes`
Reference table for DOR land use codes.

```sql
CREATE TABLE ref.dor_use_codes (
    code            SMALLINT PRIMARY KEY,
    description     TEXT NOT NULL,
    category        TEXT,           -- 'residential', 'commercial', 'industrial', 'agricultural', 'vacant'
    candidate_tier  SMALLINT        -- 1=primary, 2=secondary, NULL=not a candidate
);

-- Seed data (partial):
INSERT INTO ref.dor_use_codes VALUES
  (48, 'Warehousing, distribution terminals, trucking terminals, van and storage warehousing', 'industrial', 1),
  (40, 'Vacant industrial', 'industrial', 2),
  (41, 'Light manufacturing', 'industrial', 2),
  (42, 'Heavy industrial', 'industrial', 2),
  (49, 'Open storage', 'industrial', 2),
  (91, 'Utility, gas & electric', 'utility', 3);
```

#### `public.candidates`
Filtered candidate parcels — the working set for scoring.

```sql
CREATE TABLE public.candidates (
    id                  SERIAL PRIMARY KEY,
    parcel_id           TEXT NOT NULL UNIQUE,
    parcelno            TEXT,
    strap               TEXT,

    -- Identity
    site_addr           TEXT,
    site_city           TEXT,
    site_zip            TEXT,
    owner_name          TEXT,

    -- Property attributes
    dor_uc              SMALLINT,
    use_desc            TEXT,
    building_sqft       INTEGER,
    lot_size_acres      NUMERIC(10,4),
    year_built          SMALLINT,
    no_buildings        SMALLINT,

    -- Financials
    just_value          NUMERIC(14,2),
    assessed_value      NUMERIC(14,2),
    land_value          NUMERIC(14,2),
    bldg_value          NUMERIC(14,2),
    last_sale_price     NUMERIC(14,2),
    last_sale_year      SMALLINT,
    spec_feat_value     NUMERIC(14,2),   -- dock/water features already priced in

    -- Geometry
    geom                GEOMETRY(MULTIPOLYGON, 4326),
    centroid            GEOMETRY(POINT, 4326),

    -- Proximity (computed by compute_proximity.py)
    dist_to_water_m         NUMERIC(10,2),  -- meters to nearest navigable waterbody edge
    dist_to_ramp_m          NUMERIC(10,2),  -- meters to nearest public boat ramp
    boat_ramps_5mi          SMALLINT,       -- count of ramps within 5 miles
    marinas_10mi            SMALLINT,       -- count of marinas within 10 miles
    nearest_water_name      TEXT,
    nearest_ramp_name       TEXT,
    parcel_touches_water    BOOLEAN,        -- parcel boundary within 400m of navigable water
    median_hh_income        INTEGER,        -- from census tract containing centroid

    -- Scoring (computed by score_candidates.py)
    score_total             NUMERIC(5,2),
    score_size              NUMERIC(5,2),
    score_water_proximity   NUMERIC(5,2),
    score_ramp_access       NUMERIC(5,2),
    score_marina_density    NUMERIC(5,2),
    score_land_use          NUMERIC(5,2),
    score_income            NUMERIC(5,2),
    score_value             NUMERIC(5,2),

    -- Metadata
    scored_at           TIMESTAMPTZ,
    ingest_ts           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_candidates_geom ON public.candidates USING GIST(geom);
CREATE INDEX idx_candidates_score ON public.candidates(score_total DESC);
CREATE INDEX idx_candidates_dor_uc ON public.candidates(dor_uc);
CREATE INDEX idx_candidates_building_sqft ON public.candidates(building_sqft);
```

### 3.3 Relationships

```
raw.parcels_geo    ──[parcel_id]──>  raw.nal_attributes
raw.nal_attributes ──[dor_uc]──>    ref.dor_use_codes
raw.parcels_geo    ──[parcel_id]──>  public.candidates   (filtered subset)
public.candidates  ──[spatial]──>    geo.water_bodies    (PostGIS ST_Distance)
public.candidates  ──[spatial]──>    geo.boat_ramps      (PostGIS ST_Distance)
public.candidates  ──[spatial]──>    geo.marinas         (PostGIS ST_DWithin)
public.candidates  ──[spatial]──>    geo.census_tracts   (PostGIS ST_Within)
```

---

## 4. PostGIS Strategy

### 4.1 Key Spatial Queries

**Distance to nearest navigable waterbody (run once per candidate after ingest):**
```sql
UPDATE public.candidates c
SET
    dist_to_water_m = sub.dist_m,
    nearest_water_name = sub.gnis_name
FROM (
    SELECT DISTINCT ON (c.id)
        c.id,
        ST_Distance(
            c.centroid::geography,
            ST_ExteriorRing(w.geom::geometry)::geography
        ) AS dist_m,
        w.gnis_name
    FROM public.candidates c
    CROSS JOIN LATERAL (
        SELECT geom, gnis_name
        FROM geo.water_bodies
        WHERE navigable = TRUE
        ORDER BY c.centroid <-> geom
        LIMIT 5
    ) w
    ORDER BY c.id, ST_Distance(c.centroid::geography, ST_ExteriorRing(w.geom::geometry)::geography)
) sub
WHERE c.id = sub.id;
```

**Count boat ramps within 5 miles (8047 meters):**
```sql
UPDATE public.candidates c
SET boat_ramps_5mi = (
    SELECT COUNT(*)
    FROM geo.boat_ramps r
    WHERE ST_DWithin(c.centroid::geography, r.geom::geography, 8047)
);
```

**Count marinas within 10 miles (16093 meters):**
```sql
UPDATE public.candidates c
SET marinas_10mi = (
    SELECT COUNT(*)
    FROM geo.marinas m
    WHERE ST_DWithin(c.centroid::geography, m.geom::geography, 16093)
);
```

**Flag parcels whose boundary is within 400m of navigable water:**
```sql
UPDATE public.candidates c
SET parcel_touches_water = EXISTS (
    SELECT 1
    FROM geo.water_bodies w
    WHERE w.navigable = TRUE
    AND ST_DWithin(c.geom::geography, w.geom::geography, 400)
);
```

**Census tract income lookup:**
```sql
UPDATE public.candidates c
SET median_hh_income = t.median_hh_income
FROM geo.census_tracts t
WHERE ST_Within(c.centroid, t.geom);
```

### 4.2 Performance Notes

- All spatial queries use `::geography` cast for accurate meter-based distances (WGS84 ellipsoid math). This is slower than `::geometry` with a projected CRS but avoids reprojection complexity and is accurate enough at county scale.
- Add GIST indexes on all geometry columns before running proximity updates.
- Run proximity updates in a single transaction per batch of candidates (not row-by-row).
- For the `CROSS JOIN LATERAL ... ORDER BY centroid <-> geom LIMIT 5` pattern, the `<->` KNN operator uses the GIST index efficiently — this is O(n log n) not O(n²).
- Total candidate set is ~2,000–5,000 parcels; proximity computation completes in under 2 minutes on a laptop.

### 4.3 Projection Strategy

- **Storage:** All geometry stored in EPSG:4326 (WGS84 geographic) for compatibility and easy GeoJSON export.
- **Computation:** Use `::geography` for distance calculations to get accurate meters without reprojection.
- **Ingestion:** PCPAO shapefile arrives in EPSG:2882 (NAD83 HARN State Plane Florida West, feet). Reproject during load with `geopandas`: `gdf.to_crs(epsg=4326)`.

---

## 5. Pipeline Architecture

### 5.1 Stage Map

```
Stage 0: setup_db.py
  - Create schemas (raw, geo, ref, public)
  - Run Alembic migrations
  - Populate ref.dor_use_codes

Stage 1: ingest_parcels.py
  - Download PCPAO shapefile (if not cached or stale)
  - Reproject EPSG:2882 -> 4326
  - Upsert into raw.parcels_geo on parcel_id
  - Compute centroid and store

Stage 2: ingest_nal.py
  - Download DOR NAL 103_NAL.zip (if not cached or stale)
  - Parse pipe-delimited file
  - Upsert into raw.nal_attributes on parcel_id

Stage 3: ingest_nhd.py
  - Download NHD HUC-8 03090202 zip (if not cached)
  - Load NHDWaterbody.shp into geo.water_bodies
  - Set navigable=TRUE for FCode in (39004, 39010, 36100, 46006) filtered by area/order

Stage 4: ingest_ramps.py
  - Query FWC ArcGIS REST for Pinellas County boat ramps
  - Upsert into geo.boat_ramps

Stage 5: ingest_marinas.py
  - Query OSM Overpass for Pinellas bbox
  - Upsert into geo.marinas

Stage 6: ingest_census.py
  - Query Census ACS API for Pinellas tract incomes
  - Load TIGER/Line census tract shapefile (EPSG:4326)
  - Upsert into geo.census_tracts

Stage 7: filter_candidates.py
  - JOIN raw.parcels_geo + raw.nal_attributes on parcel_id
  - Filter: dor_uc IN (48, 40, 41, 42, 49, 91) AND building_sqft >= 40000 OR lot_size_acres >= 2.0
  - INSERT or REPLACE into public.candidates

Stage 8: compute_proximity.py
  - For each candidate: compute dist_to_water_m, dist_to_ramp_m, boat_ramps_5mi, marinas_10mi, parcel_touches_water, median_hh_income
  - Uses batched PostGIS UPDATE queries (not row-by-row Python loops)

Stage 9: score_candidates.py
  - Read candidates with proximity data
  - Compute sub-scores and total score
  - UPDATE public.candidates with score fields

Stage 10: export_outputs.py
  - Export CSV: sorted by score_total DESC
  - Export GeoJSON: candidates with all attributes
  - Write summary_report.txt: top 20 candidates, human-readable

Stage 11: validate.py  (optional but recommended)
  - Spot-check: assert candidate count > 0
  - Assert score distribution makes sense (no all-zeros)
  - Assert top candidate has non-null geometry
  - Log PASS/FAIL to stdout
```

### 5.2 Orchestration Script

```bash
# run_pipeline.sh
#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="logs/$(date +%Y-%m-%d)"
mkdir -p "$LOG_DIR"

run_stage() {
    local stage=$1
    echo "[$(date -u +%H:%M:%S)] Starting $stage"
    python -m pipeline.$stage 2>&1 | tee "$LOG_DIR/${stage}.log"
    echo "[$(date -u +%H:%M:%S)] Done $stage"
}

run_stage ingest_parcels
run_stage ingest_nal
run_stage ingest_nhd
run_stage ingest_ramps
run_stage ingest_marinas
run_stage ingest_census
run_stage filter_candidates
run_stage compute_proximity
run_stage score_candidates
run_stage export_outputs
run_stage validate

echo "Pipeline complete. Output: output/$(date +%Y-%m-%d)/"
```

### 5.3 Cron Schedule

```cron
# Run full pipeline weekly on Sunday at 2:00 AM
0 2 * * 0 /home/user/boat-storage-finder/run_pipeline.sh >> /home/user/boat-storage-finder/logs/cron.log 2>&1

# Re-score only (no ingest) daily at 6:00 AM (if you tweak the scoring model)
# 0 6 * * * python -m pipeline.score_candidates && python -m pipeline.export_outputs
```

Data sources update annually (PCPAO, DOR NAL) or infrequently (NHD, FWC ramps). Weekly pipeline runs are sufficient; only the OSM marina data benefits from more frequent refresh.

---

## 6. Scoring Model

Each candidate receives a composite score 0–100. Sub-scores are weighted and capped; the final score is a weighted sum.

### 6.1 Sub-Scores and Weights

| Sub-Score | Weight | What it measures |
|-----------|--------|-----------------|
| `score_size` | 25% | Building sq ft — are we in the 50k–200k sweet spot? |
| `score_water_proximity` | 30% | Distance from parcel to nearest navigable waterbody |
| `score_ramp_access` | 20% | Nearest boat ramp distance + ramp count within 5 miles |
| `score_marina_density` | 10% | Marina count within 10 miles (demand proxy) |
| `score_land_use` | 8% | DOR use code tier (48 > 40/41 > 42/49) |
| `score_income` | 4% | Median household income of surrounding census tract |
| `score_value` | 3% | Land value per acre (inverse: cheaper is better for ROI) |

### 6.2 Scoring Functions

**score_size (25 points max):**
```python
def score_size(sqft: int) -> float:
    """Sweet spot: 50,000–200,000 sqft. Penalty outside range."""
    if sqft is None or sqft <= 0:
        return 0.0
    if 50_000 <= sqft <= 200_000:
        return 25.0
    elif 40_000 <= sqft < 50_000:
        return 20.0  # slightly under threshold, still viable
    elif 200_000 < sqft <= 300_000:
        return 18.0  # big but possibly multi-tenant / subdivision play
    elif sqft > 300_000:
        return 10.0  # very large, capital intensive
    elif 25_000 <= sqft < 40_000:
        return 10.0  # small, risky
    else:
        return 0.0
```

**score_water_proximity (30 points max):**
```python
def score_water_proximity(dist_m: float, touches_water: bool) -> float:
    """Distance to nearest navigable waterbody edge."""
    if touches_water:
        return 30.0  # parcel boundary within 400m of water — premium
    if dist_m is None:
        return 0.0
    if dist_m <= 400:
        return 28.0
    elif dist_m <= 800:   # ~0.5 miles
        return 22.0
    elif dist_m <= 1600:  # ~1 mile
        return 16.0
    elif dist_m <= 3200:  # ~2 miles
        return 10.0
    elif dist_m <= 8000:  # ~5 miles
        return 5.0
    else:
        return 0.0
```

**score_ramp_access (20 points max):**
```python
def score_ramp_access(nearest_ramp_m: float, ramps_within_5mi: int) -> float:
    """Nearest ramp proximity + density."""
    if nearest_ramp_m is None:
        return 0.0
    # Nearest ramp: 0–12 points
    if nearest_ramp_m <= 1600:    # within 1 mile
        prox = 12.0
    elif nearest_ramp_m <= 4800:  # within 3 miles
        prox = 8.0
    elif nearest_ramp_m <= 8000:  # within 5 miles
        prox = 4.0
    else:
        prox = 0.0
    # Ramp count: 0–8 points
    density = min(ramps_within_5mi * 2.0, 8.0)
    return prox + density
```

**score_marina_density (10 points max):**
```python
def score_marina_density(marinas_10mi: int) -> float:
    return min(marinas_10mi * 1.25, 10.0)
```

**score_land_use (8 points max):**
```python
TIER_SCORES = {1: 8.0, 2: 5.0, 3: 2.0}

def score_land_use(dor_uc: int, tier: int) -> float:
    return TIER_SCORES.get(tier, 0.0)
```

**score_income (4 points max):**
```python
def score_income(median_hh_income: int) -> float:
    """Higher income areas = more boaters."""
    if median_hh_income is None:
        return 2.0  # neutral
    if median_hh_income >= 80_000:
        return 4.0
    elif median_hh_income >= 60_000:
        return 3.0
    elif median_hh_income >= 45_000:
        return 2.0
    else:
        return 1.0
```

**score_value (3 points max):**
```python
def score_value(land_value: float, lot_size_acres: float) -> float:
    """Lower land value per acre = better acquisition economics."""
    if not land_value or not lot_size_acres or lot_size_acres == 0:
        return 1.5  # neutral
    price_per_acre = land_value / lot_size_acres
    if price_per_acre < 100_000:
        return 3.0
    elif price_per_acre < 250_000:
        return 2.0
    elif price_per_acre < 500_000:
        return 1.0
    else:
        return 0.0  # too expensive per acre
```

### 6.3 Total Score Calculation

```python
def compute_total_score(candidate: dict) -> dict:
    scores = {
        'score_size':            score_size(candidate['building_sqft']),
        'score_water_proximity': score_water_proximity(candidate['dist_to_water_m'], candidate['parcel_touches_water']),
        'score_ramp_access':     score_ramp_access(candidate['dist_to_ramp_m'], candidate['boat_ramps_5mi']),
        'score_marina_density':  score_marina_density(candidate['marinas_10mi']),
        'score_land_use':        score_land_use(candidate['dor_uc'], candidate['land_use_tier']),
        'score_income':          score_income(candidate['median_hh_income']),
        'score_value':           score_value(candidate['land_value'], candidate['lot_size_acres']),
    }
    scores['score_total'] = sum(scores.values())  # max possible: 100
    return scores
```

### 6.4 Score Interpretation

| Range | Interpretation |
|-------|---------------|
| 75–100 | Exceptional — worth immediate investigation |
| 55–74 | Strong candidate — put on shortlist |
| 35–54 | Moderate — review if shortlist is thin |
| < 35 | Weak — probably not worth pursuing |

---

## 7. Crexi / LoopNet Reality Check

**Short answer:** There are no public APIs. Do not build around scraping these platforms for v1.

### 7.1 The Honest Situation

| Platform | API Status | Scraping Viability | Cost |
|----------|-----------|-------------------|------|
| Crexi | No public API. Has a private API used by their own front-end. | Technically possible with Playwright; ToS prohibits it; IP ban risk is high; data structure changes break scrapers | N/A |
| LoopNet | No public API. CoStar-owned. | Same issues as Crexi. CoStar aggressively detects and blocks scrapers. | N/A |
| CoStar | Has a data licensing API | Only available to licensed CoStar subscribers | $2,000–5,000+/month |

### 7.2 Why Not Scrape?

1. **ToS violation** — both platforms explicitly prohibit scraping in their terms. Legal risk for a commercial application.
2. **Fragility** — CRE platforms change their front-end constantly. A scraper is a maintenance tax.
3. **IP bans** — CoStar/LoopNet actively fingerprint and ban scrapers within hours.
4. **Not needed for v1** — the investor's use case is to *find the property first*, then verify it on LoopNet/Crexi manually. The tool's job is candidate identification from public data.

### 7.3 What We Can Do Instead

**Option A: County Tax Data as CRE Proxy (recommended for v1)**  
The DOR NAL + PCPAO data contains everything LoopNet has for industrial properties *except* active listing price. Assessed value is a reasonable proxy for market value. We know the owner, we know the building, we know the history.

**Option B: Commercial Listing APIs (v2)**  
- **Reonomy** (now part of CoStar) — has an API for property intelligence: `https://app.reonomy.com/api` — pricing around $500–1500/month for API access.
- **ATTOM Data** — property data aggregator with API: `https://api.attomdata.com/` — has trial tier.
- **Regrid** — parcel data API including Pinellas County: `https://regrid.com/api` — $200–500/month depending on volume. Good option for enrichment.

**Option C: Manual Crexi/LoopNet Export (v1.5)**  
Export search results from Crexi to CSV manually (Crexi has a "Save Search" + CSV export for logged-in users). Import that CSV into the DB, match on address to join Crexi listing data with our parcel scores. Low-tech but zero risk.

**v1 Recommendation:** Use Option A entirely. Build the scoring pipeline on public data. Once the model is validated, evaluate Option B for active listing price enrichment.

---

## 8. Tech Stack

### 8.1 Python Libraries

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `geopandas` | ≥ 0.14 | Read/write shapefiles, spatial joins, reprojection | Industry standard for vector GIS in Python |
| `shapely` | ≥ 2.0 | Geometry operations (buffering, intersections) | geopandas dependency; use directly for geometry construction |
| `fiona` | ≥ 1.9 | Read/write OGR-supported formats (shapefile, GeoPackage) | Low-level format access when geopandas overhead is excessive |
| `pyproj` | ≥ 3.6 | CRS transformations | Required by geopandas; use for manual reprojection |
| `psycopg2-binary` | ≥ 2.9 | PostgreSQL adapter | Use `psycopg2` (sync) not `asyncpg` — pipeline is batch, not concurrent |
| `sqlalchemy` | ≥ 2.0 | ORM + query builder + connection pooling | Use Core (not ORM) for bulk operations; ORM for simple lookups |
| `geoalchemy2` | ≥ 0.14 | SQLAlchemy extension for PostGIS geometry types | Handles WKB serialization to/from PostGIS |
| `alembic` | ≥ 1.13 | Schema migrations | Version-controlled schema changes |
| `requests` | ≥ 2.31 | HTTP client for REST APIs (FWC, Census, Overpass) | Simple and reliable for synchronous HTTP |
| `httpx` | ≥ 0.27 | Alternative HTTP client with timeout control | Use for large file downloads with progress |
| `pandas` | ≥ 2.1 | NAL CSV parsing, data manipulation | DOR NAL files are large CSVs; pandas handles them well |
| `pdfplumber` | ≥ 0.10 | Extract FWC boat registration count tables from PDFs | Better than tabula-py for complex PDF layouts |
| `click` | ≥ 8.1 | CLI interface for pipeline stages | Clean `--dry-run`, `--force-refresh` flags per stage |
| `python-dotenv` | ≥ 1.0 | Load `.env` config (DB URL, Census API key) | Standard 12-factor config approach |
| `loguru` | ≥ 0.7 | Structured logging with file rotation | Better than stdlib logging for pipeline output |
| `tqdm` | ≥ 4.66 | Progress bars for long ingestion loops | Sanity during large file processing |

**Note on asyncpg vs psycopg2:** This is a batch pipeline, not a web server. Async concurrency adds complexity without benefit. Use `psycopg2` + `connection.execute()` for simplicity. If you later expose a query API, switch the API layer to `asyncpg`.

### 8.2 Database

| Component | Choice | Notes |
|-----------|--------|-------|
| RDBMS | PostgreSQL 16 | |
| Spatial extension | PostGIS 3.4 | Install via `CREATE EXTENSION postgis` |
| Connection | psycopg2-binary | |
| Migrations | Alembic | `alembic upgrade head` on deploy |
| Local dev | Docker (`postgis/postgis:16-3.4`) | |

### 8.3 Tooling

| Tool | Purpose |
|------|---------|
| `make` | Task runner — `make ingest`, `make score`, `make pipeline`, `make export` |
| `QGIS` (developer tool) | Spatial verification — connect to PostGIS directly, visualize candidates on top of basemap |
| `ogr2ogr` (GDAL CLI) | Bulk shapefile-to-PostGIS loading as alternative to geopandas for large files |
| `psql` | Ad-hoc DB queries during development |
| `kepler.gl` | Web-based GeoJSON visualization for sharing results with investor (free, no server needed) |
| `csvkit` (`csvsql`, `csvstat`) | Quick CSV inspection during pipeline development |

### 8.4 Local Dev Setup

```
boat-storage-finder/
├── .env                    # DB_URL, CENSUS_API_KEY
├── .gitignore              # ignore .env, data/, output/
├── Makefile
├── README.md
├── requirements.txt
├── alembic/
│   ├── alembic.ini
│   └── versions/
├── pipeline/
│   ├── __init__.py
│   ├── config.py           # reads .env, defines paths
│   ├── db.py               # SQLAlchemy engine + session factory
│   ├── ingest_parcels.py
│   ├── ingest_nal.py
│   ├── ingest_nhd.py
│   ├── ingest_ramps.py
│   ├── ingest_marinas.py
│   ├── ingest_census.py
│   ├── filter_candidates.py
│   ├── compute_proximity.py
│   ├── score_candidates.py
│   ├── export_outputs.py
│   └── validate.py
├── sql/
│   ├── 001_create_schemas.sql
│   ├── 002_create_tables.sql
│   └── 003_seed_use_codes.sql
├── data/                   # downloaded source files (gitignored)
│   ├── pcpao/
│   ├── dor_nal/
│   ├── nhd/
│   └── census/
├── output/                 # exports (gitignored)
│   └── YYYY-MM-DD/
└── logs/
    └── YYYY-MM-DD/
```

**Bootstrap commands:**
```bash
# Start PostGIS
docker run -d --name boat-storage-db \
  -e POSTGRES_DB=boat_storage_db \
  -e POSTGRES_USER=boat \
  -e POSTGRES_PASSWORD=boat \
  -p 5432:5432 \
  postgis/postgis:16-3.4

# Create venv
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Run full pipeline
make pipeline
```

---

## 9. Deployment

### 9.1 Recommended v1: Local Laptop + Weekly Cron

For a solo engineer with 1–2 hours/day, the simplest deployment is:

- **Local MacBook or Linux workstation** running PostgreSQL + PostGIS in Docker
- **Weekly cron job** triggers `run_pipeline.sh`
- **Output directory** synced to a shared folder (Dropbox, Google Drive, or S3) for investor access
- **Log review** takes ~5 minutes: check for errors, spot-check the top 10 candidates

This requires zero cloud spend and zero ops overhead.

### 9.2 Optional v1.5: Cheap VPS

If the investor wants always-on automated operation:

| Component | Choice | Monthly Cost |
|-----------|--------|-------------|
| VPS | Hetzner CX22 (2 vCPU, 4 GB RAM, 40 GB SSD) or DigitalOcean Basic | $5–10 |
| Database | PostgreSQL + PostGIS on same VPS (dev scale) | $0 (included) |
| Scheduling | `cron` | $0 |
| File delivery | S3 bucket for output CSVs | < $1 |

**Deployment:** `docker-compose.yml` with:
- `postgis/postgis:16-3.4` container
- App container running pipeline via cron

### 9.3 Scaling Considerations (not v1)

- Pinellas County alone: comfortable on a laptop
- Expanding to all 67 Florida counties: ~26M parcels statewide — needs a proper VPS (16+ GB RAM) and query optimization
- Multi-state expansion: consider read replicas, partitioned tables by state/county

---

## 10. Key Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| PCPAO shapefile format changes | Medium | Validate field names on ingest; fail loudly with column diff |
| DOR NAL file schema changes | Medium | Reference DOR Users Guide each roll year; run schema validation step |
| FWC ArcGIS service restructure | Low | OSM slipway data as fallback; service is stable but not guaranteed |
| NHD waterbody geometries missing small bays | Medium | Supplement with OSM `natural=water` + `water=bay` for gaps |
| Building sq ft not in NAL for commercial properties | High | **This is a real problem.** NAL `TOT_LVG_AR` is primarily residential. For commercial, use PCPAO tabular download (separate from NAL) or scrape PCPAO property detail pages. Document this gap explicitly. |
| Parcel join failures (parcel_id mismatch) | Medium | Log join failure rate; if > 5%, investigate. PCPAO may use STRAP vs DOR PARCEL_ID inconsistently. |
| Crexi/LoopNet data needed for active listing price | Low | Use assessed value as proxy; add commercial listing enrichment in v2 |
| PostGIS geography distance calculations slow on large tables | Low | Add GIST indexes; use KNN operator (`<->`) for initial filter, then precise `ST_Distance` on candidates |

---

## 11. Open Questions / Decisions Deferred

1. **Commercial building sq ft data:** NAL `TOT_LVG_AR` is not reliable for commercial buildings. The PCPAO has a separate tabular download with `BLDG_SQFT` for commercial properties. Need to pull and join this file — **priority for v1 implementation.**

2. **Minimum lot size vs building size filter:** Should we include large vacant lots (DOR code 40) even if no building exists? A greenfield development play is different from a conversion play. Recommend separate "conversion candidates" vs "greenfield candidates" flags.

3. **Waterfront premium handling:** Parcels with waterfront access (`spec_feat_val > 0` for dock/seawall) may already be priced at a premium that makes conversion uneconomical. Should we penalize high `spec_feat_val`? TBD — ask investor.

4. **Municipal vs unincorporated Pinellas:** Zoning rules differ between St. Pete, Clearwater, Largo, etc. The county zoning layer only covers unincorporated Pinellas. For parcels within municipalities, a second zoning data source is needed per municipality.

5. **Canal access vs open water:** Many Pinellas properties are on canals that connect to Tampa Bay. Canal-front is not equivalent to open-water-front for boat storage operational purposes. Consider filtering NHD waterbodies to exclude canals < X meters wide.

---

*Requirements document: `requirements.md`*
