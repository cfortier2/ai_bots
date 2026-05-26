"""
tests/test_smoke.py — Smoke tests for DB connectivity and schema integrity.

These tests verify:
  1. Database is reachable
  2. PostGIS extension is installed and functional
  3. All 8 expected tables exist in the correct schemas

Run with:
    TEST_DATABASE_URL=postgresql://boat:boat@localhost/boat_storage_db pytest tests/test_smoke.py -v

Or if docker-compose is up and using defaults:
    pytest tests/test_smoke.py -v

The TEST_DATABASE_URL env var is read first; falls back to DATABASE_URL; then
composes from POSTGRES_* vars using the same logic as src/db.py.
"""

from __future__ import annotations

import os
from typing import Optional

import psycopg2
import pytest

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _resolve_db_url() -> str:
    """Resolve the test database URL from environment."""
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if url:
        # Strip SQLAlchemy driver suffix if present
        url = url.replace("postgresql+psycopg2://", "postgresql://")
        return url

    user = os.getenv("POSTGRES_USER", "boat")
    pw = os.getenv("POSTGRES_PASSWORD", "boat")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB", "boat_storage_db")
    return f"postgresql://{user}:{pw}@{host}:{port}/{dbname}"


@pytest.fixture(scope="session")
def db_conn():
    """
    Session-scoped psycopg2 connection.
    Skips all tests cleanly if the DB is not reachable.
    """
    url = _resolve_db_url()
    try:
        conn = psycopg2.connect(url, connect_timeout=10)
        conn.autocommit = True
        yield conn
        conn.close()
    except psycopg2.OperationalError as exc:
        pytest.skip(
            f"Database not reachable at {url!r}: {exc}\n"
            "Start the DB with: docker-compose up -d\n"
            "Then run migrations: make migrate"
        )


# ---------------------------------------------------------------------------
# Test 1 — DB connection
# ---------------------------------------------------------------------------

class TestDBConnection:
    def test_connection_is_alive(self, db_conn):
        """SELECT 1 returns a result row."""
        cur = db_conn.cursor()
        cur.execute("SELECT 1")
        row = cur.fetchone()
        cur.close()
        assert row == (1,), f"Expected (1,), got {row}"

    def test_database_name(self, db_conn):
        """Connected to the expected database."""
        expected = os.getenv("POSTGRES_DB", "boat_storage_db")
        cur = db_conn.cursor()
        cur.execute("SELECT current_database()")
        row = cur.fetchone()
        cur.close()
        assert row is not None
        assert row[0] == expected, (
            f"Expected database '{expected}', got '{row[0]}'"
        )


# ---------------------------------------------------------------------------
# Test 2 — PostGIS extension
# ---------------------------------------------------------------------------

