"""
src/ingest/ingest_water.py — NHD water features ingestion.

Downloads the USGS National Hydrography Dataset (NHD) Best Resolution for
HUC-8 03090202 (Peace-Tampa Bay watershed), which covers all of Pinellas
County including Tampa Bay, Old Tampa Bay, Boca Ciega Bay, and the Gulf
of Mexico coastline.

Two NHD layers are ingested:
  - NHDWaterbody   → polygon geometries for bays, lakes, reservoirs
  - NHDFlowline    → river/stream centerlines (buffered to approximate width)

Both are loaded into geo.water_bodies.  The `navigable` flag is set based on
FCode classification and minimum-size filters (see NAVIGABLE_FCODES below).

NHD FCode reference (relevant subset):
  39004  Bay/Estuary                  ✅ always navigable
  39010  Bay/Estuary with lock         ✅ always navigable
  36100  Lake/Pond (perennial)         ✅ if area ≥ 10 acres
  46006  Stream/River (perennial)      ✅ if Strahler order ≥ 4 (not in NHD Best;
                                          we approximate by minimum area)
  46003  Intermittent stream           ❌ not navigable
  33600  Canal/Ditch                   ✅ only if estimated width > 50 ft
  53700  Playa                         ❌ not navigable

Data source:
  https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/HU8/HighResolution/Shape/NHD_H_03090202_HU8_Shape.zip

Usage:
    python -m src.ingest.ingest_water --help
    python -m src.ingest.ingest_water --data-dir ./data/raw --db-url postgresql://boat:boat@localhost/boat_storage_db
    python -m src.ingest.ingest_water --dry-run
    python -m src.ingest.ingest_water --force-refresh
"""

from __future__ import annotations

import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

import click
import geopandas as gpd
import psycopg2
import psycopg2.extras
import requests
from loguru import logger
from shapely.geometry import MultiPolygon, Polygon, mapping
from tqdm import tqdm

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NHD_HUC8 = "03090202"
NHD_DOWNLOAD_URL = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/"
    f"HU8/HighResolution/Shape/NHD_H_{NHD_HUC8}_HU8_Shape.zip"
)

TARGET_CRS = "EPSG:4326"

# FCode → (navigable, min_area_sqkm)
# min_area_sqkm only applies to waterbodies (not flowlines)
NAVIGABLE_FCODES: dict[int, tuple[bool, Optional[float]]] = {
    39004: (True, None),   # Bay/Estuary — always navigable
    39010: (True, None),   # Bay/Estuary with lock
    39009: (True, None),   # Bay/Estuary (alternate code)
    36100: (True, 0.0405), # Lake/Pond ≥ 10 acres (0.0405 km²)
    36400: (True, 0.0405), # Reservoir
    46006: (True, None),   # Perennial stream/river (flowline)
    33600: (True, None),   # Canal/Ditch (filter by name / area in post)
    46007: (True, None),   # Intermittent stream — borderline; include for Tampa area
}

NON_NAVIGABLE_FCODES = {
    46003,  # Intermittent stream
    53700,  # Playa
    56600,  # Coastline (geometry artifact, not a water body)
    43600,  # Submerged stream
    46000,  # Stream/River generic
    33400,  # Connector (artificial path)
    55800,  # Artificial path
}

INSERT_BATCH_SIZE = 200

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_file(url: str, dest: Path, timeout: int = 300) -> None:
    """Stream-download *url* to *dest*, with progress bar."""
    logger.info(f"Downloading {url} → {dest}")
    headers = {"User-Agent": "BoatStorageFinder/1.0 (research tool)"}
    resp = requests.get(url, stream=True, timeout=timeout, headers=headers)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    with open(dest, "wb") as fh:
        with tqdm(total=total, unit="B", unit_scale=True, desc=dest.name) as bar:
            for chunk in resp.iter_content(chunk_size=65536):
                fh.write(chunk)
                bar.update(len(chunk))
    logger.info(f"Saved {dest.stat().st_size / 1_048_576:.1f} MB to {dest}")


