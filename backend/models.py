from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    Float,
    Date,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Numeric,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import relationship, sessionmaker
from geoalchemy2 import Geometry
from datetime import datetime
import enum
import os

Base = declarative_base()

class UserRole(str, enum.Enum):
    GUEST = "guest"
    FREE = "free"
    PREMIUM = "premium"
    ADMIN = "admin"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    full_name = Column(String)
    role = Column(String, default=UserRole.FREE)
    remaining_valuations = Column(Integer, default=3)
    is_banned = Column(Boolean, default=False, nullable=False)

class SavedProperty(Base):
    __tablename__ = "saved_properties"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    postal_code = Column(String)
    property_type = Column(String)
    predicted_price = Column(Integer)
    created_at = Column(String)


class ModelVersion(Base):
    """Registry row for a trained/pinned valuation model in MinIO (Postgres is the promote pointer)."""

    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    env = Column(String, nullable=False, index=True)
    object_key = Column(String, nullable=False, unique=True)
    experiment_id = Column(String, nullable=True)
    feature_set_id = Column(String, nullable=True)
    model_id = Column(String, nullable=True)
    rmse = Column(Float, nullable=True)
    is_production = Column(Boolean, default=False, nullable=False)
    registered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    promoted_at = Column(DateTime, nullable=True)
    promoted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class HdbResalePriceIndex(Base):
    """HDB Resale Price Index quarterly level (official series; training + serving archive)."""

    __tablename__ = "hdb_resale_price_index"
    __table_args__ = (
        UniqueConstraint("quarter_label", name="uq_hdb_rpi_quarter_label"),
        UniqueConstraint("year", "quarter_num", name="uq_hdb_rpi_year_quarter_num"),
    )

    quarter_label = Column(String(7), nullable=False, index=True)
    year = Column(SmallInteger, nullable=False)
    quarter_num = Column(SmallInteger, nullable=False)
    period_start = Column(Date, nullable=False, primary_key=True)
    index_value = Column(Numeric(8, 2), nullable=False)
    base_reference = Column(Text, nullable=False, default="2009-Q1=100")
    source = Column(Text, nullable=False, default="data.gov.sg")
    source_resource_id = Column(Text, nullable=False, default="d_14f63e595975691e7c24a27ae4c07c79")
    ingested_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class HdbResaleTransaction(Base):
    __tablename__ = "hdb_resale_transactions"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(String, index=True) # YYYY-MM
    town = Column(String, index=True)
    flat_type = Column(String)
    block = Column(String, index=True)
    street_name = Column(String, index=True)
    block_street = Column(Text, nullable=True)
    storey_range = Column(String)
    floor_area_sqm = Column(Integer)
    flat_model = Column(String)
    lease_commence_date = Column(Integer)
    remaining_lease_years = Column(Integer, nullable=True)
    resale_price = Column(Integer)
    enriched_addr_id = Column(
        Integer,
        ForeignKey("hdb_address_enrichment_onemap.id"),
        nullable=True,
        index=True,
    )


class HdbAddressEnrichmentOnemap(Base):
    __tablename__ = "hdb_address_enrichment_onemap"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    postal_code = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    results_count = Column(Integer, default=0)
    query_sent = Column(String, nullable=False)
    raw_response = Column(Text, nullable=False) # JSON string representation
    last_attempt_at = Column(DateTime, default=datetime.utcnow)
    attempt_count = Column(Integer, default=1)


