import sys
from pathlib import Path

# Monorepo root — enables ``from modelling...`` in routes during tests.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os

# Must be set before importing main — startup calls init_db() which runs create_all()
# and GeoAlchemy spatial tables require PostGIS, not plain SQLite.
os.environ["SKIP_DB_INIT_ON_STARTUP"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import models

from sqlalchemy.pool import StaticPool

# Use in-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Patch before importing main
models.engine = engine
models.SessionLocal = TestingSessionLocal

from main import app, get_db  # noqa: E402


def _tables_for_sqlite_tests():
    """Tables needed for API tests. Exclude GeoAlchemy models — SQLite has no PostGIS/SpatiaLite in CI."""
    return [
        models.User.__table__,
        models.SavedProperty.__table__,
        models.ModelVersion.__table__,
        models.HdbResaleTransaction.__table__,
        models.AnalysisReport.__table__,
        models.ChatConversation.__table__,
        models.ChatMessage.__table__,
    ]


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    for table in _tables_for_sqlite_tests():
        table.create(bind=engine, checkfirst=True)
    
    # Manually seed data for tests
    from auth import get_password_hash
    from models import User
    
    db = TestingSessionLocal()
    admin = User(email="admin@homeyai.com", hashed_password=get_password_hash("admin123"), full_name="Admin User", role="admin")
    free_user = User(email="free@homeyai.com", hashed_password=get_password_hash("free123"), full_name="Free User", role="free")
    db.add_all([admin, free_user])
    db.commit()
    db.close()
    
    yield
    for table in reversed(_tables_for_sqlite_tests()):
        table.drop(bind=engine, checkfirst=True)

@pytest.fixture()
def client():
    # Use FastAPI standard override
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
            
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
