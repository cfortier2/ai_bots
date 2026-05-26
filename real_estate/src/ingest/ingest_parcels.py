"""
src/ingest/ingest_parcels.py — Pinellas County parcel ingestion.

Downloads the PCPAO parcel shapefile, reprojects from EPSG:2882 to EPSG:4326,
and bulk-loads into raw.parcels_geo.

Data source:
    https://www.pcpao.gov/tools-data/maps-gis/shape-files
    The page hosts the most recent Pinellas County parcel polygon shapefile.
    No API token required; direct download.

CRS note:
    PCPAO shapefiles arrive in NAD83 HARN State Plane Florida West
    (EPSG:2882, US survey feet).  We reproject to WGS84 (EPSG:4326) on ingest
    so all geometry is stored in a single common CRS.

TOT_LVG_AR warning:
    The DOR NAL field TOT_LVG_AR ("total living area") is designed for
    residential properties.  For commercial/industrial parcels it is
    unreliable — often zero or populated with residential-centric
    interpretation.  This script does NOT use TOT_LVG_AR for building sq ft.
    Commercial building area should be sourced from the PCPAO commercial
    tabular download (a separate file from the shapefile).  See architecture
    doc §10 / §11.  The field is stored in raw.nal_attributes for reference
    only; filter_candidates.py will note the gap and default building_sqft to
    NULL rather than propagating a bad value.

Usage:
    python -m src.ingest.ingest_parcels --help
    python -m src.ingest.ingest_parcels --data-dir ./data/raw --db-url postgresql://boat:boat@localhost/boat_storage_db

    # Dry run — download + parse without writing to DB:
    python -m src.ingest.ingest_parcels --dry-run

    # Force re-download even if local file exists:
    python -m src.ingest.ingest_parcels --force-refresh
"""

from __future__ import annotations

import io
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click
import geopandas as gpd
import psycopg2
import psycopg2.extras
import requests
from loguru import logger
from tqdm import tqdm

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# PCPAO GIS data page — we'll scrape the actual shapefile URL from here.
PCPAO_GIS_PAGE = "https://www.pcpao.gov/tools-data/maps-gis/shape-files"

# Fallback direct link patterns to try if page-scraping fails.
# PCPAO typically names the file like "Parcels_YYYY.zip" or "Parcels.zip".
PCPAO_DIRECT_URLS = [
    "https://www.pcpao.gov/documents/gis/Parcels.zip",
    "https://www.pcpao.gov/documents/gis/parcel_shapes/Parcels.zip",
]

SOURCE_CRS = "EPSG:2882"   # NAD83 HARN State Plane Florida West (feet)
TARGET_CRS = "EPSG:4326"   # WGS84 geographic

# Columns we expect in the PCPAO shapefile.  Names may vary slightly between
# vintages; we use case-insensitive matching below.
EXPECTED_COLS = {"parcelno", "parcel_id", "strap"}

# Chunk size for bulk psycopg2 inserts
INSERT_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _download_file(url: str, dest: Path, timeout: int = 120) -> None:
    """Stream-download *url* to *dest*, showing a progress bar."""
    logger.info(f"Downloading {url} → {dest}")
    headers = {"User-Agent": "BoatStorageFinder/1.0 (research tool; contact: admin@example.com)"}
    resp = requests.get(url, stream=True, timeout=timeout, headers=headers)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    with open(dest, "wb") as fh:
        with tqdm(total=total, unit="B", unit_scale=True, desc=dest.name) as bar:
            for chunk in resp.iter_content(chunk_size=65536):
                fh.write(chunk)
                bar.update(len(chunk))
    logger.info(f"Saved {dest.stat().st_size / 1_048_576:.1f} MB to {dest}")


def _find_pcpao_shapefile_url() -> Optional[str]:
    """
    Attempt to scrape the PCPAO GIS page for the current parcel shapefile URL.
    Returns the URL string or None if scraping fails.
    """
    try:
        resp = requests.get(PCPAO_GIS_PAGE, timeout=30)
        resp.raise_for_status()
        # Look for .zip links that contain "Parcel" (case-insensitive)
        matches = re.findall(r'href=["\']([^"\']*(?:[Pp]arcel[^"\']*\.zip))["\']', resp.text)
        if matches:
            base = "https://www.pcpao.gov"
            url = matches[0] if matches[0].startswith("http") else base + matches[0]
            logger.info(f"Found PCPAO shapefile URL from page: {url}")
            return url
    except Exception as exc:
        logger.warning(f"Could not scrape PCPAO page ({exc}); will try direct URLs")
    return None


