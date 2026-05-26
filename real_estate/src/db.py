"""
src/db.py — SQLAlchemy engine and session factory.

Usage:
    from src.db import get_engine, get_connection

    engine = get_engine()
    with get_connection() as conn:
        result = conn.execute(sa.text("SELECT postgis_full_version()"))
        print(result.fetchone())

The DATABASE_URL env var is the primary configuration point.
Falls back to composing a URL from individual POSTGRES_* vars.

PostGIS notes:
- We use the standard PostgreSQL dialect (postgresql+psycopg2).
- GeoAlchemy2 and geopandas handle the actual geometry serialisation.
- Set connect_args={'options': '-c search_path=public,raw,geo,ref'}
  so un-qualified table names resolve correctly.
"""

from __future__ import annotations

import contextlib
import os
from typing import Generator

import sqlalchemy as sa
from sqlalchemy.engine import Engine

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------

def _build_url() -> str:
    """Return the DATABASE_URL, composing from parts if the var isn't set."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("POSTGRES_USER", "boat")
    password = os.getenv("POSTGRES_PASSWORD", "boat")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB", "boat_storage_db")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------

def get_engine(
    database_url: str | None = None,
    *,
    pool_pre_ping: bool = True,
    echo: bool = False,
) -> Engine:
    """
    Return a SQLAlchemy engine for the PostGIS database.

    Args:
        database_url: Override URL (useful for tests).  Falls back to env.
        pool_pre_ping: Issue a SELECT 1 before handing out a connection.
        echo: Log all SQL statements (verbose; set True for debugging).

    Returns:
        A configured SQLAlchemy Engine.
    """
    url = database_url or _build_url()

    # Ensure the driver prefix is correct — accept bare "postgresql://" too.
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    connect_args: dict = {
        # Include all project schemas in the search path so un-qualified
        # references work in ad-hoc SQL strings.
        "options": "-c search_path=public,raw,geo,ref",
    }

    engine = sa.create_engine(
        url,
        pool_pre_ping=pool_pre_ping,
        echo=echo,
        connect_args=connect_args,
    )
    return engine


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def get_connection(
    database_url: str | None = None,
    engine: Engine | None = None,
) -> Generator[sa.engine.Connection, None, None]:
    """
    Context manager that yields a SQLAlchemy Connection and commits on exit
    (or rolls back on exception).

    Example::

        with get_connection() as conn:
            conn.execute(sa.text("INSERT INTO raw.parcels_geo ..."))
            # auto-committed on clean exit

    Args:
        database_url: Override URL (useful for tests).
        engine: Use an existing engine instead of creating a new one.
    """
    _engine = engine or get_engine(database_url)
    with _engine.connect() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ---------------------------------------------------------------------------
# Quick connectivity test (importable as a library function)
# ---------------------------------------------------------------------------

def check_connection(database_url: str | None = None) -> bool:
    """
    Return True if the database is reachable and PostGIS is installed.

    Useful for health checks and smoke tests.
    """
    try:
        engine = get_engine(database_url)
        with engine.connect() as conn:
            row = conn.execute(sa.text("SELECT postgis_lib_version()")).fetchone()
            return row is not None
    except Exception:
        return False