class TestPostGIS:
    def test_postgis_extension_installed(self, db_conn):
        """pg_extension row exists for 'postgis'."""
        cur = db_conn.cursor()
        cur.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'postgis'"
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None, (
            "PostGIS extension not found.  "
            "Run: CREATE EXTENSION postgis; OR run migrations: make migrate"
        )

    def test_postgis_version_function(self, db_conn):
        """postgis_lib_version() is callable and returns a non-empty string."""
        cur = db_conn.cursor()
        cur.execute("SELECT postgis_lib_version()")
        row = cur.fetchone()
        cur.close()
        assert row is not None
        version = row[0]
        assert isinstance(version, str) and len(version) > 0, (
            f"Unexpected PostGIS version: {version!r}"
        )

    def test_postgis_geometry_type(self, db_conn):
        """ST_GeomFromText round-trips correctly."""
        cur = db_conn.cursor()
        cur.execute(
            "SELECT ST_AsText(ST_GeomFromText('POINT(-82.6 27.8)', 4326))"
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None
        assert "POINT" in row[0].upper(), f"Unexpected geometry: {row[0]}"

    def test_postgis_geography_cast(self, db_conn):
        """::geography cast and ST_Distance work without error."""
        cur = db_conn.cursor()
        cur.execute(
            """
            SELECT ST_Distance(
                ST_GeomFromText('POINT(-82.6 27.8)', 4326)::geography,
                ST_GeomFromText('POINT(-82.7 27.9)', 4326)::geography
            )
            """
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None
        dist = row[0]
        # Distance between two points ~14 km apart should be roughly 13–16 km
        assert 10_000 < dist < 20_000, (
            f"ST_Distance result {dist:.0f} m looks wrong "
            "(expected ~14 km between those two points)"
        )


# ---------------------------------------------------------------------------
# Test 3 — All 8 tables exist
# ---------------------------------------------------------------------------

# (schema, table_name) pairs for all tables in the architecture
EXPECTED_TABLES = [
    ("raw",    "parcels_geo"),
    ("raw",    "nal_attributes"),
    ("geo",    "water_bodies"),
    ("geo",    "boat_ramps"),
    ("geo",    "marinas"),
    ("geo",    "census_tracts"),
    ("ref",    "dor_use_codes"),
    ("public", "candidates"),
]


class TestSchema:
    def _table_exists(self, conn, schema: str, table: str) -> bool:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name   = %s
            """,
            (schema, table),
        )
        row = cur.fetchone()
        cur.close()
        return row is not None

    @pytest.mark.parametrize("schema,table", EXPECTED_TABLES)
    def test_table_exists(self, db_conn, schema: str, table: str):
        """Every expected table is present in the database."""
        exists = self._table_exists(db_conn, schema, table)
        assert exists, (
            f"Table '{schema}.{table}' not found.  "
            "Run: make migrate"
        )

    def test_all_schemas_present(self, db_conn):
        """All four schemas (raw, geo, ref, public) exist."""
        cur = db_conn.cursor()
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name IN ('raw', 'geo', 'ref', 'public')"
        )
        rows = cur.fetchall()
        cur.close()
        found = {r[0] for r in rows}
        expected = {"raw", "geo", "ref", "public"}
        missing = expected - found
        assert not missing, f"Missing schemas: {missing}"

    def test_parcels_geo_has_gist_index(self, db_conn):
        """raw.parcels_geo has a GIST spatial index on geom."""
        cur = db_conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'raw'
              AND tablename  = 'parcels_geo'
              AND indexname  = 'idx_parcels_geo_geom'
            """
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None, (
            "GIST index 'idx_parcels_geo_geom' on raw.parcels_geo not found"
        )

    def test_water_bodies_has_gist_index(self, db_conn):
        """geo.water_bodies has a GIST spatial index on geom."""
        cur = db_conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'geo'
              AND tablename  = 'water_bodies'
              AND indexname  = 'idx_water_bodies_geom'
            """
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None, (
            "GIST index 'idx_water_bodies_geom' on geo.water_bodies not found"
        )

    def test_candidates_has_gist_index(self, db_conn):
        """public.candidates has a GIST spatial index on geom."""
        cur = db_conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename  = 'candidates'
              AND indexname  = 'idx_candidates_geom'
            """
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None, (
            "GIST index 'idx_candidates_geom' on public.candidates not found"
        )

    def test_dor_use_codes_seeded(self, db_conn):
        """ref.dor_use_codes has at least the 6 core candidate codes."""
        cur = db_conn.cursor()
        cur.execute(
            "SELECT code FROM ref.dor_use_codes WHERE code IN (40, 41, 42, 48, 49, 91)"
        )
        rows = cur.fetchall()
        cur.close()
        found_codes = {r[0] for r in rows}
        expected = {40, 41, 42, 48, 49, 91}
        missing = expected - found_codes
        assert not missing, (
            f"ref.dor_use_codes is missing seed rows for codes: {missing}\n"
            "Migration 001 seeds these rows; check that migrations ran: make migrate"
        )

    def test_candidates_geometry_columns(self, db_conn):
        """public.candidates has both geom and centroid geometry columns."""
        cur = db_conn.cursor()
        cur.execute(
            """
            SELECT f_geometry_column, type, srid
            FROM geometry_columns
            WHERE f_table_schema = 'public'
              AND f_table_name   = 'candidates'
            ORDER BY f_geometry_column
            """
        )
        rows = cur.fetchall()
        cur.close()
        col_map = {r[0]: (r[1], r[2]) for r in rows}

        assert "geom" in col_map, (
            "public.candidates.geom geometry column not found in geometry_columns"
        )
        assert "centroid" in col_map, (
            "public.candidates.centroid geometry column not found in geometry_columns"
        )

        geom_type, geom_srid = col_map["geom"]
        assert geom_srid == 4326, f"candidates.geom SRID should be 4326, got {geom_srid}"

        centroid_type, centroid_srid = col_map["centroid"]
        assert centroid_srid == 4326, f"candidates.centroid SRID should be 4326, got {centroid_srid}"