def acquire_shapefile(data_dir: Path, force_refresh: bool = False) -> Path:
    """
    Download (or re-use cached) the PCPAO parcel shapefile zip.

    Returns the path to the local zip file.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    local_zip = data_dir / "pcpao_parcels.zip"

    if local_zip.exists() and not force_refresh:
        logger.info(f"Using cached shapefile: {local_zip}")
        return local_zip

    # Try scraping the page for the current URL first
    url = _find_pcpao_shapefile_url()

    if not url:
        # Fall back to known direct URL patterns
        for candidate_url in PCPAO_DIRECT_URLS:
            try:
                head = requests.head(candidate_url, timeout=15)
                if head.status_code == 200:
                    url = candidate_url
                    logger.info(f"Using fallback URL: {url}")
                    break
            except Exception:
                continue

    if not url:
        raise RuntimeError(
            "Could not find a valid PCPAO shapefile URL.  "
            "Visit https://www.pcpao.gov/tools-data/maps-gis/shape-files manually, "
            "download the parcel shapefile zip, and place it at:\n"
            f"  {local_zip}"
        )

    _download_file(url, local_zip)
    return local_zip


# ---------------------------------------------------------------------------
# Shapefile extraction and GeoDataFrame loading
# ---------------------------------------------------------------------------

def load_shapefile(zip_path: Path) -> gpd.GeoDataFrame:
    """
    Open the parcel shapefile from *zip_path*, reproject to EPSG:4326,
    and return a GeoDataFrame with normalised column names.
    """
    logger.info(f"Extracting shapefile from {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        shp_names = [n for n in zf.namelist() if n.lower().endswith(".shp")]
        if not shp_names:
            raise ValueError(f"No .shp file found inside {zip_path}")
        shp_name = shp_names[0]
        logger.info(f"Found shapefile entry: {shp_name}")

    # geopandas can read directly from a zip archive using a virtual path
    vsi_path = f"zip://{zip_path}/{shp_names[0]}"
    gdf = gpd.read_file(vsi_path)

    logger.info(f"Loaded {len(gdf):,} parcels.  CRS: {gdf.crs}")

    # Normalize column names to lowercase
    gdf.columns = [c.lower() for c in gdf.columns]

    # Detect key columns with flexible matching
    col_map = _detect_columns(gdf.columns.tolist())
    logger.info(f"Column mapping: {col_map}")

    # Reproject to WGS84
    if gdf.crs is None:
        logger.warning(f"No CRS detected; assuming {SOURCE_CRS}")
        gdf = gdf.set_crs(SOURCE_CRS)
    elif str(gdf.crs).upper() != TARGET_CRS:
        logger.info(f"Reprojecting {gdf.crs} → {TARGET_CRS}")
        gdf = gdf.to_crs(TARGET_CRS)

    # Rename to canonical names
    rename_map = {v: k for k, v in col_map.items() if v is not None}
    gdf = gdf.rename(columns=rename_map)

    # Ensure required columns exist (add as NULL if missing)
    for col in ("parcelno", "parcel_id", "strap"):
        if col not in gdf.columns:
            logger.warning(f"Column '{col}' not found in shapefile; filling with NULL")
            gdf[col] = None

    # Force geometry to MULTIPOLYGON (some parcels may be POLYGON)
    from shapely.geometry import MultiPolygon, Polygon
    def to_multipolygon(geom):
        if geom is None:
            return None
        if isinstance(geom, Polygon):
            return MultiPolygon([geom])
        return geom

    gdf["geometry"] = gdf["geometry"].apply(to_multipolygon)
    # Drop null geometries
    null_geom_count = gdf["geometry"].isna().sum()
    if null_geom_count:
        logger.warning(f"Dropping {null_geom_count:,} parcels with null geometry")
        gdf = gdf[gdf["geometry"].notna()].copy()

    logger.info(f"Shapefile ready: {len(gdf):,} parcels in {TARGET_CRS}")
    return gdf


def _detect_columns(cols: list[str]) -> dict[str, Optional[str]]:
    """
    Map canonical column names to actual shapefile column names.
    PCPAO shapefiles have changed column naming between vintages.
    """
    result: dict[str, Optional[str]] = {
        "parcelno": None,
        "parcel_id": None,
        "strap": None,
    }

    for col in cols:
        c = col.lower()
        if result["parcelno"] is None and c in ("parcelno", "parcel_no"):
            result["parcelno"] = col
        elif result["parcel_id"] is None and c in ("parcel_id", "parcelid", "pin"):
            result["parcel_id"] = col
        elif result["strap"] is None and c in ("strap", "altkey", "alt_key"):
            result["strap"] = col

    # If still nothing, try partial matches
    for col in cols:
        c = col.lower()
        if result["parcelno"] is None and "parcel" in c and "no" in c:
            result["parcelno"] = col
        if result["parcel_id"] is None and "parcel" in c and "id" in c:
            result["parcel_id"] = col
        if result["strap"] is None and "strap" in c:
            result["strap"] = col

    # Last resort: if we have only one "parcel" column, use it for both
    parcel_cols = [c for c in cols if "parcel" in c.lower()]
    if result["parcelno"] is None and parcel_cols:
        result["parcelno"] = parcel_cols[0]
    if result["parcel_id"] is None and parcel_cols:
        result["parcel_id"] = parcel_cols[0]

    return result


# ---------------------------------------------------------------------------
# Database loading
# ---------------------------------------------------------------------------

def load_to_db(
    gdf: gpd.GeoDataFrame,
    db_url: str,
    source_file: str,
    dry_run: bool = False,
) -> int:
    """
    Bulk-insert parcel rows into raw.parcels_geo.

    Uses UPSERT ON CONFLICT (parcel_id) so re-runs are idempotent.
    Returns the number of rows inserted/updated.
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would insert {len(gdf):,} parcels into raw.parcels_geo")
        return len(gdf)

    # psycopg2 needs a plain postgres:// URL (no +psycopg2 driver suffix)
    pg_url = db_url.replace("postgresql+psycopg2://", "postgresql://")

    conn = psycopg2.connect(pg_url)
    cur = conn.cursor()

    # Ensure the table is set up with a unique constraint on parcel_id so
    # ON CONFLICT works.  The migration creates a UNIQUE index on parcel_id.
    # We add a unique constraint here as a safety net if it's missing.
    cur.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'parcels_geo_parcel_id_unique'
            ) THEN
                ALTER TABLE raw.parcels_geo
                    ADD CONSTRAINT parcels_geo_parcel_id_unique UNIQUE (parcel_id);
            END IF;
        END $$;
        """
    )
    conn.commit()

    upsert_sql = """
        INSERT INTO raw.parcels_geo (parcelno, parcel_id, strap, geom, source_file)
        VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromWKB(%s), 4326), %s)
        ON CONFLICT (parcel_id) DO UPDATE SET
            parcelno    = EXCLUDED.parcelno,
            strap       = EXCLUDED.strap,
            geom        = EXCLUDED.geom,
            source_file = EXCLUDED.source_file,
            ingest_ts   = NOW()
    """

    rows_written = 0
    batch: list[tuple] = []

    logger.info(f"Inserting {len(gdf):,} parcels into raw.parcels_geo …")

    for _, row in tqdm(gdf.iterrows(), total=len(gdf), desc="Loading parcels"):
        geom = row["geometry"]
        wkb = geom.wkb if geom is not None else None

        # parcel_id is the join key — skip rows where it is null
        if not row.get("parcel_id"):
            continue

        batch.append((
            row.get("parcelno"),
            row.get("parcel_id"),
            row.get("strap"),
            psycopg2.Binary(wkb) if wkb else None,
            source_file,
        ))

        if len(batch) >= INSERT_BATCH_SIZE:
            psycopg2.extras.execute_batch(cur, upsert_sql, batch, page_size=INSERT_BATCH_SIZE)
            conn.commit()
            rows_written += len(batch)
            batch = []

    if batch:
        psycopg2.extras.execute_batch(cur, upsert_sql, batch, page_size=INSERT_BATCH_SIZE)
        conn.commit()
        rows_written += len(batch)

    cur.close()
    conn.close()

    logger.info(f"Done. {rows_written:,} rows written to raw.parcels_geo")
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
    default="./data/raw/pcpao",
    show_default=True,
    help="Directory for downloaded source files.",
    type=click.Path(),
)
@click.option(
    "--force-refresh",
    is_flag=True,
    default=False,
    help="Re-download the shapefile even if a local copy exists.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Download and parse the shapefile but do not write to the database.",
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
    verbose: bool,
) -> None:
    """
    Ingest Pinellas County parcel shapefile (PCPAO) into PostGIS.

    \b
    Steps:
      1. Download parcel shapefile zip from PCPAO (or use cache)
      2. Reproject from EPSG:2882 (State Plane Florida West) to EPSG:4326
      3. Bulk-upsert into raw.parcels_geo

    \b
    ⚠ TOT_LVG_AR warning:
      DOR NAL's TOT_LVG_AR is unreliable for commercial/industrial building
      sq ft.  This script does NOT use it.  For accurate commercial building
      area, download the PCPAO commercial tabular extract separately and join
      on STRAP.  See architecture.md §10–11 for details.
    """
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.remove()
        logger.add(sys.stderr, level="INFO")

    if not dry_run and not db_url:
        # Try composing from parts
        user = os.getenv("POSTGRES_USER", "boat")
        pw = os.getenv("POSTGRES_PASSWORD", "boat")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        dbname = os.getenv("POSTGRES_DB", "boat_storage_db")
        db_url = f"postgresql://{user}:{pw}@{host}:{port}/{dbname}"
        logger.info(f"No --db-url supplied; using {db_url}")

    data_path = Path(data_dir)

    # Step 1: acquire shapefile
    start = time.time()
    zip_path = acquire_shapefile(data_path, force_refresh=force_refresh)

    # Step 2: load GeoDataFrame and reproject
    gdf = load_shapefile(zip_path)

    # Step 3: insert into DB
    rows = load_to_db(gdf, db_url, source_file=zip_path.name, dry_run=dry_run)

    elapsed = time.time() - start
    mode = "[DRY RUN] " if dry_run else ""
    logger.info(f"{mode}Parcel ingest complete: {rows:,} rows in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