def acquire_nhd_zip(data_dir: Path, force_refresh: bool = False) -> Path:
    """Download (or re-use cached) the NHD HUC-8 zip file."""
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / f"NHD_H_{NHD_HUC8}_HU8_Shape.zip"

    if dest.exists() and not force_refresh:
        logger.info(f"Using cached NHD zip: {dest}")
        return dest

    _download_file(NHD_DOWNLOAD_URL, dest)
    return dest


# ---------------------------------------------------------------------------
# Shapefile extraction
# ---------------------------------------------------------------------------

def _list_shapefiles_in_zip(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return [n for n in zf.namelist() if n.lower().endswith(".shp")]


def _load_nhd_layer(zip_path: Path, layer_name: str) -> Optional[gpd.GeoDataFrame]:
    """
    Load a named NHD layer (e.g. 'NHDWaterbody', 'NHDFlowline') from the zip.
    Returns None if the layer is not present.
    """
    with zipfile.ZipFile(zip_path) as zf:
        matches = [
            n for n in zf.namelist()
            if n.lower().endswith(".shp") and layer_name.lower() in n.lower()
        ]

    if not matches:
        logger.warning(f"Layer '{layer_name}' not found in {zip_path.name}")
        return None

    shp_entry = matches[0]
    vsi_path = f"zip://{zip_path}/{shp_entry}"
    logger.info(f"Loading layer: {shp_entry}")
    gdf = gpd.read_file(vsi_path)
    logger.info(f"  → {len(gdf):,} features, CRS: {gdf.crs}")
    gdf.columns = [c.lower() for c in gdf.columns]

    if gdf.crs is None:
        logger.warning("No CRS; assuming EPSG:4269 (NAD83 geographic)")
        gdf = gdf.set_crs("EPSG:4269")

    if str(gdf.crs).upper() != TARGET_CRS:
        gdf = gdf.to_crs(TARGET_CRS)

    return gdf


def _is_navigable(fcode: int, area_sqkm: Optional[float]) -> bool:
    """Determine if a feature should be flagged as navigable."""
    if fcode in NON_NAVIGABLE_FCODES:
        return False
    if fcode in NAVIGABLE_FCODES:
        navigable, min_area = NAVIGABLE_FCODES[fcode]
        if not navigable:
            return False
        if min_area is not None and area_sqkm is not None:
            return area_sqkm >= min_area
        return navigable
    # Unknown FCode — not navigable by default
    return False


def _to_multipolygon(geom) -> Optional[MultiPolygon]:
    """Coerce geometry to MultiPolygon; return None for non-polygon types."""
    if geom is None:
        return None
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    # LineString / Point — not a polygon; caller handles
    return None


def prepare_waterbody_rows(gdf: gpd.GeoDataFrame) -> list[dict]:
    """
    Convert NHDWaterbody GeoDataFrame to list of row dicts ready for DB insert.
    """
    rows = []
    skipped = 0

    for _, feat in gdf.iterrows():
        geom = feat.get("geometry")
        mp = _to_multipolygon(geom)
        if mp is None:
            skipped += 1
            continue

        fcode = int(feat.get("fcode") or feat.get("fcode_", 0) or 0)
        # Compute area in km² using projected equivalent (approx using WGS84 degrees → rough km)
        area_sqkm: Optional[float] = None
        try:
            # areasqkm field present in NHD; fall back to computing from geometry
            raw_area = feat.get("areasqkm") or feat.get("areaacre")
            if raw_area is not None:
                area_sqkm = float(raw_area) if "sqkm" in str(
                    [k for k in feat.index if "area" in k.lower()]
                ) else float(raw_area) * 0.00404686  # acres → km²
        except (TypeError, ValueError):
            pass

        rows.append({
            "permanent_id": str(feat.get("permanent_identifier") or feat.get("permanent_") or ""),
            "fcode": fcode,
            "ftype": str(feat.get("ftype") or ""),
            "gnis_name": str(feat.get("gnis_name") or feat.get("gnisname") or ""),
            "area_sqkm": area_sqkm,
            "geom_wkb": mp.wkb,
            "navigable": _is_navigable(fcode, area_sqkm),
        })

    if skipped:
        logger.debug(f"Skipped {skipped} non-polygon waterbody features")

    return rows


def prepare_flowline_rows(gdf: gpd.GeoDataFrame) -> list[dict]:
    """
    Convert NHDFlowline GeoDataFrame to list of row dicts.
    Flowlines are linestrings; we store them as zero-width 'water features'
    with a small buffer for visual/proximity use.  The geometry is stored as
    a MULTIPOLYGON by buffering the centreline ~30m (roughly 1 boat-width).

    For proximity queries, using the linestring's bounding box / centroid
    would be sufficient, but storing as polygon keeps the schema consistent.
    """
    rows = []
    skipped = 0

    for _, feat in gdf.iterrows():
        geom = feat.get("geometry")
        if geom is None:
            skipped += 1
            continue

        fcode = int(feat.get("fcode") or 0)

        # Only ingest navigable flowlines (perennial streams, canals)
        if not _is_navigable(fcode, None):
            continue

        # Buffer line ~0.0003 degrees (~30 m at this latitude) to get a polygon
        try:
            buffered = geom.buffer(0.0003)
            mp = _to_multipolygon(buffered)
            if mp is None:
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue

        rows.append({
            "permanent_id": str(feat.get("permanent_identifier") or feat.get("permanent_") or ""),
            "fcode": fcode,
            "ftype": str(feat.get("ftype") or ""),
            "gnis_name": str(feat.get("gnis_name") or feat.get("gnisname") or ""),
            "area_sqkm": None,  # not meaningful for buffered flowlines
            "geom_wkb": mp.wkb,
            "navigable": True,  # already filtered above
        })

    if skipped:
        logger.debug(f"Skipped {skipped} flowline features (non-navigable or invalid)")

    return rows


# ---------------------------------------------------------------------------
# DB loading
# ---------------------------------------------------------------------------

def load_to_db(
    rows: list[dict],
    db_url: str,
    dry_run: bool = False,
) -> int:
    """
    Bulk-insert water feature rows into geo.water_bodies.
    Uses TRUNCATE + INSERT (full refresh model) since NHD data changes rarely.
    Returns row count.
    """
    if not rows:
        logger.warning("No water feature rows to insert")
        return 0

    if dry_run:
        logger.info(f"[DRY RUN] Would insert {len(rows):,} features into geo.water_bodies")
        return len(rows)

    pg_url = db_url.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()

    # Full refresh — truncate then reload
    cur.execute("TRUNCATE geo.water_bodies RESTART IDENTITY")
    conn.commit()

    insert_sql = """
        INSERT INTO geo.water_bodies
            (permanent_id, fcode, ftype, gnis_name, area_sqkm, geom, navigable)
        VALUES
            (%s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromWKB(%s), 4326), %s)
    """

    rows_written = 0
    batch: list[tuple] = []

    logger.info(f"Inserting {len(rows):,} water features into geo.water_bodies …")

    for row in tqdm(rows, desc="Loading water features"):
        batch.append((
            row["permanent_id"],
            row["fcode"],
            row["ftype"],
            row["gnis_name"],
            row["area_sqkm"],
            psycopg2.Binary(row["geom_wkb"]),
            row["navigable"],
        ))

        if len(batch) >= INSERT_BATCH_SIZE:
            psycopg2.extras.execute_batch(cur, insert_sql, batch, page_size=INSERT_BATCH_SIZE)
            conn.commit()
            rows_written += len(batch)
            batch = []

    if batch:
        psycopg2.extras.execute_batch(cur, insert_sql, batch, page_size=INSERT_BATCH_SIZE)
        conn.commit()
        rows_written += len(batch)

    cur.close()
    conn.close()

    # Log navigable summary
    logger.info(f"Done. {rows_written:,} water features loaded.")
    navigable_count = sum(1 for r in rows if r["navigable"])
    logger.info(
        f"  Navigable: {navigable_count:,}  |  Non-navigable: {len(rows) - navigable_count:,}"
    )
    return rows_written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option(
    "--db-url",
    default=None,
    envvar="DATABASE_URL",
    help="PostgreSQL connection URL.  Defaults to DATABASE_URL env var.",
)
@click.option(
    "--data-dir",
    default="./data/raw/nhd",
    show_default=True,
    help="Directory for downloaded NHD source files.",
    type=click.Path(),
)
@click.option(
    "--force-refresh",
    is_flag=True,
    default=False,
    help="Re-download the NHD zip even if a local copy exists.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Download and parse without writing to the database.",
)
@click.option(
    "--no-flowlines",
    is_flag=True,
    default=False,
    help="Skip NHDFlowline ingestion (waterbodies only).",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable debug-level logging.",
)
def main(
    db_url: Optional[str],
    data_dir: str,
    force_refresh: bool,
    dry_run: bool,
    no_flowlines: bool,
    verbose: bool,
) -> None:
    """
    Ingest NHD water features (HUC-8 03090202) into PostGIS geo.water_bodies.

    \b
    Downloads:
      NHD_H_03090202_HU8_Shape.zip (~50–100 MB) from USGS S3

    \b
    Layers ingested:
      - NHDWaterbody  → bays, lakes, reservoirs (polygon → MULTIPOLYGON)
      - NHDFlowline   → perennial streams/rivers (buffered linestring → MULTIPOLYGON)

    \b
    The `navigable` flag is set based on FCode classification:
      39004/39010 (Bay/Estuary) → always navigable
      36100/36400 (Lake/Reservoir ≥ 10 acres) → navigable
      46006 (perennial stream) → navigable
    """
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.remove()
        logger.add(sys.stderr, level="INFO")

    if not dry_run and not db_url:
        user = os.getenv("POSTGRES_USER", "boat")
        pw = os.getenv("POSTGRES_PASSWORD", "boat")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        dbname = os.getenv("POSTGRES_DB", "boat_storage_db")
        db_url = f"postgresql://{user}:{pw}@{host}:{port}/{dbname}"
        logger.info(f"No --db-url supplied; using {db_url}")

    data_path = Path(data_dir)
    start = time.time()

    # Step 1: Download
    zip_path = acquire_nhd_zip(data_path, force_refresh=force_refresh)

    # Step 2: Load waterbodies
    all_rows: list[dict] = []

    wb_gdf = _load_nhd_layer(zip_path, "NHDWaterbody")
    if wb_gdf is not None:
        wb_rows = prepare_waterbody_rows(wb_gdf)
        logger.info(f"NHDWaterbody: {len(wb_rows):,} polygon features prepared")
        all_rows.extend(wb_rows)
    else:
        logger.error("NHDWaterbody layer missing from NHD zip — cannot continue without waterbodies")
        sys.exit(1)

    # Step 3: Load flowlines (optional)
    if not no_flowlines:
        fl_gdf = _load_nhd_layer(zip_path, "NHDFlowline")
        if fl_gdf is not None:
            fl_rows = prepare_flowline_rows(fl_gdf)
            logger.info(f"NHDFlowline: {len(fl_rows):,} navigable flowline features prepared")
            all_rows.extend(fl_rows)

    # Step 4: Insert
    rows_written = load_to_db(all_rows, db_url, dry_run=dry_run)

    elapsed = time.time() - start
    mode = "[DRY RUN] " if dry_run else ""
    logger.info(f"{mode}Water ingest complete: {rows_written:,} rows in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