class HdbPropertyInformation(Base):
    """HDB Property Information catalogue (data.gov.sg); one row per block/street."""

    __tablename__ = "hdb_property_information"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    blk_street = Column(Text, nullable=False, unique=True)
    enriched_addr_id = Column(
        Integer,
        ForeignKey("hdb_address_enrichment_onemap.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    blk_no = Column(Text, nullable=False, index=True)
    street = Column(Text, nullable=False)
    street_norm = Column(Text, nullable=False)
    max_floor_lvl = Column(SmallInteger, nullable=True)
    year_completed = Column(SmallInteger, nullable=False)
    residential = Column(Boolean, nullable=False)
    commercial = Column(Boolean, nullable=False)
    market_hawker = Column(Boolean, nullable=False)
    miscellaneous = Column(Boolean, nullable=False)
    multistorey_carpark = Column(Boolean, nullable=False)
    precinct_pavilion = Column(Boolean, nullable=False)
    bldg_contract_town = Column(String(3), nullable=False)
    hdb_town = Column(Text, nullable=False, index=True)
    total_dwelling_units = Column(Integer, nullable=False, default=0)
    room_1_sold = Column(Integer, nullable=False, default=0)
    room_2_sold = Column(Integer, nullable=False, default=0)
    room_3_sold = Column(Integer, nullable=False, default=0)
    room_4_sold = Column(Integer, nullable=False, default=0)
    room_5_sold = Column(Integer, nullable=False, default=0)
    exec_sold = Column(Integer, nullable=False, default=0)
    multigen_sold = Column(Integer, nullable=False, default=0)
    studio_apartment_sold = Column(Integer, nullable=False, default=0)
    room_1_rental = Column(Integer, nullable=False, default=0)
    room_2_rental = Column(Integer, nullable=False, default=0)
    room_3_rental = Column(Integer, nullable=False, default=0)
    other_room_rental = Column(Integer, nullable=False, default=0)
    source = Column(Text, nullable=False, default="data.gov.sg")
    source_resource_id = Column(Text, nullable=False, default="d_17f5382f26140b1fdae0ba2ef6239d2f")
    ingested_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class HdbMrtRoute(Base):
    """Route legs from an enrichment address row to an MRT physical station.

    Rows are keyed per ``mrt_physical_stations.id`` (interchange footprint). Pass-1
    routing uses the physical station centroid for OneMap; line diversity is only
    used when selecting up to four distinct stations.

    Note: production DB may omit a formal PRIMARY KEY; SQLAlchemy still needs a
    composite key for identity. Prefer ``ALTER TABLE hdb_mrt_routes ADD PRIMARY KEY
    (hdb_addr_id, physical_station_id);`` for ON CONFLICT upserts.
    """

    __tablename__ = "hdb_mrt_routes"
    __table_args__ = (
        PrimaryKeyConstraint(
            "hdb_addr_id", "physical_station_id", name="hdb_mrt_routes_pkey"
        ),
    )

    hdb_addr_id = Column(
        Integer,
        ForeignKey(
            "hdb_address_enrichment_onemap.id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
        nullable=False,
    )
    physical_station_id = Column(
        Integer,
        ForeignKey(
            "mrt_physical_stations.id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
        nullable=False,
    )
    haversine_distance_m = Column(Float, nullable=True)
    
    walk_distance_m = Column(Integer, nullable=True)
    walk_time_mins = Column(Integer, nullable=True)
    raw_walk_response = Column(Text, nullable=True)
    
    drive_distance_m = Column(Integer, nullable=True)
    drive_time_mins = Column(Integer, nullable=True)
    raw_drive_response = Column(Text, nullable=True)
    
    pt_distance_m = Column(Integer, nullable=True)
    pt_time_mins = Column(Integer, nullable=True)
    raw_pt_response = Column(Text, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    filter_state = Column(Text, nullable=False)
    ai_commentary = Column(Text, nullable=True)
    chart_config = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    report_id = Column(Integer, nullable=True)
    title = Column(String, nullable=False)
    context = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer,
        ForeignKey("chat_conversations.id"),
        index=True,
        nullable=False,
    )
    role = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    blocks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MrtPhysicalStation(Base):
    """One geographic MRT interchange / station footprint."""

    __tablename__ = "mrt_physical_stations"

    id = Column(Integer, primary_key=True, index=True)
    canonical_name = Column(String(255), unique=True, nullable=False, index=True)
    lat = Column(Float)
    long = Column(Float)
    geom = Column(Geometry("POINT", srid=4326))
    is_interchange = Column(Boolean, nullable=False, default=False)

    lines = relationship("MrtStationLine", back_populates="physical_station")


class MrtStationLine(Base):
    """One network line variant at an MRT physical station."""

    __tablename__ = "mrt_station_lines"

    id = Column(Integer, primary_key=True, index=True)
    physical_station_id = Column(
        Integer,
        ForeignKey("mrt_physical_stations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    physical_station = relationship(
        "MrtPhysicalStation", back_populates="lines"
    )
    network_line = Column(String(255), nullable=False)
    subproject_or_stage = Column(String(255))
    station_code = Column(String(50), unique=True, nullable=False)
    station_name = Column(String(255), nullable=False, index=True)
    station_status = Column(String(50))
    derived_state = Column(String(24), nullable=True)
    opening_date_confidence = Column(String(16), nullable=True)
    working_name_flag = Column(String(50))
    code_source_type = Column(String(100))
    announcement_date_raw = Column(String(255))
    announcement_date = Column(Date, nullable=True)
    expected_completion_raw = Column(String(255))
    expected_completion = Column(Date, nullable=True)
    opening_date_raw = Column(String(255))
    opening_date = Column(Date, nullable=True)
    dates_source_type = Column(String(100))
    phase2_review_priority = Column(String(50))
    source_url = Column(Text)
    source_note = Column(Text)
    search_term = Column(String(255))
    found = Column(Integer)
    api_response = Column(Text)


# Deprecated name (pre split); retained for scripting compatibility during refactors.
MrtStationTemporal = MrtStationLine


class UraRegion(Base):
    __tablename__ = "ura_mp19_regions_no_sea"

    id = Column(Integer, primary_key=True, index=True)
    region_n = Column(String, index=True)
    region_c = Column(String, index=True)
    geom = Column(Geometry('MULTIPOLYGON', srid=4326))

class UraPlanningArea(Base):
    __tablename__ = "ura_mp19_planning_areas_no_sea"

    id = Column(Integer, primary_key=True, index=True)
    pln_area_n = Column(String, index=True)
    pln_area_c = Column(String, index=True)
    region_c = Column(String, index=True)
    geom = Column(Geometry('GEOMETRY', srid=4326))


class HdbResaleTownPlanningArea(Base):
    """Deterministic resale ``town`` → URA PA names for polygon union."""

    __tablename__ = "hdb_resale_town_planning_area"
    __table_args__ = (
        PrimaryKeyConstraint("town_normalized", "pln_area_n"),
    )

    town_normalized = Column(Text, nullable=False)
    pln_area_n = Column(Text, nullable=False)


class HdbResaleTownLandAreaKm2(Base):
    """PostGIS-derived union footprint (URA MP19 no-sea polygons) per harmonised resale town."""

    __tablename__ = "hdb_resale_town_land_area_km2"

    town_normalized = Column(Text, primary_key=True)
    land_area_sq_km = Column(Float, nullable=False)
    computed_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class HdbTownCompletionFY(Base):
    """HDB completions / under-construction units by FY and town from data.gov.sg."""

    __tablename__ = "hdb_town_completion_fy"
    __table_args__ = (
        PrimaryKeyConstraint("financial_year", "town_normalized", "scheme", "status"),
    )

    financial_year = Column(SmallInteger, nullable=False)
    fy_start_date = Column(Date, nullable=False)
    fy_end_date = Column(Date, nullable=False)
    town_normalized = Column(Text, nullable=False)
    scheme = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    n_units = Column(Integer, nullable=False)
    source = Column(Text, nullable=False, default="data.gov.sg")
    source_resource_id = Column(Text, nullable=False, default="d_9bbcd0c9b0351c7f41c9bfdcdc746668")
    ingested_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class HdbEstateMaturityByTownMonth(Base):
    """Town × transaction-month estate maturity aggregates (joined on resale spine)."""

    __tablename__ = "hdb_estate_maturity_by_town_month"
    __table_args__ = (
        PrimaryKeyConstraint("town_normalized", "year_month"),
    )

    town_normalized = Column(Text, nullable=False)
    year_month = Column(Text, nullable=False)
    avg_residential_block_age_years = Column(Float, nullable=True)
    town_completed_residential_units_stock = Column(Integer, nullable=True)
    town_land_area_km2 = Column(Float, nullable=True)
    town_dwelling_unit_density = Column(Float, nullable=True)
    town_units_under_construction = Column(Integer, nullable=True)
    town_hdb_completed_units_roll36m = Column(Integer, nullable=True)
    town_supply_maturity_ratio = Column(Float, nullable=True)
    materialized_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class HdbBuilding(Base):
    """HDB building footprints (Data.gov.sg HDBExistingBuilding GeoJSON)."""

    __tablename__ = "hdb_buildings"
    __table_args__ = (
        Index("idx_hdb_buildings_geom", "geom", postgresql_using="gist"),
        Index("idx_hdb_buildings_postal", "postal_cod"),
        Index("idx_hdb_buildings_shape_area", "shape_area"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    objectid = Column(Integer, nullable=True)
    blk_no = Column(String(20), nullable=True)
    st_cod = Column(String(20), nullable=True)
    entityid = Column(Integer, nullable=True)
    postal_cod = Column(String(10), nullable=True)
    inc_crc = Column(String(20), nullable=True)
    fmel_upd_d = Column(String(20), nullable=True)
    shape_area = Column(Float, nullable=True)
    shape_len = Column(Float, nullable=True)
    geom = Column(Geometry("GEOMETRY", srid=4326), nullable=True)


DATABASE_URL = (
    os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL") or "sqlite:///./homeyai.db"
).strip() or "sqlite:///./homeyai.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """
    Seed the database with initial data if tables are empty.
    Schema creation is handled by Alembic migrations (see alembic/versions/).
    For existing databases that predate Alembic, create_all is kept as a
    safe fallback — it is a no-op if tables already exist.
    """
    Base.metadata.create_all(bind=engine)

    from auth import get_password_hash
    from datetime import datetime

    db = SessionLocal()
    try:
        if not db.query(User).first():
            admin = User(email="admin@homeyai.com", hashed_password=get_password_hash("admin123"), full_name="Admin User", role="admin")
            free_user = User(email="free@homeyai.com", hashed_password=get_password_hash("free123"), full_name="Free User", role="free")
            premium = User(email="premium@homeyai.com", hashed_password=get_password_hash("premium123"), full_name="Premium User", role="premium")

            db.add_all([admin, free_user, premium])
            db.commit()

            mock_p1 = SavedProperty(user_id=free_user.id, postal_code="120456", property_type="HDB", predicted_price=580000, created_at=datetime.now().isoformat())
            mock_p2 = SavedProperty(user_id=free_user.id, postal_code="529900", property_type="Condo", predicted_price=1250000, created_at=datetime.now().isoformat())

            db.add_all([mock_p1, mock_p2])
            db.commit()

        from ingestion import run_ingestion, ingest_master_plan_data, _make_minio_client
        run_ingestion(db)
        
        # Ingest geographic Master Plan data
        mc = _make_minio_client()
        ingest_master_plan_data(db, mc)
    except Exception as e:
        print(f"Startup Error: {e}")
    finally:
        db.close()
