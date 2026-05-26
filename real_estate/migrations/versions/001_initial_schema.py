"""Initial schema: PostGIS extensions, schemas, and all 8 tables.

Revision ID: 001
Revises:
Create Date: 2026-05-26

Tables created:
  raw.parcels_geo         -- PCPAO parcel polygons
  raw.nal_attributes      -- DOR NAL tabular attributes
  geo.water_bodies        -- NHD waterbody polygons
  geo.boat_ramps          -- FWC boat ramp points
  geo.marinas             -- OSM marina/slipway points
  geo.census_tracts       -- ACS census tract polygons
  ref.dor_use_codes       -- DOR land use code lookup (seeded)
  public.candidates       -- Filtered + scored candidate parcels
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # PostGIS extension                                                    #
    # ------------------------------------------------------------------ #
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis_topology")

    # ------------------------------------------------------------------ #
    # Schemas                                                             #
    # ------------------------------------------------------------------ #
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("CREATE SCHEMA IF NOT EXISTS geo")
    op.execute("CREATE SCHEMA IF NOT EXISTS ref")
    # public schema already exists in PostgreSQL by default

    # ------------------------------------------------------------------ #
    # raw.parcels_geo                                                      #
    # Parcel polygons from PCPAO shapefile                                #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE raw.parcels_geo (
            id          SERIAL PRIMARY KEY,
            parcelno    TEXT NOT NULL,
            parcel_id   TEXT NOT NULL,
            strap       TEXT,
            geom        GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
            ingest_ts   TIMESTAMPTZ DEFAULT NOW(),
            source_file TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_parcels_geo_geom ON raw.parcels_geo USING GIST(geom)"
    )
    op.execute(
        "CREATE INDEX idx_parcels_geo_parcel_id ON raw.parcels_geo(parcel_id)"
    )
    op.execute(
        "CREATE INDEX idx_parcels_geo_parcelno ON raw.parcels_geo(parcelno)"
    )

    # ------------------------------------------------------------------ #
    # raw.nal_attributes                                                   #
    # DOR NAL file attributes, joined to parcels by parcel_id            #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE raw.nal_attributes (
            id              SERIAL PRIMARY KEY,
            parcel_id       TEXT NOT NULL,
            county_no       SMALLINT,
            dor_uc          SMALLINT,
            owner_name      TEXT,
            mail_addr1      TEXT,
            mail_addr2      TEXT,
            mail_city       TEXT,
            mail_state      CHAR(2),
            mail_zip        TEXT,
            site_addr       TEXT,
            site_city       TEXT,
            site_zip        TEXT,
            jv              NUMERIC(14,2),
            av_sd           NUMERIC(14,2),
            tv_sd           NUMERIC(14,2),
            lnd_val         NUMERIC(14,2),
            bldg_val        NUMERIC(14,2),
            tot_lvg_ar      INTEGER,
            no_buldng       SMALLINT,
            act_yr_blt      SMALLINT,
            sale_prc        NUMERIC(14,2),
            sale_yr         SMALLINT,
            sale_mo         SMALLINT,
            spec_feat_val   NUMERIC(14,2),
            lot_size        NUMERIC(12,2),
            ingest_ts       TIMESTAMPTZ DEFAULT NOW(),
            roll_year       SMALLINT,
            roll_type       TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_nal_parcel_id ON raw.nal_attributes(parcel_id)"
    )
    op.execute(
        "CREATE INDEX idx_nal_dor_uc ON raw.nal_attributes(dor_uc)"
    )

    # ------------------------------------------------------------------ #
    # geo.water_bodies                                                     #
    # NHD waterbody polygons + flowline features                          #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE geo.water_bodies (
            id              SERIAL PRIMARY KEY,
            permanent_id    TEXT,
            fcode           INTEGER,
            ftype           TEXT,
            gnis_name       TEXT,
            area_sqkm       NUMERIC(12,4),
            geom            GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
            navigable       BOOLEAN DEFAULT FALSE,
            ingest_ts       TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_water_bodies_geom ON geo.water_bodies USING GIST(geom)"
    )
    op.execute(
        "CREATE INDEX idx_water_bodies_fcode ON geo.water_bodies(fcode)"
    )
    op.execute(
        "CREATE INDEX idx_water_bodies_navigable ON geo.water_bodies(navigable)"
    )

    # ------------------------------------------------------------------ #
    # geo.boat_ramps                                                       #
    # FWC public boat ramp locations                                       #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE geo.boat_ramps (
            id              SERIAL PRIMARY KEY,
            facility_name   TEXT,
            county          TEXT,
            ramp_type       TEXT,
            num_lanes       SMALLINT,
            parking_spaces  INTEGER,
            public_access   BOOLEAN DEFAULT TRUE,
            geom            GEOMETRY(POINT, 4326) NOT NULL,
            source          TEXT DEFAULT 'FWC',
            ingest_ts       TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_boat_ramps_geom ON geo.boat_ramps USING GIST(geom)"
    )
    op.execute(
        "CREATE INDEX idx_boat_ramps_county ON geo.boat_ramps(county)"
    )

    # ------------------------------------------------------------------ #
    # geo.marinas                                                          #
    # Marina/boat storage locations from OSM                              #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE geo.marinas (
            id              SERIAL PRIMARY KEY,
            osm_id          BIGINT,
            osm_type        TEXT,
            name            TEXT,
            amenity         TEXT,
            capacity        INTEGER,
            geom            GEOMETRY(POINT, 4326) NOT NULL,
            source          TEXT DEFAULT 'OSM',
            ingest_ts       TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_marinas_geom ON geo.marinas USING GIST(geom)"
    )

    # ------------------------------------------------------------------ #
    # geo.census_tracts                                                    #
    # ACS census tracts with median household income                      #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE geo.census_tracts (
            id                  SERIAL PRIMARY KEY,
            geoid               TEXT UNIQUE NOT NULL,
            name                TEXT,
            county_fips         TEXT,
            median_hh_income    INTEGER,
            acs_year            SMALLINT,
            geom                GEOMETRY(MULTIPOLYGON, 4326),
            ingest_ts           TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_census_geom ON geo.census_tracts USING GIST(geom)"
    )

    # ------------------------------------------------------------------ #
    # ref.dor_use_codes                                                    #
    # Florida DOR land use code lookup table                              #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE ref.dor_use_codes (
            code            SMALLINT PRIMARY KEY,
            description     TEXT NOT NULL,
            category        TEXT,
            candidate_tier  SMALLINT
        )
        """
    )

    # Seed data: all relevant DOR use codes
    op.execute(
        """
        INSERT INTO ref.dor_use_codes (code, description, category, candidate_tier) VALUES
          (48, 'Warehousing, distribution terminals, trucking terminals, van and storage warehousing', 'industrial', 1),
          (40, 'Vacant industrial',         'industrial', 2),
          (41, 'Light manufacturing',        'industrial', 2),
          (42, 'Heavy industrial',           'industrial', 2),
          (49, 'Open storage',               'industrial', 2),
          (39, 'Hotels and motels',          'commercial', 3),
          (91, 'Utility, gas & electric',    'utility',    3),
          (10, 'Vacant commercial',          'commercial', NULL),
          (11, 'Stores, one-story',          'commercial', NULL),
          (12, 'Mixed use - store and office or store and residential combination', 'commercial', NULL),
          (17, 'Office buildings, non-professional service buildings, one-story', 'commercial', NULL),
          (18, 'Office buildings, non-professional service buildings, multi-story', 'commercial', NULL),
          (20, 'Airports and marine terminals, piers, marinas', 'commercial', NULL),
          (27, 'Automotive service facilities including service stations', 'commercial', NULL),
          (34, 'Bowling alleys, skating rinks, pool halls, enclosed arenas', 'commercial', NULL)
        """
    )

    # ------------------------------------------------------------------ #
    # public.candidates                                                    #
    # Filtered candidate parcels — working set for scoring               #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE public.candidates (
            id                      SERIAL PRIMARY KEY,
            parcel_id               TEXT NOT NULL UNIQUE,
            parcelno                TEXT,
            strap                   TEXT,

            -- Identity
            site_addr               TEXT,
            site_city               TEXT,
            site_zip                TEXT,
            owner_name              TEXT,

            -- Property attributes
            dor_uc                  SMALLINT,
            use_desc                TEXT,
            building_sqft           INTEGER,
            lot_size_acres          NUMERIC(10,4),
            year_built              SMALLINT,
            no_buildings            SMALLINT,

            -- Financials
            just_value              NUMERIC(14,2),
            assessed_value          NUMERIC(14,2),
            land_value              NUMERIC(14,2),
            bldg_value              NUMERIC(14,2),
            last_sale_price         NUMERIC(14,2),
            last_sale_year          SMALLINT,
            spec_feat_value         NUMERIC(14,2),

            -- Geometry
            geom                    GEOMETRY(MULTIPOLYGON, 4326),
            centroid                GEOMETRY(POINT, 4326),

            -- Proximity (computed by compute_proximity.py)
            dist_to_water_m         NUMERIC(10,2),
            dist_to_ramp_m          NUMERIC(10,2),
            boat_ramps_5mi          SMALLINT,
            marinas_10mi            SMALLINT,
            nearest_water_name      TEXT,
            nearest_ramp_name       TEXT,
            parcel_touches_water    BOOLEAN,
            median_hh_income        INTEGER,

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
            scored_at               TIMESTAMPTZ,
            ingest_ts               TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_candidates_geom ON public.candidates USING GIST(geom)"
    )
    op.execute(
        "CREATE INDEX idx_candidates_centroid ON public.candidates USING GIST(centroid)"
    )
    op.execute(
        "CREATE INDEX idx_candidates_score ON public.candidates(score_total DESC NULLS LAST)"
    )
    op.execute(
        "CREATE INDEX idx_candidates_dor_uc ON public.candidates(dor_uc)"
    )
    op.execute(
        "CREATE INDEX idx_candidates_building_sqft ON public.candidates(building_sqft)"
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.execute("DROP TABLE IF EXISTS public.candidates CASCADE")
    op.execute("DROP TABLE IF EXISTS ref.dor_use_codes CASCADE")
    op.execute("DROP TABLE IF EXISTS geo.census_tracts CASCADE")
    op.execute("DROP TABLE IF EXISTS geo.marinas CASCADE")
    op.execute("DROP TABLE IF EXISTS geo.boat_ramps CASCADE")
    op.execute("DROP TABLE IF EXISTS geo.water_bodies CASCADE")
    op.execute("DROP TABLE IF EXISTS raw.nal_attributes CASCADE")
    op.execute("DROP TABLE IF EXISTS raw.parcels_geo CASCADE")

    # Drop schemas (only if empty — safe to skip if tables were dropped above)
    op.execute("DROP SCHEMA IF EXISTS ref CASCADE")
    op.execute("DROP SCHEMA IF EXISTS geo CASCADE")
    op.execute("DROP SCHEMA IF EXISTS raw CASCADE")

    # Leave PostGIS extension installed (shared resource; don't remove it
    # unless you're sure nothing else in the DB uses it)
