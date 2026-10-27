from fastapi import FastAPI, Response, Depends, HTTPException, Query
from starlette.requests import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from typing import Any, Dict, List, Optional, Set
from statistics import median
import asyncio
import logging
import random
import json
import jwt
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
import zipfile

from starlette.background import BackgroundTask

# Prefer monorepo ``modelling/`` (full feature-set registry, inference, training) over
# ``backend/modelling`` stubs — both are named ``modelling`` on ``sys.path``.
_backend_dir = Path(__file__).resolve().parent
_repo_root = _backend_dir.parent
if (_repo_root / "modelling" / "config" / "feature_sets.py").is_file():
    _repo = str(_repo_root)
    _backend = str(_backend_dir)
    _tail = [p for p in sys.path if p not in (_repo, _backend)]
    sys.path[:] = [_repo, _backend] + _tail

from services import (
    geospatial_service,
    analytics_service,
    report_service,
    minio_catalog,
    ml_service,
    model_store,
    sentiment_service,
)
from services.experiment_report_build import ExperimentReportBuildError, ensure_experiment_report_presigned_url
from services.training_report_feature_labels import (
    feature_selection_policy_from_metrics,
    feature_selection_summary_from_metrics,
)
import ai_service
from models import (
    User,
    SessionLocal,
    init_db,
    UserRole,
    SavedProperty,
    AnalysisReport,
    ChatConversation,
    ChatMessage as DBChatMessage,
    ModelVersion,
)
from auth import get_password_hash, verify_password, create_access_token, SECRET_KEY, ALGORITHM
from sqlalchemy.orm import Session
from sqlalchemy import func

from hdb_storey import parse_storey_range_bounds

_REPO_ROOT = _repo_root

logger = logging.getLogger(__name__)


app = FastAPI(title="HomeyAI Valuation & Geospatial API")

from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1024)

_ESTIMATOR_LABELS = {
    "linear": "Linear Regression",
    "random_forest": "Random Forest",
    "mlp": "MLP",
    "xgboost": "XGBoost",
    "xgboost_eco": "XGBoost (eco)",
    "xgboost_grouped": "XGBoost (grouped)",
    "xgboost_tuned": "XGBoost (tuned)",
    "extra_trees": "Extra Trees",
    "lightgbm": "LightGBM",
    "ridge": "Ridge Regression",
}

# Approximate Downtown Core centroid for “distance to CBD” copy (km, great-circle).
_CBD_REFERENCE_LAT = 1.2891
_CBD_REFERENCE_LNG = 103.8523


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    r_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    lat1r = radians(lat1)
    lat2r = radians(lat2)
    h = sin(dlat / 2) ** 2 + cos(lat1r) * cos(lat2r) * sin(dlon / 2) ** 2
    return 2 * r_km * asin(min(1.0, sqrt(h)))


_COASTLINE_LANDMARKS = (
    {"name": "East Coast Park", "lat": 1.3005, "lng": 103.9122},
    {"name": "West Coast Park", "lat": 1.2915, "lng": 103.7665},
    {"name": "Punggol Promenade", "lat": 1.4195, "lng": 103.9265},
    {"name": "Pasir Ris Beach", "lat": 1.3725, "lng": 103.9495},
    {"name": "Changi Beach", "lat": 1.3890, "lng": 104.0030},
    {"name": "Sembawang Park", "lat": 1.4705, "lng": 103.8305},
)

_LANDUSE_NEG_KEYS = (
    ("dist_to_nearest_cemetery", "Cemetery"),
    ("dist_to_nearest_b2_zone", "B2 industrial"),
    ("dist_to_nearest_special_use", "Special-use land"),
)


def _format_distance_str(metres: float | None = None, km: float | None = None) -> str:
    if metres is not None and metres >= 0:
        if metres < 1000:
            return f"{int(round(metres))}m"
        return f"{metres / 1000:.1f} km"
    if km is not None and km >= 0:
        if km < 1:
            return f"{int(round(km * 1000))}m"
        return f"{km:.1f} km"
    return "—"


def _format_transport_current_proxy(nearest_mrt: dict | None) -> str | None:
    if not nearest_mrt:
        return None
    name = str(nearest_mrt.get("name") or "").strip()
    if not name or name.lower() == "unknown":
        return None
    if not name.upper().endswith(" MRT"):
        name = f"{name} MRT"
    code = nearest_mrt.get("station_code")
    line_part = f" ({code})" if code else ""
    try:
        dist_km = float(nearest_mrt.get("distance", 0))
    except (TypeError, ValueError):
        dist_km = 0.0
    return f"{name}{line_part} — {_format_distance_str(km=dist_km)}"


def _format_transport_future_proxy(mrt_overrides: dict | None) -> str | None:
    if not mrt_overrides:
        return None
    dist_raw = mrt_overrides.get("nearest_planned_mrt_dist")
    try:
        dist_m = float(dist_raw) if dist_raw is not None else None
    except (TypeError, ValueError):
        dist_m = None
    if dist_m is None or dist_m <= 0:
        if mrt_overrides.get("has_future_upside"):
            return "Planned MRT nearby (distance unavailable)"
        return "No planned MRT nearby"
    lines = mrt_overrides.get("nearest_planned_lines")
    line_str = ""
    if isinstance(lines, (list, tuple)) and lines:
        line_str = ", ".join(str(x).strip() for x in lines[:3] if str(x).strip())
    station = f"Planned MRT ({line_str})" if line_str else "Planned MRT"
    opens = ""
    days_raw = mrt_overrides.get("days_to_mrt_opening")
    try:
        days = float(days_raw) if days_raw is not None else None
    except (TypeError, ValueError):
        days = None
    if days is not None and days > 0:
        years = max(0.1, round(days / 365.25, 1))
        opens = f", opens ~{years} yrs"
    return f"{station} — {_format_distance_str(metres=dist_m)}{opens}"


def _format_landuse_negative_proxy(feature_extras: dict | None) -> str | None:
    if not feature_extras:
        return None
    parts: list[str] = []
    for key, label in _LANDUSE_NEG_KEYS:
        raw = feature_extras.get(key)
        if raw is None:
            continue
        try:
            km = float(raw)
        except (TypeError, ValueError):
            continue
        if km < 2.0:
            parts.append(f"{label} {km:.1f} km")
    return " · ".join(parts) if parts else None


def _nearest_coastline_landmark(lat: float, lng: float) -> dict | None:
    best_name: str | None = None
    best_km = float("inf")
    for lm in _COASTLINE_LANDMARKS:
        d = _haversine_km(lat, lng, lm["lat"], lm["lng"])
        if d < best_km:
            best_km = d
            best_name = lm["name"]
    if best_name is None:
        return None
    return {"distance_km": round(best_km, 2), "landmark": best_name}


def _build_driver_context(
    *,
    nearby_mrts: list | None,
    mrt_overrides: dict | None,
    school_str: str | None,
    feature_extras: dict | None,
    lat: float | None,
    lng: float | None,
) -> dict:
    nearest_mrt = nearby_mrts[0] if nearby_mrts else None
    coastline = None
    if lat is not None and lng is not None:
        coastline = _nearest_coastline_landmark(lat, lng)
    return {
        "transport_current": _format_transport_current_proxy(nearest_mrt),
        "transport_future": _format_transport_future_proxy(mrt_overrides),
        "primary_school": school_str if school_str and school_str != "Data not available" else None,
        "landuse_negative": _format_landuse_negative_proxy(feature_extras),
        "coastline": coastline,
    }


def _repo_root() -> Path:
    return _REPO_ROOT


def _modelling_dir() -> Path:
    """Path to the ``modelling/`` tree (``outputs/``, ``experiments/``, …).

    - **Local / monorepo:** ``<repo>/backend/main.py`` → ``<repo>/modelling``.
    - **Docker (backend only at ``/app``):** mount the repo's ``modelling`` folder at
      ``/modelling`` and set ``HOMEYAI_MODELLING_DIR=/modelling`` (see ``docker-compose.yml``).
    """
    override = os.environ.get("HOMEYAI_MODELLING_DIR", "").strip()
    if override:
        return Path(override).resolve()
    repo = Path(__file__).resolve().parent.parent
    bundled = repo / "modelling"
    if bundled.is_dir():
        return bundled.resolve()
    docker_mount = Path("/modelling")
    if docker_mount.is_dir():
        return docker_mount.resolve()
    return bundled.resolve()


def _split_exp_timestamp_dirname(dirname: str) -> tuple[str, str] | None:
    """``model__feature__20260510T145026Z`` → (logical id, UTC stamp)."""
    if not dirname.endswith("Z") or "__" not in dirname:
        return None
    head, ts = dirname.rsplit("__", 1)
    if not re.fullmatch(r"\d{8}T\d{6}Z", ts):
        return None
    return head, ts


def _build_cors_origins() -> list[str]:
    """Browser Origin must match exactly; VM host comes from REMOTE_VM_IP only."""
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    remote = os.getenv("REMOTE_VM_IP", "").strip()
    if remote:
        origins.extend(
            [
                f"http://{remote}:3000",
                f"http://{remote}:8000",
            ]
        )
    extra = os.getenv("CORS_EXTRA_ORIGINS", "")
    if extra:
        origins.extend([o.strip() for o in extra.split(",") if o.strip()])
    return list(dict.fromkeys(origins))


def _experiment_row_from_metrics_dict(model_key: str, data: dict, run_id: str) -> dict | None:
    """Build comparison row from ``metrics.json`` content (MinIO)."""
    tm = data.get("test_metrics") or {}
    rmse = tm.get("rmse")
    if rmse is None:
        return None
    tc = data.get("training_context") or {}
    model_id = (data.get("model") or "").strip()
    fs = (data.get("feature_set") or "").strip()
    parsed = _split_exp_timestamp_dirname(run_id)
    experiment_id = parsed[0] if parsed else run_id
    stamp = parsed[1] if parsed else None
    tw_raw = tc.get("training_wall_seconds")
    training_wall_seconds: float | None = None
    if tw_raw is not None:
        try:
            twf = float(tw_raw)
            if twf == twf and twf not in (float("inf"), float("-inf")):
                training_wall_seconds = twf
        except (TypeError, ValueError):
            pass
    fs_summary = feature_selection_summary_from_metrics(data)
    fs_pol = fs_summary.get("policy")
    fs_removed_n = fs_summary.get("columns_removed_count")
    return {
        "id": run_id,
        "experiment_id": experiment_id,
        "estimator": _ESTIMATOR_LABELS.get(
            model_id, model_id.replace("_", " ").title() if model_id else ""
        ),
        "feature_set": fs,
        "feature_set_id": fs,
        "model_id": model_id,
        "rmse": float(rmse),
        "mae": float(tm["mae"]) if tm.get("mae") is not None else None,
        "r2": float(tm["r2"]) if tm.get("r2") is not None else None,
        "mape": float(tm["mape"]) if tm.get("mape") is not None else None,
        "cv_rmse": float(data["best_cv_rmse"]) if data.get("best_cv_rmse") is not None else None,
        "n_train": int(data["n_train"]) if data.get("n_train") is not None else None,
        "n_test": int(data["n_test"]) if data.get("n_test") is not None else None,
        "mrt_pit_min_years": tc.get("mrt_pit_min_years"),
        "feature_selection_policy": fs_pol if isinstance(fs_pol, str) else None,
        "feature_selection_columns_removed_count": fs_removed_n
        if isinstance(fs_removed_n, int)
        else None,
        "run_directory": f"minio:{model_key}",
        "run_timestamp": stamp,
        "test_fraction": tc.get("test_fraction"),
        "cv_splits": tc.get("cv_splits"),
        "max_train_rows": tc.get("max_train_rows"),
        "training_wall_seconds": training_wall_seconds,
    }


def _collect_experiment_rows_from_minio(
    env: str | None = None,
    *,
    prefetched_experiment_model_keys: list[str] | None = None,
) -> list[dict]:
    """All training/publish runs: ``{env}/valuation/experiments/*/model.pkl`` plus legacy ``artifacts`` only."""
    use_env = (env or os.getenv("MODEL_ENV", "prod")).strip()
    rows_by_id: dict[str, dict] = {}
    try:
        exp_keys = (
            prefetched_experiment_model_keys
            if prefetched_experiment_model_keys is not None
            else model_store.list_valuation_experiment_model_keys(use_env)
        )
        for mk in exp_keys:
            rid = model_store.experiment_folder_from_model_object_key(mk)
            if not rid:
                continue
            base = mk.rsplit("/", 1)[0]
            raw = model_store.load_json_object_key(f"{base}/metrics.json")
            if not raw:
                continue
            row = _experiment_row_from_metrics_dict(mk, raw, rid)
            if row:
                rows_by_id[rid] = row
    except Exception:
        logger.exception("listing MinIO experiment metrics failed")

    try:
        art_keys = model_store.list_valuation_model_object_keys(use_env)
        for mk in art_keys:
            rid = model_store.folder_name_from_model_object_key(mk)
            if not rid or rid in rows_by_id:
                continue
            base = mk.rsplit("/", 1)[0]
            raw = model_store.load_json_object_key(f"{base}/metrics.json")
            if not raw:
                continue
            row = _experiment_row_from_metrics_dict(mk, raw, rid)
            if row:
                rows_by_id[rid] = row
    except Exception:
        logger.exception("listing MinIO artifact metrics failed")

    rows = list(rows_by_id.values())
    rows.sort(
        key=lambda e: e["id"].split("__")[-1] if "__" in e["id"] else e["id"],
        reverse=True,
    )
    return rows


def _load_metrics_payload(prefetched_experiment_model_keys: list[str] | None = None) -> dict:
    """Build experiment comparison payload for ``/api/model/metrics`` from MinIO only."""
    mroot = _modelling_dir()
    experiments = _collect_experiment_rows_from_minio(
        prefetched_experiment_model_keys=prefetched_experiment_model_keys,
    )

    with_rmse = [e for e in experiments if e.get("rmse") is not None]
    best = min(with_rmse, key=lambda x: float(x["rmse"])) if with_rmse else None
    shap_png = mroot / "outputs" / "mrt_pit_features" / "rf_shap_bar.png"
    best_out: dict[str, Any] = {}
    if best is not None:
        best_out = {
            "id": best["id"],
            "rmse": best.get("rmse"),
            "mae": best.get("mae"),
            "r2": best.get("r2"),
            "cv_rmse": best.get("cv_rmse"),
            "n_train": best.get("n_train"),
            "n_test": best.get("n_test"),
            "mape": best.get("mape"),
            "mrt_pit_min_years": best.get("mrt_pit_min_years"),
            "feature_selection_policy": best.get("feature_selection_policy"),
            "feature_selection_columns_removed_count": best.get("feature_selection_columns_removed_count"),
        }
    return {
        "experiments": experiments,
        "best": best_out,
        "shap_chart_available": shap_png.is_file(),
    }


def _production_model_key_from_db(db: Session) -> str | None:
    """Return MinIO object key for the current MODEL_ENV production row, if any."""
    try:
        env = (os.getenv("MODEL_ENV", "prod")).strip()
        row = (
            db.query(ModelVersion)
            .filter(ModelVersion.env == env, ModelVersion.is_production.is_(True))
            .order_by(ModelVersion.promoted_at.desc())
            .first()
        )
        if row and row.object_key:
            return str(row.object_key).strip()
    except Exception:
        logger.exception("model_versions production key query failed")
    return None


def _enrich_admin_serving_status_from_registry(db: Session, base: dict[str, Any]) -> dict[str, Any]:
    """Attach registry promotion + holdout RMSE to ``ml_service.admin_serving_status()`` (dashboard + GET /status)."""
    key = base.get("model_object_key")
    promoted_at: str | None = None
    promoted_by: str | None = None
    if key:
        env = (os.getenv("MODEL_ENV", "prod")).strip()
        try:
            mv = (
                db.query(ModelVersion)
                .filter(
                    ModelVersion.env == env,
                    ModelVersion.object_key == key,
                    ModelVersion.is_production.is_(True),
                )
                .first()
            )
            if mv and mv.promoted_at:
                promoted_at = mv.promoted_at.isoformat()
            if mv and mv.promoted_by_user_id:
                pu = db.query(User).filter(User.id == mv.promoted_by_user_id).first()
                if pu and pu.full_name:
                    promoted_by = pu.full_name
        except Exception:
            logger.exception("model_versions join for serving status failed")
    holdout = ml_service.holdout_rmse_from_loaded_model()
    return {
        **base,
        "promoted_at": promoted_at,
        "promoted_by": promoted_by,
        "holdout_rmse": holdout,
    }


def _admin_serving_status_payload_sync() -> dict[str, Any]:
    """Threadpool-safe: own DB session for admin dashboard status bundle."""
    base = ml_service.admin_serving_status()
    db = SessionLocal()
    try:
        return _enrich_admin_serving_status_from_registry(db, base)
    finally:
        db.close()


def _upsert_model_version_as_production(
    db: Session,
    *,
    env: str,
    object_key: str,
    experiment_id: str | None,
    feature_set_id: str | None,
    model_id: str | None,
    rmse: float | None,
    user_id: int | None,
) -> None:
    now = datetime.now(timezone.utc)
    env = env.strip()
    db.query(ModelVersion).filter(ModelVersion.env == env).update(
        {"is_production": False},
        synchronize_session=False,
    )
    existing = db.query(ModelVersion).filter(ModelVersion.object_key == object_key).first()
    if existing:
        existing.env = env
        existing.experiment_id = experiment_id
        existing.feature_set_id = feature_set_id
        existing.model_id = model_id
        existing.rmse = rmse
        existing.is_production = True
        existing.promoted_at = now
        existing.promoted_by_user_id = user_id
    else:
        db.add(
            ModelVersion(
                env=env,
                object_key=object_key,
                experiment_id=experiment_id,
                feature_set_id=feature_set_id,
                model_id=model_id,
                rmse=rmse,
                is_production=True,
                registered_at=now,
                promoted_at=now,
                promoted_by_user_id=user_id,
            )
        )
    db.commit()


# Initialize DB on startup (not globally on import). Tests set SKIP_DB_INIT_ON_STARTUP
# and build schema via conftest + SQLite without PostGIS/SpatiaLite.
@app.on_event("startup")
def on_startup():
    if os.getenv("SKIP_DB_INIT_ON_STARTUP"):
        ml_service.init()
        return
    init_db()
    db = SessionLocal()
    try:
        explicit = _production_model_key_from_db(db)
    finally:
        db.close()
    ml_service.init(explicit_key=explicit)

# Enable CORS for frontend communication (browser Origin must match exactly).
_cors_origins = _build_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict


class TriggerMrtRoutingRequest(BaseModel):
    """Body for enqueueing Prefect deployment ``hdb-mrt-routing`` / ``mrt-routing-default``."""

    rerun_partial: bool = False
    limit: int = 5000


class AdminModelPromoteBody(BaseModel):
    """Pin production model to a MinIO ``model.pkl`` key; persisted in ``model_versions``."""

    object_key: str = Field(..., min_length=1)


class AdminModelTrainBody(BaseModel):
    """Parameters forwarded to the Prefect training deployment."""

    experiment_id: str = Field(..., min_length=1)
    feature_set_id: str = Field(..., min_length=1)
    feature_selection_policy: Optional[str] = Field(
        default=None,
        description="Optional: advisory_only | apply — overrides HOMEYAI_FEATURE_SELECTION_POLICY for this run (requires redeployed Prefect + Modal app).",
    )


class AdminModelTrainBatchBody(BaseModel):
    """Batch training: Prefect ``homeyai-model-train-batch`` (defaults to PERFORMANCE_PLAN_V1)."""

    experiment_ids: Optional[list[str]] = None
    dataset_version: Optional[str] = None
    use_gpu: Optional[bool] = None
    max_concurrent: Optional[int] = Field(default=None, ge=1, le=32)
    feature_selection_policy: Optional[str] = Field(
        default=None,
        description="Optional: advisory_only | apply — per-batch policy without flipping Modal secrets.",
    )


@app.post("/api/register", response_model=Token)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user_data.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_pass = get_password_hash(user_data.password)
    new_user = User(
        email=user_data.email,
        hashed_password=hashed_pass,
        full_name=user_data.full_name,
        role=UserRole.FREE
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    access_token = create_access_token(data={"sub": new_user.email, "role": new_user.role})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "email": new_user.email,
            "full_name": new_user.full_name,
            "role": new_user.role
        }
    }

@app.post("/api/login", response_model=Token)
async def login(login_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if getattr(user, "is_banned", False):
        raise HTTPException(status_code=403, detail="Account suspended")

    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        }
    }

class ValuationInput(BaseModel):
    postal_code: str
    town: str
    flat_type: str
    flat_model_grouped: str
    region: str
    storey_midpoint: int
    floor_area_sqm: float
    remaining_lease_years: int
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    lease_commence_year: Optional[int] = None

class LocationInput(BaseModel):
    lat: float
    lng: float
    radius: Optional[float] = 1.0


class PoiNearbyRequest(BaseModel):
    """Places-of-interest query around a resolved HDB enrichment coordinate."""

    postal_code: Optional[str] = None
    property_name: Optional[str] = None
    radius_m: float = Field(default=1000.0, ge=50.0, le=10000.0, description="Search radius in metres")

class PolygonInput(BaseModel):
    coords: List[List[float]] # List of [lat, lng]

class AreaInsightInput(BaseModel):
    region: str

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="api/login", auto_error=False)

# Admin-only subscription preview: send X-Homey-Preview-Role: free | premium (no DB writes).
ADMIN_SUBSCRIPTION_PREVIEW_HEADER = "X-Homey-Preview-Role"


def _admin_subscription_preview_tier(request: Request) -> Optional[UserRole]:
    raw = (request.headers.get(ADMIN_SUBSCRIPTION_PREVIEW_HEADER) or "").strip().lower()
    if raw == "free":
        return UserRole.FREE
    if raw == "premium":
        return UserRole.PREMIUM
    return None


def has_premium_entitlements(user: User, request: Request) -> bool:
    """Whether this request should receive premium-only features (real premium or admin preview)."""
    if user.role == UserRole.PREMIUM:
        return True
    if user.role == UserRole.ADMIN:
        return _admin_subscription_preview_tier(request) == UserRole.PREMIUM
    return False


def get_optional_user(token: Optional[str] = Depends(oauth2_scheme_optional), db: Session = Depends(get_db)):
    if not token:
        return None
    from jose import JWTError, jwt
    from auth import SECRET_KEY, ALGORITHM
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
    except JWTError:
        return None
    user = db.query(User).filter(User.email == email).first()
    if user and getattr(user, "is_banned", False):
        raise HTTPException(status_code=403, detail="Account suspended")
    return user

@app.get("/")
def read_root():
    return {"message": "Welcome to HomeyAI API"}

@app.get("/api/version")
def get_version():
    return {
        "version": os.getenv("APP_VERSION", "dev"),
        "commit": os.getenv("GIT_COMMIT", "unknown"),
        "model_env": os.getenv("MODEL_ENV", "prod"),
    }


@app.get("/api/model/info")
def get_public_model_info(db: Session = Depends(get_db)):
    """Production valuation model (in-memory loader + registry); unauthenticated read-only transparency."""
    base: dict[str, Any] = {
        "is_ready": ml_service.is_ready(),
        "feature_set_id": ml_service.feature_set_id(),
        "experiment_id": ml_service.manifest_meta().get("experiment_id"),
        "model_id": ml_service.manifest_meta().get("model_id"),
        "model_object_key": ml_service.model_object_key(),
        "load_error": ml_service.load_error_message(),
        "holdout_rmse": ml_service.holdout_rmse_from_loaded_model(),
    }
    key = ml_service.model_object_key()
    promoted_at: str | None = None
    promoted_by: str | None = None
    if key:
        env = (os.getenv("MODEL_ENV", "prod")).strip()
        try:
            mv = (
                db.query(ModelVersion)
                .filter(
                    ModelVersion.env == env,
                    ModelVersion.object_key == key,
                    ModelVersion.is_production.is_(True),
                )
                .first()
            )
            if mv and mv.promoted_at:
                promoted_at = mv.promoted_at.isoformat()
            if mv and mv.promoted_by_user_id:
                pu = db.query(User).filter(User.id == mv.promoted_by_user_id).first()
                if pu and pu.full_name:
                    promoted_by = pu.full_name
        except Exception:
            logger.exception("public model info registry lookup failed")
    base["promoted_at"] = promoted_at
    base["promoted_by"] = promoted_by
    return base


@app.get("/api/model/metrics")
def get_model_metrics():
    """Experiment comparison rows + lowest-RMSE ``best`` from MinIO (RMSE in S$)."""
    return _load_metrics_payload()


@app.get("/api/admin/ml/data-report")
def get_ml_data_report():
    """Consolidated SQL + engineered-frame training data quality (from model sweep or report script)."""
    path = _modelling_dir() / "outputs" / "training_data_report.json"
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="training_data_report.json not found (run modelling/runners/run_model_sweep.py or report_training_completeness --append-data-quality-report).",
        )
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/model/shap_chart")
def get_model_shap_chart():
    """Mean |SHAP| bar chart from modelling/report_mrt_shap.py (if generated)."""
    path = _modelling_dir() / "outputs" / "mrt_pit_features" / "rf_shap_bar.png"
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="SHAP chart not generated yet (run modelling/report_mrt_shap.py)",
        )
    return FileResponse(path, media_type="image/png")

@app.get("/api/admin/ml/runs")
def get_ml_runs():
    """Experiment run folders from MinIO ``valuation/experiments`` (canonical store)."""
    runs: list[dict[str, Any]] = []
    seen: set[str] = set()
    env = os.getenv("MODEL_ENV", "prod").strip()
    try:
        for mk in model_store.list_valuation_experiment_model_keys(env):
            row = model_store.catalog_row_from_minio_experiment_model_key(mk)
            if row and row["id"] not in seen:
                runs.append(dict(row))
                seen.add(row["id"])
    except Exception:
        logger.exception("get_ml_runs MinIO listing failed")

    runs.sort(key=lambda x: _run_id_sortable_ts_ms(x["id"]), reverse=True)

    folders: set[str] = set()
    try:
        folders = model_store.valuation_artifact_folder_names(env)
    except Exception:
        folders = set()
    for r in runs:
        r["has_minio_experiment"] = True
        r["has_minio_artifact"] = model_store.local_run_has_minio_counterpart(r["id"], folders)
    return {"runs": runs}


def _catalog_minio_experiment_directories(
    env: str,
    prefetched_model_keys: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """All ``{env}/valuation/experiments/<run_id>/`` runs with config/metrics when present."""
    by_id: dict[str, dict[str, Any]] = {}
    try:
        keys = (
            prefetched_model_keys
            if prefetched_model_keys is not None
            else model_store.list_valuation_experiment_model_keys(env)
        )
        for mk in keys:
            row = model_store.catalog_row_from_minio_experiment_model_key(mk)
            if row:
                by_id[row["id"]] = row
    except Exception:
        logger.exception("catalog MinIO experiments failed")
    return by_id


def _slim_catalog_mrt_years(row: dict[str, Any]) -> int | None:
    """Expose MRT window for dashboard filtering (from metrics.training_context)."""
    m = row.get("metrics")
    if not isinstance(m, dict):
        return None
    tc = m.get("training_context")
    if not isinstance(tc, dict):
        return None
    v = tc.get("mrt_pit_min_years")
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
            return None
        return int(v)
    return None


def _slim_catalog_training_wall_seconds(row: dict[str, Any]) -> float | None:
    """Expose ``train_from_frame`` wall time for slim dashboard rows."""
    m = row.get("metrics")
    if not isinstance(m, dict):
        return None
    tc = m.get("training_context")
    if not isinstance(tc, dict):
        return None
    v = tc.get("training_wall_seconds")
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def _slim_catalog_feature_selection_policy(row: dict[str, Any]) -> str | None:
    m = row.get("metrics")
    return feature_selection_policy_from_metrics(m if isinstance(m, dict) else None)


def _slim_catalog_feature_selection_columns_removed_count(row: dict[str, Any]) -> int | None:
    m = row.get("metrics")
    summary = feature_selection_summary_from_metrics(m if isinstance(m, dict) else None)
    n = summary.get("columns_removed_count")
    return int(n) if isinstance(n, int) else None


def _run_id_sortable_ts_ms(run_id: str) -> int:
    """Parses ``…__YYYYMMDDTHHMMSSZ`` tail for newest-first ordering; digit-only tails as tie-break."""
    rid = run_id.strip()
    tail = rid.split("__")[-1] if "__" in rid else rid
    if re.match(r"^\d{8}T\d{6}Z$", tail):
        try:
            from datetime import datetime, timezone

            dt = datetime.strptime(tail, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            return 0
    if tail.isdigit():
        try:
            return int(tail)
        except ValueError:
            return 0
    return 0


def _admin_ml_experiments_catalog(
    use_env: str | None,
    prefetched_folder_names: set[str] | None = None,
    slim_rows: bool = False,
    prefetched_experiment_model_keys: list[str] | None = None,
) -> dict[str, Any]:
    """MinIO experiment catalog + publish flags for admin UI."""
    env = (use_env or os.getenv("MODEL_ENV", "prod")).strip()
    by_id = _catalog_minio_experiment_directories(env, prefetched_model_keys=prefetched_experiment_model_keys)
    experiment_folders: set[str] = set()
    exp_mks = (
        prefetched_experiment_model_keys
        if prefetched_experiment_model_keys is not None
        else model_store.list_valuation_experiment_model_keys(env)
    )
    try:
        for mk in exp_mks:
            fn = model_store.experiment_folder_from_model_object_key(mk)
            if fn:
                experiment_folders.add(fn)
    except Exception:
        pass
    folders: set[str] = set()
    if prefetched_folder_names is not None:
        folders = prefetched_folder_names
    else:
        try:
            folders = model_store.valuation_artifact_folder_names(env)
        except Exception:
            folders = set()
    experiments: list[dict[str, Any]] = []
    for rid in sorted(
        by_id.keys(),
        key=_run_id_sortable_ts_ms,
        reverse=True,
    ):
        row = by_id[rid]
        in_minio_exp = rid in experiment_folders
        published = in_minio_exp or model_store.local_run_has_minio_counterpart(rid, folders)
        publish_key = f"{env}/valuation/experiments/{rid}/model.pkl" if in_minio_exp else None
        cfg = row.get("config") if isinstance(row.get("config"), dict) else {}
        ex = cfg.get("experiment") if isinstance(cfg.get("experiment"), dict) else {}
        tm = (
            (row.get("metrics") or {}).get("test_metrics")
            if isinstance(row.get("metrics"), dict)
            else None
        )
        rmse = tm.get("rmse") if isinstance(tm, dict) else None
        if slim_rows:
            experiments.append(
                {
                    "id": rid,
                    "published": published,
                    "has_minio_experiment": in_minio_exp,
                    "publish_object_key": publish_key,
                    "has_minio_artifact": published,
                    "has_metrics": bool(row.get("has_metrics")),
                    "model_id": ex.get("model_id"),
                    "feature_set_id": ex.get("feature_set_id"),
                    "rmse": rmse,
                    "mrt_pit_min_years": _slim_catalog_mrt_years(row),
                    "training_wall_seconds": _slim_catalog_training_wall_seconds(row),
                    "feature_selection_policy": _slim_catalog_feature_selection_policy(row),
                    "feature_selection_columns_removed_count": _slim_catalog_feature_selection_columns_removed_count(
                        row
                    ),
                }
            )
        else:
            experiments.append(
                {
                    "id": rid,
                    "published": published,
                    "has_minio_experiment": in_minio_exp,
                    "publish_object_key": publish_key,
                    "has_minio_artifact": published,
                    "has_metrics": bool(row.get("has_metrics")),
                    "config": row.get("config"),
                    "metrics": row.get("metrics"),
                    "best_params": row.get("best_params"),
                }
            )
    return {"env": env, "experiments": experiments}


def _read_one_experiment_directory(run_id: str, env: str | None = None) -> dict[str, Any] | None:
    """Load ``experiments/<run_id>/`` from MinIO only."""
    use_env = (env or os.getenv("MODEL_ENV", "prod")).strip()
    rid = run_id.strip().strip("/")
    mk = f"{use_env}/valuation/experiments/{rid}/model.pkl"
    try:
        if model_store.object_exists(mk):
            row = model_store.catalog_row_from_minio_experiment_model_key(mk)
            if row:
                return row
    except Exception:
        logger.exception("read experiment from MinIO failed")
    return None


def _admin_experiment_run_detail_sync(run_id: str, use_env: str | None) -> dict[str, Any]:
    """Full catalog row for one run id (MinIO + flags)."""
    env = (use_env or os.getenv("MODEL_ENV", "prod")).strip()
    by_id: dict[str, dict[str, Any]] = {}
    disk_row = _read_one_experiment_directory(run_id, env)
    if disk_row:
        by_id[run_id] = disk_row
    if run_id not in by_id:
        exp_model_key = f"{env}/valuation/experiments/{run_id.strip().strip('/')}/model.pkl"
        try:
            if model_store.object_exists(exp_model_key):
                row = model_store.catalog_row_from_minio_experiment_model_key(exp_model_key)
                if row:
                    by_id[run_id] = row
        except Exception:
            pass
    row = by_id.get(run_id)
    if row is None:
        raise ValueError(f"Unknown experiment run: {run_id}")
    folders: set[str] = set()
    try:
        folders = model_store.valuation_artifact_folder_names(env)
    except Exception:
        folders = set()
    experiment_folders: set[str] = set()
    try:
        for mk in model_store.list_valuation_experiment_model_keys(env):
            fn = model_store.experiment_folder_from_model_object_key(mk)
            if fn:
                experiment_folders.add(fn)
    except Exception:
        pass
    in_minio_exp = run_id in experiment_folders
    published = in_minio_exp or model_store.local_run_has_minio_counterpart(run_id, folders)
    publish_key = f"{env}/valuation/experiments/{run_id}/model.pkl" if in_minio_exp else None
    return {
        "env": env,
        "run": {
            "id": run_id,
            "published": published,
            "has_minio_experiment": in_minio_exp,
            "publish_object_key": publish_key,
            "has_minio_artifact": published,
            "has_metrics": bool(row.get("has_metrics")),
            "config": row.get("config"),
            "metrics": row.get("metrics"),
            "best_params": row.get("best_params"),
        },
    }


def _ensure_repo_root_for_modelling_import() -> None:
    """Repo root must be on ``sys.path`` for ``from modelling...`` imports."""
    root = Path(__file__).resolve().parent.parent
    rs = str(root)
    if rs not in sys.path:
        sys.path.insert(0, rs)


def _run_valuation_request_sync(
    data: ValuationInput,
    db: Session,
    *,
    valuation_month: str,
    include_premium_extras: bool,
    debug_timings: bool,
) -> Dict[str, Any]:
    """Synchronous valuation body — run via ``run_in_threadpool`` from async handler."""
    from modelling.inference.serving import valuation_extra_raw_columns
    from modelling.inference.valuation_raw_row import ValuationInferenceInput, build_valuation_raw_dataframe

    timings_ms: dict[str, Any] = {}
    t_wall = time.perf_counter()

    t0 = time.perf_counter()
    post_digits = "".join(c for c in data.postal_code if c.isdigit())
    pc_for_resolve = post_digits if len(post_digits) == 6 else (data.postal_code or "").strip()
    addr = _resolve_enrichment_for_amenity(db, pc_for_resolve or None, None)
    timings_ms["resolve_addr_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    fs = ml_service.feature_set_id()
    timings_ms["feature_set_id"] = fs or ""

    lat_model: Optional[float] = None
    lng_model: Optional[float] = None
    if data.latitude is not None and data.longitude is not None:
        lat_model, lng_model = float(data.latitude), float(data.longitude)
    elif addr is not None and addr.latitude is not None and addr.longitude is not None:
        lat_model, lng_model = float(addr.latitude), float(addr.longitude)

    if ml_service.requires_coordinates_for_inference():
        if lat_model is None or lng_model is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Valuation requires latitude and longitude (WGS84) for this model — "
                    "provide them on the request or use a postcode with OneMap enrichment."
                ),
            )

    mrt_overrides: Optional[dict] = None
    mrt_src: str | None = None
    t_mrt = time.perf_counter()
    if fs and "mrt_pit" in fs:
        from services.mrt_inference_features import fetch_mrt_features_row_with_meta

        if addr is None or addr.id is None:
            raise HTTPException(
                status_code=503,
                detail="Address enrichment not found — cannot compute MRT features for this postal code.",
            )
        mrt_overrides, mrt_src = fetch_mrt_features_row_with_meta(db, int(addr.id), valuation_month)
        if not mrt_overrides:
            raise HTTPException(
                status_code=503,
                detail="MRT features unavailable for this address and valuation month.",
            )
    timings_ms["mrt_features_ms"] = round((time.perf_counter() - t_mrt) * 1000, 2)
    timings_ms["mrt_features_source"] = mrt_src

    _ensure_repo_root_for_modelling_import()

    t_ex = time.perf_counter()
    feature_extras = valuation_extra_raw_columns(
        fs,
        valuation_month=valuation_month,
        latitude=lat_model,
        longitude=lng_model,
        town=data.town,
        project_root=Path(__file__).resolve().parent.parent,
    )
    timings_ms["feature_extras_ms"] = round((time.perf_counter() - t_ex) * 1000, 2)

    v_in = ValuationInferenceInput(
        postal_code=data.postal_code,
        town=data.town,
        flat_type=data.flat_type,
        flat_model_grouped=data.flat_model_grouped,
        region=data.region,
        storey_midpoint=int(data.storey_midpoint),
        floor_area_sqm=float(data.floor_area_sqm),
        remaining_lease_years=float(data.remaining_lease_years),
        latitude=lat_model,
        longitude=lng_model,
        lease_commence_year=data.lease_commence_year,
    )
    raw_df = build_valuation_raw_dataframe(
        v_in,
        valuation_month=valuation_month,
        mrt_feature_overrides=mrt_overrides,
        feature_overrides=feature_extras if feature_extras else None,
    )

    t_pred = time.perf_counter()
    try:
        predicted_price = ml_service.predict_raw(raw_df, valuation_month=valuation_month)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Model prediction failed: {exc}",
        ) from exc
    timings_ms["predict_ms"] = round((time.perf_counter() - t_pred) * 1000, 2)

    lat_f: Optional[float] = lat_model
    lng_f: Optional[float] = lng_model
    nearby_mrt_distance: float | None = None
    nearby_mrts: list = []

    t_am = time.perf_counter()
    if lat_f is not None and lng_f is not None:
        nearby_mrts = geospatial_service.get_nearby_mrts(lat_f, lng_f, radius_km=2.0, db=db)
        nearest_mrt = nearby_mrts[0] if nearby_mrts else {"name": "Unknown", "distance": 0.0}
        if nearby_mrts:
            mrt_label = f"{nearest_mrt['name']} MRT ({nearest_mrt['distance']}km)"
            nearby_mrt_distance = float(nearest_mrt["distance"])
        else:
            mrt_label = "Data not available"
        cbd_km = _haversine_km(lat_f, lng_f, _CBD_REFERENCE_LAT, _CBD_REFERENCE_LNG)
        cbd_str = f"{cbd_km:.1f} km"

        school_row = geospatial_service.nearest_school_amenity_within_radius(
            db,
            lat_f,
            lng_f,
            radius_m=5000.0,
        )
        if school_row:
            dm = float(school_row["distance_m"])
            school_str = f"{school_row['name']} ({dm / 1000.0:.1f} km)"
        else:
            school_str = "Data not available"
    else:
        mrt_label = "Data not available"
        school_str = "Data not available"
        cbd_str = "Data not available"
        nearest_mrt = {"name": "Unknown", "distance": 0.0}
    timings_ms["amenities_ms"] = round((time.perf_counter() - t_am) * 1000, 2)

    result = {
        "predicted_price": round(predicted_price, 2),
        **ml_service.prediction_interval_payload(predicted_price),
        "amenities": {
            "mrt": mrt_label,
            "school": school_str,
            "cbd_distance": cbd_str,
        },
        "nearby_mrt_distance": nearby_mrt_distance,
    }

    timings_ms["shap_ms"] = 0.0
    if include_premium_extras:
        t_shap = time.perf_counter()
        shap_vals = ml_service.compute_shap_top_features(
            raw_df, top_n=500, valuation_month=valuation_month
        )
        timings_ms["shap_ms"] = round((time.perf_counter() - t_shap) * 1000, 2)
        if shap_vals:
            result["shap_values"] = shap_vals

        result["driver_context"] = _build_driver_context(
            nearby_mrts=nearby_mrts,
            mrt_overrides=mrt_overrides,
            school_str=school_str,
            feature_extras=feature_extras,
            lat=lat_f,
            lng=lng_f,
        )

        from services.comparable_service import find_comparable_sales

        t_comparables = time.perf_counter()
        result["neighbor_comparison"] = find_comparable_sales(
            db,
            predicted_price=predicted_price,
            floor_area_sqm=data.floor_area_sqm,
            flat_type=data.flat_type,
            flat_model=data.flat_model_grouped,
            storey_midpoint=data.storey_midpoint,
            remaining_lease_years=data.remaining_lease_years,
            latitude=lat_f,
            longitude=lng_f,
            valuation_month=valuation_month,
            subject_postal_code=pc_for_resolve,
        )
        timings_ms["comparables_ms"] = round((time.perf_counter() - t_comparables) * 1000, 2)

    timings_ms["wall_ms"] = round((time.perf_counter() - t_wall) * 1000, 2)
    if debug_timings:
        result["_timings"] = timings_ms
        logger.info("valuation timings ms=%s", timings_ms)
    else:
        logger.debug("valuation timings ms=%s", timings_ms)

    return result


@app.post("/api/valuation")
async def get_valuation(
    data: ValuationInput,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
    debug_timings: bool = Query(False, description="Include _timings object and log segment timings."),
):
    if not ml_service.is_ready():
        raise HTTPException(
            status_code=503,
            detail=ml_service.load_error_message() or "Valuation model unavailable.",
        )

    valuation_month = datetime.now(timezone.utc).strftime("%Y-%m")
    include_premium = bool(current_user and has_premium_entitlements(current_user, request))

    return await run_in_threadpool(
        _run_valuation_request_sync,
        data,
        db,
        valuation_month=valuation_month,
        include_premium_extras=include_premium,
        debug_timings=debug_timings,
    )


def _resolve_enrichment_for_amenity(
    db: Session,
    postal_code: Optional[str],
    property_name: Optional[str],
):
    """Resolve one ``hdb_address_enrichment_onemap`` row for amenity / POI APIs.

    **Property path:** ``query_sent`` is treated as unique per normalized string (case-insensitive
    match to ``property_name``). Postal is not used to disambiguate when ``property_name`` is set.

    **Postal-only path:** match on ``postal_code`` (6-digit exact, else digit prefix, else ilike);
    ``order_by(id).first()`` makes ties deterministic if multiple rows share a prefix.
    """
    from models import HdbAddressEnrichmentOnemap

    pc = (postal_code or "").strip()
    pn = (property_name or "").strip()
    base = db.query(HdbAddressEnrichmentOnemap)
    digits_all = "".join(c for c in pc if c.isdigit()) if len(pc) >= 3 else ""

    if len(pn) >= 2:
        return (
            base.filter(func.lower(HdbAddressEnrichmentOnemap.query_sent) == pn.lower())
            .order_by(HdbAddressEnrichmentOnemap.id)
            .first()
        )

    if len(pc) >= 3:
        q = base.order_by(HdbAddressEnrichmentOnemap.id)
        if len(digits_all) == 6:
            return q.filter(HdbAddressEnrichmentOnemap.postal_code == digits_all).first()
        if len(digits_all) >= 3:
            return q.filter(HdbAddressEnrichmentOnemap.postal_code.like(f"{digits_all}%")).first()
        return q.filter(HdbAddressEnrichmentOnemap.postal_code.ilike(f"{pc}%")).first()

    return None


def _build_amenity_score_response(
    db: Session,
    postal_code: Optional[str],
    property_name: Optional[str],
    *,
    radius_km: float = 1.0,
):
    """Nearby MRT stations and illustrative school/park/mosque rows for a resolved address (no composite scores)."""
    from datetime import date

    from models import HdbResaleTransaction
    from sqlalchemy import text

    pc_in = (postal_code or "").strip()
    pn_in = (property_name or "").strip()
    post_digits = "".join(c for c in pc_in if c.isdigit())
    has_det_postal = len(post_digits) == 6
    if not has_det_postal and len(pn_in) < 2:
        raise HTTPException(
            status_code=400,
            detail="Provide a 6-digit postal_code and/or property_name (at least 2 characters).",
        )

    # Prefer exact 6-digit postal when property is absent; otherwise let resolver use property or prefix rules.
    pc_for_resolve = post_digits if (has_det_postal and len(pn_in) < 2) else (pc_in if len(pc_in) >= 3 else None)
    address = _resolve_enrichment_for_amenity(db, pc_for_resolve, pn_in or None)
    if not address:
        raise HTTPException(status_code=404, detail="Address not found in enrichment records")
    if address.latitude is None or address.longitude is None:
        return {
            "no_coordinates": True,
            "message": "Geographical Analysis Unavailable: No Lat-long",
        }

    postal_for_score = (address.postal_code or "").strip() or pc_in or pn_in

    lat, lng = float(address.latitude), float(address.longitude)
    as_of = date.today()
    pit_fragment = geospatial_service._pit_state_case_sql("m")
    radius_m = max(250.0, min(float(radius_km) * 1000.0, 20_000.0))

    sample_tx = (
        db.query(HdbResaleTransaction)
        .filter(HdbResaleTransaction.enriched_addr_id == address.id)
        .first()
    )
    if sample_tx and sample_tx.block_street:
        address_label = sample_tx.block_street
    elif sample_tx and (sample_tx.block or sample_tx.street_name):
        address_label = f"Blk {sample_tx.block} {sample_tx.street_name}".strip()
    else:
        address_label = f"Postal {address.postal_code or postal_for_score}"

    # Pass 1: physical stations within radius. Pass 2: LEFT JOIN hdb_mrt_routes for pre-computed legs.
    sql = text(
        f"""
        SELECT m.id AS mrt_id,
               m.physical_station_id AS physical_station_id,
               ps.canonical_name AS physical_canonical_name,
               ps.lat AS station_lat,
               ps.long AS station_long,
               m.station_name,
               m.network_line,
               m.station_code,
               m.opening_date,
               m.expected_completion,
               m.announcement_date,
               m.announcement_date_raw,
               m.opening_date_raw,
               m.expected_completion_raw,
               m.source_url,
               m.subproject_or_stage,
               ROUND(
                   ST_Distance(
                       ps.geom::geography,
                       ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                   )::numeric
               ) AS geom_distance_m,
               r.haversine_distance_m,
               r.walk_distance_m,
               r.walk_time_mins,
               r.drive_distance_m,
               r.drive_time_mins,
               r.pt_distance_m,
               r.pt_time_mins,
               ({pit_fragment.strip()}) AS pit_state
        FROM mrt_station_lines m
        INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
        LEFT JOIN hdb_mrt_routes r ON r.physical_station_id = ps.id AND r.hdb_addr_id = :addr_id
        WHERE ps.geom IS NOT NULL
          AND ST_DWithin(
              ps.geom::geography,
              ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
              :radius_m
          )
        ORDER BY geom_distance_m ASC NULLS LAST, m.id ASC
        """
    )
    rows = db.execute(
        sql,
        {"addr_id": address.id, "lat": lat, "lng": lng, "as_of": as_of, "radius_m": radius_m},
    ).fetchall()

    PLANNED_PIT_STATES = frozenset({"COMMITTED_DATED", "COMMITTED_ESTIMATED", "ANNOUNCED_UNDATED"})
    PIT_SORT = {
        "OPERATIONAL": 0,
        "UNKNOWN": 1,
        "COMMITTED_DATED": 2,
        "COMMITTED_ESTIMATED": 3,
        "ANNOUNCED_UNDATED": 4,
    }

    def _merge_travel_times_into_station(st: dict, tt: Optional[Dict]) -> None:
        """Attach routing legs to the *physical* station payload.

        ``hdb_mrt_routes`` rows are keyed by ``(hdb_addr_id, physical_station_id)`` where
        ``physical_station_id`` references ``mrt_physical_stations.id``. Multiple
        ``mrt_station_lines`` rows at the same interchange share one route row; for the
        amenity API we merge walk/drive/pt across lines and expose a single ``travel_times``
        object on each physical station for UI consistency.
        """
        if not tt or not isinstance(tt, dict):
            return
        modes = ("walk", "drive", "pt")
        cur = st.get("travel_times")
        if not isinstance(cur, dict) or not cur:
            st["travel_times"] = {k: dict(v) for k, v in tt.items() if isinstance(v, dict)}
            return
        for mode in modes:
            new_leg = tt.get(mode)
            if not isinstance(new_leg, dict):
                continue
            new_t = new_leg.get("time_mins")
            old_leg = cur.get(mode)
            old_t = old_leg.get("time_mins") if isinstance(old_leg, dict) else None
            if new_t is None:
                continue
            try:
                new_num = float(new_t)
                old_num = float(old_t) if old_t is not None else None
            except (TypeError, ValueError):
                if old_t is None:
                    cur[mode] = dict(new_leg)
                continue
            if old_num is None or new_num < old_num:
                cur[mode] = dict(new_leg)

    def _iso(d) -> Optional[str]:
        if d is None:
            return None
        return d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]

    def _line_payload_from_row(row) -> dict:
        geom_d = int(float(row.geom_distance_m or 0))
        w = row.walk_distance_m
        h = row.haversine_distance_m
        if w is not None:
            route_dist_m = int(w)
        elif h is not None:
            route_dist_m = int(h)
        else:
            route_dist_m = geom_d
        ps_norm = (str(row.pit_state or "")).strip().upper() or "UNKNOWN"
        tt: Dict[str, Dict] = {}
        if row.walk_time_mins is not None or row.walk_distance_m is not None:
            tt["walk"] = {"time_mins": row.walk_time_mins, "distance_m": row.walk_distance_m}
        if row.drive_time_mins is not None or row.drive_distance_m is not None:
            tt["drive"] = {"time_mins": row.drive_time_mins, "distance_m": row.drive_distance_m}
        if row.pt_time_mins is not None or row.pt_distance_m is not None:
            tt["pt"] = {"time_mins": row.pt_time_mins, "distance_m": row.pt_distance_m}
        line: Dict = {
            "line_id": int(row.mrt_id),
            "station_name": row.station_name,
            "network_line": row.network_line,
            "station_code": row.station_code,
            "pit_state": ps_norm,
            "distance_m": route_dist_m,
            "straight_line_distance_m": geom_d,
            "opening_date": _iso(row.opening_date),
            "expected_completion": _iso(row.expected_completion),
            "announcement_date": _iso(row.announcement_date),
            "announcement_date_raw": row.announcement_date_raw,
            "opening_date_raw": row.opening_date_raw,
            "expected_completion_raw": row.expected_completion_raw,
            "source_url": row.source_url,
            "subproject_or_stage": row.subproject_or_stage,
            "type": "MRT",
            "icon": "Train",
        }
        if tt:
            line["travel_times"] = tt
        return line

    def _line_payload_from_planned_item(item: dict) -> dict:
        """Normalize planned-station dict to the same line shape as `_line_payload_from_row`."""
        ps_norm = (str(item.get("pit_state") or "")).strip().upper() or "UNKNOWN"
        line: Dict = {
            "line_id": int(item["id"]),
            "station_name": item.get("station_name"),
            "network_line": item.get("network_line"),
            "station_code": item.get("station_code"),
            "pit_state": ps_norm,
            "distance_m": int(item.get("distance_m") or 0),
            "straight_line_distance_m": int(item.get("distance_m") or 0),
            "opening_date": item.get("opening_date"),
            "expected_completion": item.get("expected_completion"),
            "announcement_date": item.get("announcement_date"),
            "announcement_date_raw": item.get("announcement_date_raw"),
            "opening_date_raw": item.get("opening_date_raw"),
            "expected_completion_raw": item.get("expected_completion_raw"),
            "source_url": item.get("source_url"),
            "subproject_or_stage": item.get("subproject_or_stage"),
            "type": "MRT",
            "icon": "Train",
        }
        if item.get("travel_times"):
            line["travel_times"] = item["travel_times"]
        return line

    stations_by_phys: Dict[int, dict] = {}
    seen_line_ids: set = set()

    def _merge_line_into_station(row_or_line: Any, *, from_row: bool) -> None:
        if from_row:
            row = row_or_line
            mid = int(row.mrt_id)
            if mid in seen_line_ids:
                return
            seen_line_ids.add(mid)
            pid = int(row.physical_station_id)
            canon = (row.physical_canonical_name or row.station_name or "").strip()
            sla = float(row.station_lat) if row.station_lat is not None else None
            slo = float(row.station_long) if row.station_long is not None else None
            geom_d = int(float(row.geom_distance_m or 0))
            line_payload = _line_payload_from_row(row)
        else:
            item = row_or_line
            mid = int(item["id"])
            if mid in seen_line_ids:
                return
            seen_line_ids.add(mid)
            pid = int(item["physical_station_id"])
            canon = (item.get("physical_canonical_name") or item.get("station_name") or "").strip()
            sla = item.get("station_lat")
            slo = item.get("station_long")
            if sla is not None:
                sla = float(sla)
            if slo is not None:
                slo = float(slo)
            geom_d = int(item.get("distance_m") or 0)
            line_payload = _line_payload_from_planned_item(item)

        display_name = canon.upper() if canon else "MRT"
        if not display_name.endswith("MRT"):
            display_name = f"{display_name} MRT"

        if pid not in stations_by_phys:
            stations_by_phys[pid] = {
                "physical_station_id": pid,
                "canonical_name": canon or display_name.replace(" MRT", ""),
                "name": display_name,
                "lat": sla,
                "lng": slo,
                "distance_m": geom_d,
                "lines": [],
            }
        st = stations_by_phys[pid]
        st["distance_m"] = min(int(st["distance_m"]), int(geom_d))
        if sla is not None:
            st["lat"] = sla
        if slo is not None:
            st["lng"] = slo
        if not any(int(ln["line_id"]) == int(line_payload["line_id"]) for ln in st["lines"]):
            tt_merge = line_payload.pop("travel_times", None)
            st["lines"].append(line_payload)
            _merge_travel_times_into_station(st, tt_merge)

    for row in rows:
        _merge_line_into_station(row, from_row=True)

    planned_extra = geospatial_service.get_nearby_planned_mrts_detail(
        lat,
        lng,
        db=db,
        radius_km=float(radius_km),
        exclude_line_ids=seen_line_ids,
        limit=12,
        as_of=as_of,
    )
    for item in planned_extra:
        if item.get("physical_station_id") is None:
            continue
        _merge_line_into_station(item, from_row=False)

    for st in stations_by_phys.values():
        st["lines"].sort(
            key=lambda ln: (PIT_SORT.get(str(ln.get("pit_state") or "").upper(), 99), ln.get("network_line") or "")
        )

    def _station_buckets(st: dict) -> str:
        pits = [str(ln.get("pit_state") or "").upper() for ln in st["lines"]]
        if any(p == "OPERATIONAL" for p in pits):
            return "operational"
        if pits and all(p in PLANNED_PIT_STATES for p in pits):
            return "upcoming"
        return "unknown"

    mrt_operational: List[dict] = []
    mrt_upcoming: List[dict] = []
    mrt_unknown: List[dict] = []
    for st in sorted(stations_by_phys.values(), key=lambda x: int(x.get("distance_m") or 0)):
        bucket = _station_buckets(st)
        if bucket == "upcoming":
            mrt_upcoming.append(st)
        elif bucket == "operational":
            mrt_operational.append(st)
        else:
            mrt_unknown.append(st)

    nearby_pois = geospatial_service.query_pois_within_radius(
        db, lat, lng, float(radius_m), limit=8000
    )

    def _looks_like_mosque(p: dict) -> bool:
        n = str(p.get("name") or "").lower()
        return any(
            kw in n
            for kw in ("mosque", "masjid", "musollah", "musolla", "surau", "kampung mosque")
        )

    schools = sorted(
        [p for p in nearby_pois if str(p.get("poi_type") or "") in ("school_top20", "school_any")],
        key=lambda x: float(x.get("distance_m") or 0),
    )
    parks = sorted(
        [p for p in nearby_pois if str(p.get("poi_type") or "") == "park"],
        key=lambda x: float(x.get("distance_m") or 0),
    )
    mosques = sorted(
        [p for p in nearby_pois if _looks_like_mosque(p)],
        key=lambda x: float(x.get("distance_m") or 0),
    )

    def _amenity_payload_row(p: dict, *, display_type: str, icon: str) -> dict:
        nm = str(p.get("name") or "").strip()
        return {
            "name": nm or None,
            "type": display_type,
            "distance_m": int(round(float(p.get("distance_m") or 0))),
            "icon": icon,
        }

    def _norm_amenity_school_name(p: dict) -> str:
        n = str(p.get("name") or "").strip().lower()
        return " ".join(n.split())

    schools_top20_ordered = sorted(
        [p for p in schools if str(p.get("poi_type") or "") == "school_top20"],
        key=lambda x: float(x.get("distance_m") or 0),
    )
    schools_any_ordered = sorted(
        [p for p in schools if str(p.get("poi_type") or "") == "school_any"],
        key=lambda x: float(x.get("distance_m") or 0),
    )
    seen_school_norm: Set[str] = set()
    school_list = []
    for p in schools_top20_ordered + schools_any_ordered:
        if len(school_list) >= 15:
            break
        key_nm = _norm_amenity_school_name(p)
        if key_nm and key_nm in seen_school_norm:
            continue
        if key_nm:
            seen_school_norm.add(key_nm)
        school_list.append(_amenity_payload_row(p, display_type="School", icon="GraduationCap"))
    park_list = [_amenity_payload_row(p, display_type="Park", icon="TreePine") for p in parks[:15]]
    mosque_list = [_amenity_payload_row(p, display_type="Mosque", icon="Library") for p in mosques[:10]]

    other_amenities = school_list + park_list + mosque_list
    other_amenities.sort(key=lambda x: x["distance_m"])

    mrt_operational.sort(key=lambda x: x.get("distance_m") or 0)
    mrt_upcoming.sort(key=lambda x: x.get("distance_m") or 0)

    return {
        "postal_code": postal_for_score,
        "address": address_label,
        "mrt_search_radius_m": int(radius_m),
        "mrt": {"operational": mrt_operational, "upcoming": mrt_upcoming, "unknown": mrt_unknown},
        "amenities": other_amenities[:20],
    }


@app.get("/api/geospatial/amenity_score")
async def get_amenity_score_query(
    postal_code: Optional[str] = Query(None),
    property_name: Optional[str] = Query(None),
    radius_km: float = Query(1.0, ge=0.25, le=15.0, description="Radius (km) for physical MRT pass-1"),
    db: Session = Depends(get_db),
):
    return _build_amenity_score_response(db, postal_code, property_name, radius_km=radius_km)


@app.get("/api/geospatial/amenity_score/{postal_code}")
async def get_amenity_score_path(
    postal_code: str,
    property_name: Optional[str] = Query(None),
    radius_km: float = Query(1.0, ge=0.25, le=15.0, description="Radius (km) for physical MRT pass-1"),
    db: Session = Depends(get_db),
):
    return _build_amenity_score_response(db, postal_code, property_name, radius_km=radius_km)


@app.post("/api/geospatial/pois_nearby")
async def pois_nearby(body: PoiNearbyRequest, db: Session = Depends(get_db)):
    """On-demand POI list and counts within ``radius_m`` of resolved address."""
    pc_in = (body.postal_code or "").strip()
    pn_in = (body.property_name or "").strip()
    post_digits = "".join(c for c in pc_in if c.isdigit())
    has_det_postal = len(post_digits) == 6
    if not has_det_postal and len(pn_in) < 2:
        raise HTTPException(
            status_code=400,
            detail="Provide a 6-digit postal_code and/or property_name (at least 2 characters).",
        )
    pc_for_resolve = post_digits if (has_det_postal and len(pn_in) < 2) else (pc_in if len(pc_in) >= 3 else None)
    address = _resolve_enrichment_for_amenity(db, pc_for_resolve, pn_in or None)
    if not address:
        raise HTTPException(status_code=404, detail="Address not found in enrichment records")
    if not address.latitude or not address.longitude:
        return {
            "no_coordinates": True,
            "message": "Geographical Analysis Unavailable: No Lat-long",
        }

    postal_for_display = (address.postal_code or "").strip() or pc_in or None

    from models import HdbResaleTransaction

    sample_tx = (
        db.query(HdbResaleTransaction)
        .filter(HdbResaleTransaction.enriched_addr_id == address.id)
        .first()
    )
    if sample_tx and sample_tx.block_street:
        address_label = sample_tx.block_street
    elif sample_tx and (sample_tx.block or sample_tx.street_name):
        address_label = f"Blk {sample_tx.block} {sample_tx.street_name}".strip()
    else:
        address_label = f"Postal {postal_for_display or pc_in}"

    return geospatial_service.build_poi_nearby_payload(
        db,
        float(address.latitude),
        float(address.longitude),
        float(body.radius_m),
        address_label=address_label,
        postal_for_display=postal_for_display,
    )


@app.get("/api/geospatial/nearest_poi_per_type")
async def nearest_poi_per_type(
    postal_code: Optional[str] = Query(None),
    property_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Nearest *named* POI per type from the address; no search-radius cap (global nearest per type)."""
    pc_in = (postal_code or "").strip()
    pn_in = (property_name or "").strip()
    post_digits = "".join(c for c in pc_in if c.isdigit())
    has_det_postal = len(post_digits) == 6
    if not has_det_postal and len(pn_in) < 2:
        raise HTTPException(
            status_code=400,
            detail="Provide a 6-digit postal_code and/or property_name (at least 2 characters).",
        )
    pc_for_resolve = post_digits if (has_det_postal and len(pn_in) < 2) else (pc_in if len(pc_in) >= 3 else None)
    address = _resolve_enrichment_for_amenity(db, pc_for_resolve, pn_in or None)
    if not address:
        raise HTTPException(status_code=404, detail="Address not found in enrichment records")
    if not address.latitude or not address.longitude:
        return {
            "no_coordinates": True,
            "message": "Geographical Analysis Unavailable: No Lat-long",
        }

    postal_for_display = (address.postal_code or "").strip() or pc_in or None

    from models import HdbResaleTransaction

    sample_tx = (
        db.query(HdbResaleTransaction)
        .filter(HdbResaleTransaction.enriched_addr_id == address.id)
        .first()
    )
    if sample_tx and sample_tx.block_street:
        address_label = sample_tx.block_street
    elif sample_tx and (sample_tx.block or sample_tx.street_name):
        address_label = f"Blk {sample_tx.block} {sample_tx.street_name}".strip()
    else:
        address_label = f"Postal {postal_for_display or pc_in}"

    return geospatial_service.build_nearest_named_poi_by_type_payload(
        db,
        float(address.latitude),
        float(address.longitude),
        address_label=address_label,
        postal_for_display=postal_for_display,
    )


@app.get("/api/geospatial/mrt_in_planning_areas")
async def mrt_in_planning_areas(
    region_c: Optional[str] = Query(None, description="URA region code, e.g. CR, ER"),
    towns: Optional[str] = Query(None, description="Comma-separated planning area names (pln_area_n)"),
    db: Session = Depends(get_db),
):
    rc = region_c.strip().upper() if region_c and region_c.strip() else None
    town_list = [t.strip() for t in (towns or "").split(",") if t.strip()]
    if rc is None and not town_list:
        raise HTTPException(
            status_code=400,
            detail="Provide region_c and/or towns (comma-separated planning area names).",
        )
    try:
        stations = geospatial_service.list_mrts_in_planning_union(
            db, region_c=rc, town_names=town_list if town_list else None
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"stations": stations, "count": len(stations)}


@app.get("/api/geospatial/area_amenity_breakdown")
async def area_amenity_breakdown(
    region_c: Optional[str] = Query(None, description="URA region code, e.g. CR, ER"),
    towns: Optional[str] = Query(None, description="Comma-separated planning area names (pln_area_n)"),
    db: Session = Depends(get_db),
):
    rc = region_c.strip().upper() if region_c and region_c.strip() else None
    town_list = [t.strip() for t in (towns or "").split(",") if t.strip()]
    if rc is None and not town_list:
        raise HTTPException(
            status_code=400,
            detail="Provide region_c and/or towns (comma-separated planning area names).",
        )
    try:
        return geospatial_service.build_area_amenity_breakdown(
            db, region_c=rc, town_names=town_list if town_list else None
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/geospatial/nearby_mrts")
async def nearby_mrts(data: LocationInput, db: Session = Depends(get_db)):
    results = geospatial_service.get_nearby_mrts(data.lat, data.lng, data.radius, db=db)
    return {"mrts": results}

@app.post("/api/geospatial/area_insights")
async def area_insights(data: AreaInsightInput, db: Session = Depends(get_db)):
    """Deprecated: synthetic POC. Use ``GET /api/geospatial/area_amenity_breakdown``."""
    raise HTTPException(
        status_code=410,
        detail="area_insights is deprecated. Use GET /api/geospatial/area_amenity_breakdown with region_c and/or towns query parameters.",
    )

@app.get("/api/geospatial/mrt_stations")
async def get_mrt_stations(db: Session = Depends(get_db)):
    try:
        return geospatial_service.get_mrt_stations_geojson(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MRT exits query failed: {str(e)}")

@app.get("/api/geospatial/regions")
async def get_ura_regions(db: Session = Depends(get_db)):
    from sqlalchemy import text
    sql = text("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'region_n', region_n,
                        'region_c', region_c
                    )
                )
            ), '[]'::json)
        )
        FROM ura_mp19_regions_no_sea
    """)
    result = db.execute(sql).scalar()
    return result if result else {"type": "FeatureCollection", "features": []}

@app.get("/api/geospatial/planning_areas")
async def get_ura_planning_areas(region: Optional[str] = None, db: Session = Depends(get_db)):
    from sqlalchemy import text
    filter_sql = "WHERE region_c = :region" if region else ""
    sql = text(f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'pln_area_n', pln_area_n,
                        'pln_area_c', pln_area_c,
                        'region_c', region_c
                    )
                )
            ), '[]'::json)
        )
        FROM ura_mp19_planning_areas_no_sea
        {filter_sql}
    """)
    result = db.execute(sql, {"region": region} if region else {}).scalar()
    return result if result else {"type": "FeatureCollection", "features": []}

@app.get("/api/geospatial/hdb_buildings")
async def get_hdb_buildings(
    min_area: float = 0,
    max_area: float = 999999,
    postal_prefix: str = None,
    region_c: Optional[str] = Query(None, description="URA region code, e.g. CR, ER"),
    towns: Optional[str] = Query(None, description="Comma-separated resale town or planning area names"),
    limit: int = Query(default=2000, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    from sqlalchemy import text

    rc = region_c.strip().upper() if region_c and region_c.strip() else None
    town_list = [t.strip() for t in (towns or "").split(",") if t.strip()]

    has_area_filter = rc is not None or bool(town_list)
    has_filter = (
        has_area_filter
        or (postal_prefix is not None)
        or (min_area > 0)
        or (max_area < 999999)
    )
    # Cap: filtered queries allow up to 5 000; unfiltered browsing is capped at 2 000
    effective_limit = min(limit, 5000 if has_filter else 2000)

    if has_area_filter:
        try:
            return geospatial_service.list_hdb_buildings_in_planning_union(
                db,
                region_c=rc,
                town_names=town_list if town_list else None,
                min_area=min_area,
                max_area=max_area,
                postal_prefix=postal_prefix,
                limit=effective_limit,
                offset=offset,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Spatial query failed: {str(e)}") from e

    postal_filter = "AND postal_cod LIKE :postal_prefix" if postal_prefix else ""

    sql = text(f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(feat), '[]'::json),
            'totalCount', (
                SELECT COUNT(*) FROM hdb_buildings
                WHERE shape_area BETWEEN :min_area AND :max_area
                {postal_filter}
            )
        ) AS geojson
        FROM (
            SELECT json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(geom, 6)::json,
                'properties', json_build_object(
                    'blk_no', blk_no,
                    'st_cod', st_cod,
                    'entityid', entityid,
                    'postal_cod', postal_cod,
                    'inc_crc', inc_crc,
                    'fmel_upd_d', fmel_upd_d,
                    'shape_area', shape_area,
                    'shape_len', shape_len,
                    'objectid', objectid
                )
            ) AS feat
            FROM hdb_buildings
            WHERE shape_area BETWEEN :min_area AND :max_area
            {postal_filter}
            ORDER BY id
            LIMIT :lim OFFSET :off
        ) sub
    """)

    params: dict = {
        "min_area": min_area,
        "max_area": max_area,
        "lim": effective_limit,
        "off": offset,
    }
    if postal_prefix:
        params["postal_prefix"] = postal_prefix + "%"

    try:
        result = db.execute(sql, params)
        row = result.fetchone()
        if row is None or row[0] is None:
            return {"type": "FeatureCollection", "features": [], "totalCount": 0}
        return row[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Spatial query failed: {str(e)}")

@app.get("/api/analytics/summary")
async def get_analytics_summary():
    return analytics_service.get_singapore_summary()

@app.get("/api/analytics/district/{district_name}")
async def get_district_data(district_name: str):
    return analytics_service.get_district_analytics(district_name)

@app.get("/api/analytics/filters")
async def get_analytics_filters():
    return analytics_service.get_filter_options()

class AnalyticsQueryRequest(BaseModel):
    towns: Optional[List[str]] = None
    flat_types: Optional[List[str]] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    floor_levels: Optional[List[str]] = None
    floor_area_min: Optional[float] = None
    floor_area_max: Optional[float] = None
    lease_remaining_min: Optional[int] = None
    lease_remaining_max: Optional[int] = None
    group_by: Optional[str] = "month"
    ura_region: Optional[str] = None
    postal_code: Optional[str] = None
    property_name: Optional[str] = None

@app.post("/api/analytics/query")
async def analytics_query(req: AnalyticsQueryRequest):
    towns_to_query = req.towns
    if req.ura_region and req.ura_region != "All Regions (Experimental)":
        from models import UraPlanningArea
        db = SessionLocal()
        REGION_MAP = {
            "Central Region": "CR",
            "East Region": "ER",
            "North Region": "NR",
            "North-East Region": "NER",
            "West Region": "WR",
        }
        region_code = REGION_MAP.get(req.ura_region, req.ura_region)
        areas = db.query(UraPlanningArea.pln_area_n).filter(UraPlanningArea.region_c == region_code).all()
        pln_area_names = [a[0] for a in areas]

        valid_towns = [name for name in pln_area_names]
        if region_code == "CR":
            valid_towns.extend(["CENTRAL AREA", "KALLANG/WHAMPOA"])

        if towns_to_query:
            towns_to_query = list(set(towns_to_query) & set(valid_towns))
        else:
            towns_to_query = valid_towns
        db.close()

    return analytics_service.query_transactions(
        towns=towns_to_query,
        flat_types=req.flat_types,
        date_from=req.date_from,
        date_to=req.date_to,
        price_min=req.price_min,
        price_max=req.price_max,
        floor_levels=req.floor_levels,
        floor_area_min=req.floor_area_min,
        floor_area_max=req.floor_area_max,
        lease_remaining_min=req.lease_remaining_min,
        lease_remaining_max=req.lease_remaining_max,
        postal_code=req.postal_code,
        property_name=req.property_name,
        group_by=req.group_by or "month",
    )

@app.get("/api/analytics/properties/search")
async def search_properties(q: str, db: Session = Depends(get_db)):
    if not q or len(q) < 2:
        return {"results": []}
    
    from models import HdbAddressEnrichmentOnemap
    parts = q.strip().split()
    search_term = "%" + "%".join(parts) + "%"
    
    results = db.query(
        HdbAddressEnrichmentOnemap.query_sent, 
        HdbAddressEnrichmentOnemap.postal_code
    ).filter(
        HdbAddressEnrichmentOnemap.query_sent.ilike(search_term)
    ).distinct().limit(20).all()
    
    # Return a list of dicts with name and postal
    out = []
    for r in results:
        if r[0]:
            out.append({"name": r[0], "postal_code": r[1] or ""})
            
    return {"results": out}


@app.get("/api/analytics/properties/postal_search")
async def search_properties_by_postal(postal_q: str, db: Session = Depends(get_db)):
    """Autocomplete postal codes (digits only, prefix match)."""
    from models import HdbAddressEnrichmentOnemap

    q = (postal_q or "").strip()
    if len(q) < 2 or not q.isdigit():
        return {"results": []}
    term = q + "%"
    rows = (
        db.query(HdbAddressEnrichmentOnemap.query_sent, HdbAddressEnrichmentOnemap.postal_code)
        .filter(
            HdbAddressEnrichmentOnemap.postal_code.isnot(None),
            HdbAddressEnrichmentOnemap.postal_code != "",
            HdbAddressEnrichmentOnemap.postal_code.ilike(term),
        )
        .distinct()
        .limit(20)
        .all()
    )
    out: list[dict] = []
    for r in rows:
        pc = (r[1] or "").strip()
        if pc:
            out.append({"name": r[0] or "", "postal_code": pc})
    return {"results": out}


# HDB town (as in resale data) → region label for the valuation UI
_TOWN_TO_REGION: dict[str, str] = {
    "ANG MO KIO": "North East",
    "BEDOK": "East",
    "BISHAN": "Central",
    "BUKIT BATOK": "West",
    "BUKIT MERAH": "Central",
    "BUKIT PANJANG": "West",
    "BUKIT TIMAH": "Central",
    "CENTRAL AREA": "Central",
    "CHOA CHU KANG": "West",
    "CLEMENTI": "West",
    "GEYLANG": "Central",
    "HOUGANG": "North East",
    "JURONG EAST": "West",
    "JURONG WEST": "West",
    "KALLANG/WHAMPOA": "Central",
    "MARINE PARADE": "East",
    "PASIR RIS": "East",
    "PUNGGOL": "North East",
    "QUEENSTOWN": "Central",
    "SEMBAWANG": "North",
    "SENGKANG": "North East",
    "SERANGOON": "North East",
    "TAMPINES": "East",
    "TOA PAYOH": "Central",
    "WOODLANDS": "North",
    "YISHUN": "North",
}


class FlatOption(BaseModel):
    flat_type: str
    flat_model_grouped: str
    # Official dwelling count for this flat type from hdb_property_information *_sold.
    units_sold: int = 0
    avg_floor_area_sqm: Optional[float] = None
    min_floor_area_sqm: Optional[int] = None
    max_floor_area_sqm: Optional[int] = None
    latest_lease_commence_year: Optional[int] = None
    # Inclusive storey band from HDB resale ``storey_range`` (min lower / max upper).
    min_storey_midpoint: Optional[int] = None
    max_storey_midpoint: Optional[int] = None
    resale_transaction_count: int = 0
    median_resale_price_sgd: Optional[int] = None
    latest_resale_month: Optional[str] = None
    latest_resale_price_sgd: Optional[int] = None


class PropertyLookupResponse(BaseModel):
    address_label: str
    postal_code: str
    town: str
    region: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    resale_transaction_count: int = 0
    resale_month_range_start: Optional[str] = None
    resale_month_range_end: Optional[str] = None
    flat_options: List[FlatOption]
    # Block completion year from HDB Property Information catalogue.
    year_completed: Optional[int] = None
    # Building height from ``hdb_property_information.max_floor_lvl`` only (not inferred from resale).
    building_max_storey: Optional[int] = None


@app.get("/api/properties/lookup", response_model=PropertyLookupResponse)
async def lookup_property_by_postal(postal_code: str, db: Session = Depends(get_db)):
    """Resolve a 6-digit postal to HDB Property Information plus optional resale overlays."""
    from collections import Counter, defaultdict

    from hdb_property_flat_types import flat_types_from_property_row, resolve_property_for_address

    from models import HdbAddressEnrichmentOnemap, HdbResaleTransaction

    raw = (postal_code or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 6:
        raise HTTPException(
            status_code=400,
            detail="Postal code must be exactly 6 digits",
        )

    address = (
        db.query(HdbAddressEnrichmentOnemap)
        .filter(HdbAddressEnrichmentOnemap.postal_code == digits)
        .order_by(HdbAddressEnrichmentOnemap.id)
        .first()
    )
    if not address:
        raise HTTPException(status_code=404, detail="No records found")

    prop = resolve_property_for_address(db, address)
    if prop is None:
        raise HTTPException(status_code=404, detail="No records found")

    rows = (
        db.query(HdbResaleTransaction)
        .filter(HdbResaleTransaction.enriched_addr_id == address.id)
        .all()
    )

    by_ft: dict[str, dict] = defaultdict(
        lambda: {
            "models": [],
            "areas": [],
            "leases": [],
            "storey_lows": [],
            "storey_highs": [],
            "prices": [],
            "month_price": [],
            "count": 0,
        }
    )
    for r in rows:
        ft = (r.flat_type or "").strip()
        if not ft:
            continue
        by_ft[ft]["count"] += 1
        m = (r.flat_model or "").strip()
        if m:
            by_ft[ft]["models"].append(m)
        if r.floor_area_sqm is not None:
            by_ft[ft]["areas"].append(int(r.floor_area_sqm))
        if r.lease_commence_date is not None:
            by_ft[ft]["leases"].append(int(r.lease_commence_date))
        bounds = parse_storey_range_bounds(getattr(r, "storey_range", None))
        if bounds:
            lo, hi = bounds
            by_ft[ft]["storey_lows"].append(lo)
            by_ft[ft]["storey_highs"].append(hi)
        if r.resale_price is not None:
            by_ft[ft]["prices"].append(int(r.resale_price))
        mo = (r.month or "").strip()
        if mo and r.resale_price is not None:
            by_ft[ft]["month_price"].append((mo, int(r.resale_price)))

    catalogue_town = (getattr(prop, "hdb_town", None) or "").strip()
    if catalogue_town:
        town = catalogue_town.upper()
    else:
        town_counts = Counter(
            (r.town or "").strip() for r in rows if (r.town or "").strip()
        )
        if town_counts:
            town = town_counts.most_common(1)[0][0].upper()
        elif rows:
            town = (rows[0].town or "").strip().upper()
        else:
            town = ""

    region = _TOWN_TO_REGION.get(town, "Central") if town else "Central"

    all_months = [(r.month or "").strip() for r in rows if (r.month or "").strip()]
    resale_month_start = min(all_months) if all_months else None
    resale_month_end = max(all_months) if all_months else None

    flat_options: list[FlatOption] = []
    for ft, units_sold in flat_types_from_property_row(prop):
        data = by_ft.get(ft)
        if data:
            models = data["models"]
            model_mode = (
                Counter(models).most_common(1)[0][0] if models else "Model A"
            )
            areas = data["areas"]
            avg_f = sum(areas) / len(areas) if areas else None
            min_a = min(areas) if areas else None
            max_a = max(areas) if areas else None
            leases = data["leases"]
            latest_lease = max(leases) if leases else None
            lows = data["storey_lows"]
            highs = data["storey_highs"]
            min_st = min(lows) if lows else None
            max_st = max(highs) if highs else None
            prices: list[int] = data["prices"]
            med_price = int(round(median(prices))) if prices else None
            mp: list[tuple[str, int]] = data["month_price"]
            latest_rm: Optional[str] = None
            latest_rp: Optional[int] = None
            if mp:
                latest_rm = max(m[0] for m in mp)
                latest_rp = max(p for m, p in mp if m == latest_rm)
            flat_options.append(
                FlatOption(
                    flat_type=ft,
                    flat_model_grouped=model_mode,
                    units_sold=units_sold,
                    avg_floor_area_sqm=round(avg_f, 1) if avg_f is not None else None,
                    min_floor_area_sqm=min_a,
                    max_floor_area_sqm=max_a,
                    latest_lease_commence_year=latest_lease,
                    min_storey_midpoint=min_st,
                    max_storey_midpoint=max_st,
                    resale_transaction_count=data["count"],
                    median_resale_price_sgd=med_price,
                    latest_resale_month=latest_rm,
                    latest_resale_price_sgd=latest_rp,
                )
            )
        else:
            flat_options.append(
                FlatOption(
                    flat_type=ft,
                    flat_model_grouped="Model A",
                    units_sold=units_sold,
                )
            )

    label = (address.query_sent or "").strip() or f"Postal {digits}"
    mf = getattr(prop, "max_floor_lvl", None)
    building_max_storey = (
        int(mf) if mf is not None else None
    )
    yc = getattr(prop, "year_completed", None)
    year_completed = int(yc) if yc is not None else None

    return PropertyLookupResponse(
        address_label=label,
        postal_code=digits,
        town=town,
        region=region,
        latitude=address.latitude,
        longitude=address.longitude,
        resale_transaction_count=len(rows),
        resale_month_range_start=resale_month_start,
        resale_month_range_end=resale_month_end,
        flat_options=flat_options,
        year_completed=year_completed,
        building_max_storey=building_max_storey,
    )


class InsightRequest(BaseModel):
    filter_state: dict
    data_summary: dict


# ---------------------------------------------------------------------------
# AUTH DEPENDENCY (used by reports, chat, user endpoints)
# ---------------------------------------------------------------------------

def get_current_user(token: str = Depends(OAuth2PasswordBearer(tokenUrl="api/login")), db: Session = Depends(get_db)):
    from jwt import PyJWTError
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if getattr(user, "is_banned", False):
        raise HTTPException(status_code=403, detail="Account suspended")
    return user


@app.post("/api/analytics/insight")
async def analytics_insight(
    req: InsightRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not has_premium_entitlements(current_user, request):
        raise HTTPException(status_code=403, detail="Premium subscription required for AI market insights")
    return ai_service.generate_insight(req.filter_state, req.data_summary)


# ---------------------------------------------------------------------------
# REPORTS CRUD
# ---------------------------------------------------------------------------

class ReportCreate(BaseModel):
    title: str
    description: Optional[str] = None
    filter_state: dict
    ai_commentary: Optional[str] = None
    chart_config: Optional[dict] = None

@app.get("/api/reports")
async def list_reports(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reports = (
        db.query(AnalysisReport)
        .filter(AnalysisReport.user_id == current_user.id)
        .order_by(AnalysisReport.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "filter_state": json.loads(r.filter_state) if r.filter_state else {},
            "ai_commentary": r.ai_commentary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in reports
    ]

@app.post("/api/reports")
async def create_report(data: ReportCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = AnalysisReport(
        user_id=current_user.id,
        title=data.title,
        description=data.description,
        filter_state=json.dumps(data.filter_state),
        ai_commentary=data.ai_commentary,
        chart_config=json.dumps(data.chart_config) if data.chart_config else None,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"id": report.id, "title": report.title, "created_at": report.created_at.isoformat() if report.created_at else None}

@app.get("/api/reports/{report_id}")
async def get_report(report_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = db.query(AnalysisReport).filter(
        AnalysisReport.id == report_id,
        AnalysisReport.user_id == current_user.id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    filter_state = json.loads(report.filter_state) if report.filter_state else {}
    live_data = analytics_service.query_transactions(
        towns=filter_state.get("towns"),
        flat_types=filter_state.get("flat_types"),
        date_from=filter_state.get("date_from"),
        date_to=filter_state.get("date_to"),
        price_min=filter_state.get("price_min"),
        price_max=filter_state.get("price_max"),
        floor_levels=filter_state.get("floor_levels"),
        floor_area_min=filter_state.get("floor_area_min"),
        floor_area_max=filter_state.get("floor_area_max"),
        lease_remaining_min=filter_state.get("lease_remaining_min"),
        lease_remaining_max=filter_state.get("lease_remaining_max"),
        group_by=filter_state.get("group_by", "month"),
    )

    return {
        "id": report.id,
        "title": report.title,
        "description": report.description,
        "filter_state": filter_state,
        "ai_commentary": report.ai_commentary,
        "chart_config": json.loads(report.chart_config) if report.chart_config else None,
        "live_data": live_data,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }

@app.delete("/api/reports/{report_id}")
async def delete_report(report_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = db.query(AnalysisReport).filter(
        AnalysisReport.id == report_id,
        AnalysisReport.user_id == current_user.id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    db.delete(report)
    db.commit()
    return {"message": "Report deleted"}


# ---------------------------------------------------------------------------
# CHAT CONVERSATIONS CRUD
# ---------------------------------------------------------------------------

class ConversationCreate(BaseModel):
    title: Optional[str] = None
    report_id: Optional[int] = None
    context: Optional[dict] = None

@app.get("/api/conversations")
async def list_conversations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convos = (
        db.query(ChatConversation)
        .filter(ChatConversation.user_id == current_user.id)
        .order_by(ChatConversation.updated_at.desc())
        .all()
    )
    results = []
    for c in convos:
        last_msg = (
            db.query(DBChatMessage)
            .filter(DBChatMessage.conversation_id == c.id)
            .order_by(DBChatMessage.id.desc())
            .first()
        )
        results.append({
            "id": c.id,
            "title": c.title,
            "report_id": c.report_id,
            "preview": (last_msg.content or "")[:80] if last_msg else "",
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return results

@app.post("/api/conversations")
async def create_conversation(data: ConversationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convo = ChatConversation(
        user_id=current_user.id,
        title=data.title or "New Chat",
        report_id=data.report_id,
        context=json.dumps(data.context) if data.context else None,
    )
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return {"id": convo.id, "title": convo.title}

@app.get("/api/conversations/{convo_id}")
async def get_conversation(convo_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convo = db.query(ChatConversation).filter(
        ChatConversation.id == convo_id,
        ChatConversation.user_id == current_user.id,
    ).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = (
        db.query(DBChatMessage)
        .filter(DBChatMessage.conversation_id == convo_id)
        .order_by(DBChatMessage.id.asc())
        .all()
    )
    return {
        "id": convo.id,
        "title": convo.title,
        "report_id": convo.report_id,
        "context": json.loads(convo.context) if convo.context else None,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "blocks": json.loads(m.blocks) if m.blocks else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }

@app.delete("/api/conversations/{convo_id}")
async def delete_conversation(convo_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convo = db.query(ChatConversation).filter(
        ChatConversation.id == convo_id,
        ChatConversation.user_id == current_user.id,
    ).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.query(DBChatMessage).filter(DBChatMessage.conversation_id == convo_id).delete()
    db.delete(convo)
    db.commit()
    return {"message": "Conversation deleted"}


# ---------------------------------------------------------------------------
# AI CHAT (SSE streaming with persistence)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    messages: List[dict]
    conversation_id: Optional[int] = None
    context: Optional[dict] = None

@app.post("/api/chat")
async def chat_endpoint(
    req: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not has_premium_entitlements(current_user, request):
        raise HTTPException(status_code=403, detail="Premium subscription required for analytics chat")

    user = current_user

    convo_id = req.conversation_id
    if user and req.messages:
        user_content = req.messages[-1].get("content", "")

        if not convo_id:
            title = (user_content[:40] + "...") if len(user_content) > 40 else user_content
            convo = ChatConversation(
                user_id=user.id,
                title=title or "New Chat",
                context=json.dumps(req.context) if req.context else None,
            )
            db.add(convo)
            db.commit()
            db.refresh(convo)
            convo_id = convo.id

        db.add(DBChatMessage(
            conversation_id=convo_id,
            role="user",
            content=user_content,
        ))
        db.commit()

    analytics_context = req.context
    if not analytics_context and convo_id and user:
        convo = db.query(ChatConversation).filter(ChatConversation.id == convo_id).first()
        if convo and convo.context:
            analytics_context = json.loads(convo.context)

    def event_stream():
        all_blocks = []
        text_content = ""
        for block in ai_service.chat_completion(req.messages, analytics_context=analytics_context):
            if block.get("type") == "text":
                text_content += block.get("content", "")
            if block.get("type") in ("text", "chart", "tool_call"):
                all_blocks.append(block)

            if block.get("type") != "done" and convo_id:
                block["conversation_id"] = convo_id

            yield f"data: {json.dumps(block)}\n\n"

        if user and convo_id:
            inner_db = SessionLocal()
            try:
                inner_db.add(DBChatMessage(
                    conversation_id=convo_id,
                    role="assistant",
                    content=text_content,
                    blocks=json.dumps(all_blocks) if all_blocks else None,
                ))
                inner_db.query(ChatConversation).filter(
                    ChatConversation.id == convo_id
                ).update({"updated_at": datetime.utcnow()})
                inner_db.commit()
            finally:
                inner_db.close()

    from datetime import datetime
    return StreamingResponse(event_stream(), media_type="text/event-stream")

# --- USER STORY API ENDPOINTS ---

@app.get("/api/user/saved-properties")
async def get_saved_properties(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    props = (
        db.query(SavedProperty)
        .filter(SavedProperty.user_id == current_user.id)
        .order_by(SavedProperty.id.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "postal_code": p.postal_code,
            "property_type": p.property_type,
            "predicted_price": p.predicted_price,
            "created_at": p.created_at,
        }
        for p in props
    ]

class SavedPropertyCreate(BaseModel):
    postal_code: str
    property_type: str
    predicted_price: int

@app.post("/api/user/saved-properties")
async def save_property(prop_data: SavedPropertyCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from datetime import datetime
    if prop_data.predicted_price <= 0:
        raise HTTPException(status_code=400, detail="predicted_price must be positive")
    new_prop = SavedProperty(
        user_id=current_user.id,
        postal_code=prop_data.postal_code,
        property_type=prop_data.property_type,
        predicted_price=prop_data.predicted_price,
        created_at=datetime.now().isoformat()
    )
    db.add(new_prop)
    db.commit()
    db.refresh(new_prop)
    return new_prop

@app.delete("/api/user/saved-properties/{prop_id}")
async def delete_saved_property(prop_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prop = db.query(SavedProperty).filter(SavedProperty.id == prop_id, SavedProperty.user_id == current_user.id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    db.delete(prop)
    db.commit()
    return {"message": "Property deleted successfully"}

class ProfileUpdate(BaseModel):
    full_name: str

@app.get("/api/user/profile")
async def get_profile(current_user: User = Depends(get_current_user)):
    return {
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "remaining_valuations": getattr(current_user, "remaining_valuations", None),
    }

@app.put("/api/user/profile")
async def update_profile(profile_data: ProfileUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.full_name = profile_data.full_name
    db.commit()
    return {"message": "Profile updated successfully"}

@app.delete("/api/user/profile")
async def delete_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(SavedProperty).filter(SavedProperty.user_id == current_user.id).delete()
    db.delete(current_user)
    db.commit()
    return {"message": "Account deleted successfully"}

def _admin_usage_maps(db: Session):
    sp_rows = db.query(SavedProperty.user_id, func.count(SavedProperty.id)).group_by(SavedProperty.user_id).all()
    sp = {uid: c for uid, c in sp_rows if uid is not None}
    ar_rows = db.query(AnalysisReport.user_id, func.count(AnalysisReport.id)).group_by(AnalysisReport.user_id).all()
    ar = {uid: c for uid, c in ar_rows if uid is not None}
    cc_rows = db.query(ChatConversation.user_id, func.count(ChatConversation.id)).group_by(ChatConversation.user_id).all()
    cc = {uid: c for uid, c in cc_rows if uid is not None}
    cm_rows = (
        db.query(ChatConversation.user_id, func.count(DBChatMessage.id))
        .join(DBChatMessage, DBChatMessage.conversation_id == ChatConversation.id)
        .group_by(ChatConversation.user_id)
        .all()
    )
    cm = {uid: c for uid, c in cm_rows if uid is not None}
    return sp, ar, cc, cm


def _usage_for_user(uid: int, sp: dict, ar: dict, cc: dict, cm: dict) -> dict:
    return {
        "saved_properties": sp.get(uid, 0),
        "analysis_reports": ar.get(uid, 0),
        "chat_conversations": cc.get(uid, 0),
        "chat_messages": cm.get(uid, 0),
    }


def _serialize_admin_user(u: User, sp: dict, ar: dict, cc: dict, cm: dict) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_banned": bool(getattr(u, "is_banned", False)),
        "remaining_valuations": u.remaining_valuations,
        "usage": _usage_for_user(u.id, sp, ar, cc, cm),
    }


def _prefect_api_headers_for_server() -> dict:
    hdr = {}
    key = os.getenv("PREFECT_API_KEY", "").strip()
    if key:
        hdr["Authorization"] = f"Bearer {key}"
    ver = os.getenv("PREFECT_API_VERSION", "").strip()
    if ver:
        hdr["X-PREFECT-API-VERSION"] = ver
    return hdr


def _trigger_prefect_mrt_routing_flow(*, rerun_partial: bool, limit: int) -> dict:
    """Resolve Prefect deployment and POST create_flow_run (Prefect 3 server REST)."""
    import httpx

    base = os.getenv("PREFECT_API_URL", "").strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="PREFECT_API_URL is not configured.")

    flow_nm = os.getenv("PREFECT_MRT_FLOW_NAME", "hdb-mrt-routing").strip()
    dep_nm = os.getenv("PREFECT_MRT_DEPLOYMENT_NAME", "mrt-routing-default").strip()
    dep_override = os.getenv("PREFECT_MRT_ROUTING_DEPLOYMENT_ID", "").strip()
    hdr_base = dict(_prefect_api_headers_for_server())

    try:
        with httpx.Client(timeout=60.0) as client:
            if dep_override:
                dep_uuid = dep_override
            else:
                rm = client.get(
                    f"{base}/deployments/name/{flow_nm}/{dep_nm}",
                    headers=hdr_base,
                )
                if rm.status_code == 404:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            f"Prefect deployment '{flow_nm}/{dep_nm}' not found. Deploy from backend with "
                            "`prefect deploy --all --prefect-file prefect.yaml`, or set "
                            "PREFECT_MRT_ROUTING_DEPLOYMENT_ID to the deployment UUID."
                        ),
                    )
                rm.raise_for_status()
                dep_uuid = rm.json().get("id")
                if not dep_uuid:
                    raise HTTPException(
                        status_code=502,
                        detail="Prefect returned deployment payload without id.",
                    )

            hdr_run = dict(hdr_base)
            hdr_run["Content-Type"] = "application/json"
            cre = client.post(
                f"{base}/deployments/{dep_uuid}/create_flow_run",
                headers=hdr_run,
                json={"parameters": {"rerun_partial": rerun_partial, "limit": limit}},
            )
            if cre.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Prefect create_flow_run failed (HTTP {cre.status_code}): "
                        f"{cre.text[:800]}"
                    ),
                )
            return cre.json()
    except HTTPException:
        raise
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Prefect API at {base}: {exc}",
        ) from exc


def _trigger_prefect_model_training_flow(
    *,
    experiment_id: str,
    feature_set_id: str,
    feature_selection_policy: str | None = None,
) -> dict:
    """Resolve Prefect model-training deployment and POST ``create_flow_run``."""
    import httpx

    base = os.getenv("PREFECT_API_URL", "").strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="PREFECT_API_URL is not configured.")

    flow_nm = os.getenv("PREFECT_TRAINING_FLOW_NAME", "homeyai-model-train").strip()
    dep_nm = os.getenv("PREFECT_TRAINING_DEPLOYMENT_NAME", "model-train-default").strip()
    dep_override = os.getenv("PREFECT_MODEL_TRAINING_DEPLOYMENT_ID", "").strip()
    hdr_base = dict(_prefect_api_headers_for_server())

    try:
        with httpx.Client(timeout=60.0) as client:
            if dep_override:
                dep_uuid = dep_override
            else:
                rm = client.get(
                    f"{base}/deployments/name/{flow_nm}/{dep_nm}",
                    headers=hdr_base,
                )
                if rm.status_code == 404:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            f"Prefect deployment '{flow_nm}/{dep_nm}' not found. Deploy the flow or set "
                            "PREFECT_MODEL_TRAINING_DEPLOYMENT_ID to the deployment UUID."
                        ),
                    )
                rm.raise_for_status()
                dep_uuid = rm.json().get("id")
                if not dep_uuid:
                    raise HTTPException(
                        status_code=502,
                        detail="Prefect returned deployment payload without id.",
                    )

            hdr_run = dict(hdr_base)
            hdr_run["Content-Type"] = "application/json"
            params_body: dict[str, object] = {
                "experiment_id": experiment_id,
                "feature_set_id": feature_set_id,
            }
            if feature_selection_policy is not None:
                params_body["feature_selection_policy"] = feature_selection_policy
            cre = client.post(
                f"{base}/deployments/{dep_uuid}/create_flow_run",
                headers=hdr_run,
                json={"parameters": params_body},
            )
            if cre.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Prefect create_flow_run failed (HTTP {cre.status_code}): "
                        f"{cre.text[:800]}"
                    ),
                )
            return cre.json()
    except HTTPException:
        raise
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Prefect API at {base}: {exc}",
        ) from exc


def _trigger_prefect_model_training_batch_flow(
    *,
    experiment_ids: list[str] | None,
    dataset_version: str | None,
    use_gpu: bool | None,
    max_concurrent: int | None = None,
    feature_selection_policy: str | None = None,
) -> dict:
    """Resolve batch training deployment and POST ``create_flow_run``."""
    import httpx

    base = os.getenv("PREFECT_API_URL", "").strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="PREFECT_API_URL is not configured.")

    flow_nm = os.getenv("PREFECT_TRAINING_BATCH_FLOW_NAME", "homeyai-model-train-batch").strip()
    dep_nm = os.getenv("PREFECT_TRAINING_BATCH_DEPLOYMENT_NAME", "model-train-batch-default").strip()
    dep_override = os.getenv("PREFECT_MODEL_TRAINING_BATCH_DEPLOYMENT_ID", "").strip()
    hdr_base = dict(_prefect_api_headers_for_server())

    params: dict[str, object] = {}
    if experiment_ids is not None:
        params["experiment_ids"] = experiment_ids
    if dataset_version is not None:
        params["dataset_version"] = dataset_version
    if use_gpu is not None:
        params["use_gpu"] = use_gpu
    if max_concurrent is not None:
        params["max_concurrent"] = max_concurrent
    if feature_selection_policy is not None:
        params["feature_selection_policy"] = feature_selection_policy

    try:
        with httpx.Client(timeout=60.0) as client:
            if dep_override:
                dep_uuid = dep_override
            else:
                rm = client.get(
                    f"{base}/deployments/name/{flow_nm}/{dep_nm}",
                    headers=hdr_base,
                )
                if rm.status_code == 404:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            f"Prefect deployment '{flow_nm}/{dep_nm}' not found. Deploy the flow or set "
                            "PREFECT_MODEL_TRAINING_BATCH_DEPLOYMENT_ID to the deployment UUID."
                        ),
                    )
                rm.raise_for_status()
                dep_uuid = rm.json().get("id")
                if not dep_uuid:
                    raise HTTPException(
                        status_code=502,
                        detail="Prefect returned deployment payload without id.",
                    )

            hdr_run = dict(hdr_base)
            hdr_run["Content-Type"] = "application/json"
            cre = client.post(
                f"{base}/deployments/{dep_uuid}/create_flow_run",
                headers=hdr_run,
                json={"parameters": params},
            )
            if cre.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Prefect create_flow_run failed (HTTP {cre.status_code}): "
                        f"{cre.text[:800]}"
                    ),
                )
            return cre.json()
    except HTTPException:
        raise
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Prefect API at {base}: {exc}",
        ) from exc


def _prefect_flow_run_public_status(flow_run_id: str) -> dict:
    """Proxy Prefect ``GET /flow_runs/{id}`` into a simple UI state."""
    import httpx

    base = os.getenv("PREFECT_API_URL", "").strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="PREFECT_API_URL is not configured.")

    rid = flow_run_id.strip()
    if not rid:
        raise HTTPException(status_code=422, detail="flow_run_id is required.")

    hdr = dict(_prefect_api_headers_for_server())

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(f"{base}/flow_runs/{rid}", headers=hdr)
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail="Prefect flow run not found.")
            if r.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Prefect flow_runs GET failed (HTTP {r.status_code}): {r.text[:800]}"
                    ),
                )
            data = r.json()
    except HTTPException:
        raise
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Prefect API at {base}: {exc}",
        ) from exc

    state = data.get("state")
    st_raw = ""
    msg = ""
    if isinstance(state, dict):
        st_raw = str(state.get("type") or state.get("name") or "").strip().upper()
        msg = str(state.get("message") or "").strip()
        details = state.get("state_details")
        if not msg and isinstance(details, dict):
            msg = str(details.get("message") or "").strip()
    elif isinstance(state, str):
        st_raw = state.strip().upper()

    terminal_ok = {"COMPLETED", "COMPLETED_SUCCESSFULLY"}
    terminal_bad = {"FAILED", "CRASHED", "CANCELLED", "CANCELLED_FAILED"}

    if st_raw in terminal_ok:
        label = "Completed"
    elif st_raw in terminal_bad:
        label = "Failed"
    elif not st_raw:
        label = "Running"
    elif "FAIL" in st_raw or "CANCEL" in st_raw:
        label = "Failed"
    elif "COMPLETE" in st_raw:
        label = "Completed"
    else:
        label = "Running"

    return {"state": label, "state_message": msg or st_raw or "—"}


def _purge_user_owned_rows(db: Session, user_id: int) -> None:
    convo_ids = [r[0] for r in db.query(ChatConversation.id).filter(ChatConversation.user_id == user_id).all()]
    if convo_ids:
        db.query(DBChatMessage).filter(DBChatMessage.conversation_id.in_(convo_ids)).delete(synchronize_session=False)
    db.query(ChatConversation).filter(ChatConversation.user_id == user_id).delete(synchronize_session=False)
    db.query(AnalysisReport).filter(AnalysisReport.user_id == user_id).delete(synchronize_session=False)
    db.query(SavedProperty).filter(SavedProperty.user_id == user_id).delete(synchronize_session=False)


@app.get("/api/admin/metrics")
async def admin_metrics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    rows = db.query(User.role, func.count(User.id)).group_by(User.role).all()
    by_role = {r[0]: r[1] for r in rows}
    return {
        "total_users": db.query(User).count(),
        "by_role": by_role,
        "banned_users": db.query(User).filter(User.is_banned.is_(True)).count(),
    }


@app.get("/api/admin/hdb-enrichment-completeness")
async def admin_hdb_enrichment_completeness(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    return await run_in_threadpool(analytics_service.get_hdb_enrichment_completeness, db)


@app.post("/api/admin/trigger-mrt-routing")
async def admin_trigger_mrt_routing(
    body: TriggerMrtRoutingRequest,
    current_user: User = Depends(get_current_user),
):
    """Enqueue the Prefect ``hdb-mrt-routing`` deployment (needs a worker on the deployment work pool)."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    return await run_in_threadpool(
        _trigger_prefect_mrt_routing_flow,
        rerun_partial=body.rerun_partial,
        limit=body.limit,
    )


@app.get("/api/admin/ml/experiments")
async def admin_ml_experiments_catalog(
    env: Optional[str] = Query(None, description="MinIO env segment for publish check (default MODEL_ENV)"),
    current_user: User = Depends(get_current_user),
):
    """MinIO ``valuation/experiments`` catalog."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    use_env = (env or os.getenv("MODEL_ENV", "prod")).strip()
    return await run_in_threadpool(_admin_ml_experiments_catalog, use_env)


@app.get("/api/admin/ml/experiment-run-detail")
async def admin_experiment_run_detail(
    run_id: str = Query(..., min_length=1, description="Experiment directory id / logical run id"),
    env: Optional[str] = Query(None, description="MinIO env segment for publish check (default MODEL_ENV)"),
    current_user: User = Depends(get_current_user),
):
    """Full experiment row (config, metrics, best_params) for one run — use after slim dashboard payload."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    rid = run_id.strip()
    use_env = (env or os.getenv("MODEL_ENV", "prod")).strip()
    try:
        return await run_in_threadpool(_admin_experiment_run_detail_sync, rid, use_env)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class ExperimentReportResolveBody(BaseModel):
    run_id: str = Field(..., min_length=1, description="Experiment run directory id (MinIO valuation/experiments/<id>/)")
    env: Optional[str] = Field(None, description="MinIO env segment (default MODEL_ENV)")
    use_existing_pdf: bool = Field(
        False,
        description="If true, return presigned URL for current report.pdf without regenerating (legacy cache).",
    )


@app.get("/api/admin/ml/experiment-report")
async def admin_experiment_training_report_pdf_url(
    run_id: str = Query(..., min_length=1, description="Experiment run directory id"),
    env: Optional[str] = Query(None, description="MinIO env segment (default MODEL_ENV)"),
    current_user: User = Depends(get_current_user),
):
    """Presigned download URL only when ``report.pdf`` already exists (TTL ~15m).

    To **build or fetch** PDF (creating ``report.pdf`` from ``metrics.json`` when missing),
    use ``POST /api/admin/ml/experiment-report`` instead.
    """

    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    use_env = (env or os.getenv("MODEL_ENV", "prod")).strip()
    rid = run_id.strip()

    def _url() -> Optional[str]:
        return model_store.presigned_experiment_report_pdf_url(use_env, rid)

    url = await run_in_threadpool(_url)
    if not url:
        raise HTTPException(status_code=404, detail="report.pdf not found for this run_id/env")
    return {"url": url, "run_id": rid, "env": use_env}


@app.post("/api/admin/ml/experiment-report")
async def admin_experiment_training_report_resolve(
    body: ExperimentReportResolveBody,
    current_user: User = Depends(get_current_user),
):
    """Presigned GET URL for training ``report.pdf``; **regenerates** from MinIO artefacts by default.

    Set ``use_existing_pdf: true`` in the body only to presign the current blob without rebuilding.
    Use ``GET /api/admin/ml/experiment-report`` when the PDF already exists and you only need a URL.
    """

    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    use_env = (body.env or os.getenv("MODEL_ENV", "prod")).strip().strip("/")
    rid = body.run_id.strip().strip("/")

    def _sync() -> tuple[str, bool]:
        return ensure_experiment_report_presigned_url(rid, use_env, use_existing_pdf=body.use_existing_pdf)

    try:
        url, rebuilt = await run_in_threadpool(_sync)
    except ExperimentReportBuildError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": exc.message,
                "missing": exc.missing_components,
            },
        ) from exc

    return {
        "url": url,
        "run_id": rid,
        "env": use_env,
        "rebuilt": rebuilt,
    }


def _unlink_experiment_assets_zip_temp(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _build_experiment_run_assets_zip_temp_path(env: str, run_id: str) -> str:
    """Write all objects under ``valuation/experiments/<run_id>/`` or legacy ``artifacts/<run_id>/`` into a temp zip.

    Very large runs (e.g. huge ``training_data.parquet``) may take tens of seconds or hit reverse-proxy timeouts.
    """
    rid = run_id.strip().strip("/")
    if not rid or "/" in rid:
        raise ValueError("invalid run_id")
    prefixes = (
        f"{env}/valuation/experiments/{rid}/",
        f"{env}/valuation/artifacts/{rid}/",
    )
    chosen: str | None = None
    rows: list[dict[str, Any]] = []
    for pref in prefixes:
        found = model_store.list_objects_with_prefix(pref)
        if found:
            chosen = pref
            rows = found
            break
    if not chosen:
        raise FileNotFoundError(
            f"No MinIO objects for run_id={rid!r} under valuation/experiments/ or "
            f"valuation/artifacts/ (env={env!r})."
        )

    fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for row in rows:
                key = str(row.get("object_name") or "")
                if not key.startswith(chosen):
                    continue
                arc = key[len(chosen) :]
                if not arc or arc.endswith("/"):
                    continue
                model_store.stream_object_into_zip(zf, key, arc)
    except Exception:
        _unlink_experiment_assets_zip_temp(tmp_path)
        raise
    return tmp_path


class ExperimentRunAssetsZipBody(BaseModel):
    run_id: str = Field(..., min_length=1, description="Experiment folder id under valuation/experiments or artifacts")
    env: Optional[str] = Field(None, description="MinIO env segment (default MODEL_ENV)")


@app.post("/api/admin/ml/experiment-run-assets-zip")
async def admin_experiment_run_assets_zip(
    body: ExperimentRunAssetsZipBody,
    current_user: User = Depends(get_current_user),
):
    """Zip all objects for one run (canonical ``experiments/<id>/`` first, else legacy ``artifacts/<id>/``)."""

    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    use_env = (body.env or os.getenv("MODEL_ENV", "prod")).strip().strip("/")
    rid = body.run_id.strip().strip("/")
    if not rid or "/" in rid:
        raise HTTPException(status_code=400, detail="Invalid run_id")

    try:
        tmp_path = await run_in_threadpool(_build_experiment_run_assets_zip_temp_path, use_env, rid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    safe_name = f"{rid}_assets.zip"
    return FileResponse(
        tmp_path,
        filename=safe_name,
        media_type="application/zip",
        background=BackgroundTask(_unlink_experiment_assets_zip_temp, tmp_path),
    )


def _parse_dashboard_include(include: str) -> set[str]:
    allowed = {"metrics", "status", "experiments", "artifacts"}
    parts = {p.strip().lower() for p in include.split(",") if p.strip()}
    selected = parts & allowed
    return selected if selected else allowed



@app.get("/api/admin/dashboard")
async def admin_model_dashboard(
    env: Optional[str] = Query(None, description="MinIO env segment for artifacts/catalog (default MODEL_ENV)"),
    include: str = Query(
        "metrics,status,experiments,artifacts",
        description="Comma-separated: metrics, status, experiments, artifacts",
    ),
    experiments_detail: bool = Query(
        True,
        description="When false, experiments list returns slim rows (use experiment-run-detail for full row)",
    ),
    debug_timings: bool = Query(False, description="Include _timings object in JSON (admin diagnostics)"),
    current_user: User = Depends(get_current_user),
):
    """Bundled admin model-management payload (single round-trip): version, metrics, artifacts, experiments, serving."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    use_env = (env or os.getenv("MODEL_ENV", "prod")).strip()
    inc = _parse_dashboard_include(include)
    timings: dict[str, Any] = {}
    t_wall0 = time.perf_counter()

    prefetched_exp_keys: list[str] | None = None
    if "metrics" in inc or "experiments" in inc:
        prefetched_exp_keys = await run_in_threadpool(
            model_store.list_valuation_experiment_model_keys,
            use_env,
        )

    need_keys = ("artifacts" in inc) or ("experiments" in inc)
    phase1_labels: list[str] = []
    phase1_coros: list[Any] = []
    if need_keys:
        phase1_labels.append("keys")
        phase1_coros.append(run_in_threadpool(model_store.list_valuation_model_object_keys, use_env))
    if "metrics" in inc:
        phase1_labels.append("metrics")
        phase1_coros.append(run_in_threadpool(_load_metrics_payload, prefetched_exp_keys))
    if "status" in inc:
        phase1_labels.append("status")
        phase1_coros.append(run_in_threadpool(_admin_serving_status_payload_sync))

    t1 = time.perf_counter()
    r1 = await asyncio.gather(*phase1_coros, return_exceptions=True) if phase1_coros else []
    timings["phase1_ms"] = round((time.perf_counter() - t1) * 1000)
    p1 = dict(zip(phase1_labels, r1))
    keys_raw = p1.get("keys") if need_keys else []
    keys = keys_raw if isinstance(keys_raw, list) else []
    folders = model_store.folder_names_from_model_keys(keys) if need_keys else set()

    phase2_labels: list[str] = []
    phase2_coros = []
    if "artifacts" in inc:
        phase2_labels.append("artifacts")
        phase2_coros.append(
            run_in_threadpool(
                model_store.describe_valuation_artifacts,
                use_env,
                active_object_key=ml_service.model_object_key(),
                prefetched_model_keys=keys if need_keys else None,
            )
        )
    if "experiments" in inc:
        phase2_labels.append("experiments")
        phase2_coros.append(
            run_in_threadpool(
                _admin_ml_experiments_catalog,
                use_env,
                folders if need_keys else None,
                not experiments_detail,
                prefetched_exp_keys,
            )
        )

    t2 = time.perf_counter()
    r2 = await asyncio.gather(*phase2_coros, return_exceptions=True) if phase2_coros else []
    timings["phase2_ms"] = round((time.perf_counter() - t2) * 1000)
    p2 = dict(zip(phase2_labels, r2))

    def _safe_artifacts(r: Any) -> list:
        return r if isinstance(r, list) else []

    def _safe_experiments(r: Any) -> dict:
        return r if isinstance(r, dict) else {"env": use_env, "experiments": []}

    def _safe_status(r: Any):
        return None if isinstance(r, Exception) else r

    def _safe_metrics(r: Any):
        return None if isinstance(r, Exception) else r

    artifacts_res = _safe_artifacts(p2.get("artifacts")) if "artifacts" in inc else []
    experiments_res = (
        _safe_experiments(p2.get("experiments"))
        if "experiments" in inc
        else {"env": use_env, "experiments": []}
    )
    metrics_res = _safe_metrics(p1.get("metrics")) if "metrics" in inc else None
    status_res = _safe_status(p1.get("status")) if "status" in inc else None

    timings["total_ms"] = round((time.perf_counter() - t_wall0) * 1000)
    timings["include"] = sorted(inc)
    logger.info("admin_dashboard timings env=%s ms=%s", use_env, timings)

    out: dict[str, Any] = {
        "version": get_version(),
        "env": use_env,
        "artifacts": {"env": use_env, "artifacts": artifacts_res},
        "experiments": experiments_res,
        "model_status": status_res,
        "metrics": metrics_res,
    }
    if debug_timings:
        out["_timings"] = timings
    return out


@app.get("/api/admin/model/artifacts")
async def admin_list_valuation_artifacts(
    env: Optional[str] = Query(None, description="MinIO prefix env segment (default MODEL_ENV)"),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    use_env = (env or os.getenv("MODEL_ENV", "prod")).strip()
    try:
        artifacts = model_store.describe_valuation_artifacts(
            use_env,
            active_object_key=ml_service.model_object_key(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not list MinIO valuation artifacts: {exc}",
        ) from exc
    return {"env": use_env, "artifacts": artifacts}


@app.get("/api/admin/model/status")
async def admin_model_serving_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    base = ml_service.admin_serving_status()
    return _enrich_admin_serving_status_from_registry(db, base)


@app.post("/api/admin/model/promote")
async def admin_promote_valuation_model(
    body: AdminModelPromoteBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    key = body.object_key.strip()
    if not key.endswith("model.pkl"):
        raise HTTPException(
            status_code=422,
            detail="object_key must point to a valuation model.pkl artifact.",
        )
    if not model_store.object_exists(key):
        raise HTTPException(status_code=404, detail=f"MinIO object not found: {key}")
    try:
        meta = ml_service.init_from_key(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    metrics_side = model_store.load_json_sidecar_from_object_key(key, "metrics.json") or {}
    tm = metrics_side.get("test_metrics") or {}
    rmse_v = None
    try:
        if tm.get("rmse") is not None:
            rmse_v = float(tm["rmse"])
    except (TypeError, ValueError):
        rmse_v = None
    # Registry + startup always key off MODEL_ENV; must match MinIO prefix ({MODEL_ENV}/valuation/...).
    registry_env = (os.getenv("MODEL_ENV", "prod")).strip().strip("/")
    prefix = f"{registry_env}/"
    if not key.startswith(prefix):
        hint = key.split("/")[0] if "/" in key else key
        raise HTTPException(
            status_code=422,
            detail=(
                f"object_key must start with MODEL_ENV prefix {prefix!r} (current MODEL_ENV={registry_env!r}). "
                f"Key starts with {hint!r}. Fix MODEL_ENV or use keys under {prefix}valuation/…"
            ),
        )
    _upsert_model_version_as_production(
        db,
        env=registry_env,
        object_key=key,
        experiment_id=meta.get("experiment_id"),
        feature_set_id=meta.get("feature_set_id"),
        model_id=meta.get("model_id"),
        rmse=rmse_v,
        user_id=current_user.id,
    )
    model_store.invalidate_valuation_model_keys_cache(registry_env)
    status_payload = _enrich_admin_serving_status_from_registry(
        db, ml_service.admin_serving_status()
    )
    return {"ok": True, **meta, "model_status": status_payload}


@app.post("/api/admin/model/train")
async def admin_trigger_model_training(
    body: AdminModelTrainBody,
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    out = await run_in_threadpool(
        _trigger_prefect_model_training_flow,
        experiment_id=body.experiment_id.strip(),
        feature_set_id=body.feature_set_id.strip(),
        feature_selection_policy=(body.feature_selection_policy.strip() if body.feature_selection_policy else None),
    )
    fid = out.get("id")
    if not fid:
        raise HTTPException(status_code=502, detail="Prefect did not return a flow run id.")
    return {"flow_run_id": str(fid)}


@app.post("/api/admin/model/train/batch")
async def admin_trigger_model_training_batch(
    body: AdminModelTrainBatchBody,
    current_user: User = Depends(get_current_user),
):
    """Enqueue Prefect ``homeyai-model-train-batch`` (default experiment list: PERFORMANCE_PLAN_V1)."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    out = await run_in_threadpool(
        _trigger_prefect_model_training_batch_flow,
        experiment_ids=body.experiment_ids,
        dataset_version=body.dataset_version,
        use_gpu=body.use_gpu,
        max_concurrent=body.max_concurrent,
        feature_selection_policy=(
            body.feature_selection_policy.strip() if body.feature_selection_policy else None
        ),
    )
    fid = out.get("id")
    if not fid:
        raise HTTPException(status_code=502, detail="Prefect did not return a flow run id.")
    return {"flow_run_id": str(fid)}


@app.get("/api/admin/model/train/status/{flow_run_id}")
async def admin_model_training_status(
    flow_run_id: str,
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return await run_in_threadpool(_prefect_flow_run_public_status, flow_run_id)


@app.get("/api/admin/users")
async def get_all_users(q: Optional[str] = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = db.query(User)
    if q:
        query = query.filter((User.email.ilike(f"%{q}%")) | (User.full_name.ilike(f"%{q}%")))
        
    users = query.order_by(User.id.asc()).all()
    sp, ar, cc, cm = _admin_usage_maps(db)
    return [_serialize_admin_user(u, sp, ar, cc, cm) for u in users]


@app.get("/api/admin/users/{user_id}")
async def get_admin_user(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    sp, ar, cc, cm = _admin_usage_maps(db)
    return _serialize_admin_user(u, sp, ar, cc, cm)


class AdminUserUpdate(BaseModel):
    role: Optional[str] = None
    is_banned: Optional[bool] = None


@app.patch("/api/admin/users/{user_id}")
async def update_admin_user(
    user_id: int,
    body: AdminUserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    if body.role is None and body.is_banned is None:
        raise HTTPException(status_code=400, detail="No fields to update")

    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    if body.is_banned is not None:
        if user_id == current_user.id and body.is_banned:
            raise HTTPException(status_code=400, detail="You cannot ban your own account")
        u.is_banned = body.is_banned

    if body.role is not None:
        allowed = {UserRole.GUEST, UserRole.FREE, UserRole.PREMIUM, UserRole.ADMIN}
        try:
            new_role = UserRole(body.role)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid role")
        if new_role not in allowed:
            raise HTTPException(status_code=400, detail="Invalid role")

        if user_id == current_user.id and new_role != UserRole.ADMIN:
            raise HTTPException(status_code=400, detail="You cannot demote your own admin account")

        admin_count = db.query(User).filter(User.role == UserRole.ADMIN).count()
        if u.role == UserRole.ADMIN and new_role != UserRole.ADMIN and admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last admin")

        u.role = new_role

    db.commit()
    db.refresh(u)
    sp, ar, cc, cm = _admin_usage_maps(db)
    return _serialize_admin_user(u, sp, ar, cc, cm)


@app.delete("/api/admin/users/{user_id}")
async def delete_admin_user(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    if u.role == UserRole.ADMIN:
        admin_count = db.query(User).filter(User.role == UserRole.ADMIN).count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")

    _purge_user_owned_rows(db, user_id)
    db.delete(u)
    db.commit()
    return {"message": "User deleted"}


# --- PDF REPORT ENDPOINTS (User Stories #24, #25) ---

class ReportConfig(BaseModel):
    include_property_details: bool = True
    include_valuation_summary: bool = True
    include_amenities: bool = True
    include_market_insights: bool = True
    include_market_sentiment: bool = True
    include_comparative_analysis: bool = True

class ValuationReportRequest(BaseModel):
    property_data: ValuationInput
    valuation_data: dict
    report_config: ReportConfig = ReportConfig()

@app.post("/api/reports/valuation/pdf")
async def generate_pdf_report(
    report: ValuationReportRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate a PDF valuation report with customizable metrics.
    Only available for PREMIUM users.
    """
    # Check if user is premium
    if not has_premium_entitlements(current_user, http_request):
        raise HTTPException(
            status_code=403, 
            detail="PDF report generation is only available for Premium subscribers"
        )
    
    # Fetch extra analysis data
    market_sentiment = None
    if report.report_config.include_market_sentiment:
        try:
            market_sentiment = sentiment_service.get_market_sentiment()
        except Exception as e:
            print(f"ERROR fetching market sentiment: {e}")

    comparative_data = None
    if report.report_config.include_comparative_analysis:
        try:
            comparative_data = analytics_service.get_district_analytics(report.property_data.town)
        except Exception as e:
            print(f"ERROR fetching comparative data: {e}")

    # Generate the PDF
    property_data = {
        'postal_code': report.property_data.postal_code,
        'town': report.property_data.town,
        'flat_type': report.property_data.flat_type,
        'floor_area_sqm': report.property_data.floor_area_sqm,
        'remaining_lease_years': report.property_data.remaining_lease_years,
        'storey_midpoint': report.property_data.storey_midpoint
    }
    
    report_config = report.report_config.model_dump()
    
    pdf_buffer = report_service.generate_valuation_report(
        property_data=property_data,
        valuation_data=report.valuation_data,
        user_email=current_user.email,
        report_config=report_config,
        market_sentiment=market_sentiment,
        comparative_data=comparative_data
    )
    
    return Response(
        content=pdf_buffer.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=homeyai_valuation_report.pdf"
        }
    )

@app.get("/api/reports/config/default")
async def get_default_report_config():
    """Get the default report configuration (all metrics enabled)."""
    return report_service.get_default_report_config()


class ReportPreview(BaseModel):
    """Preview data for PDF report sections."""
    sections: list[dict]
    page_count_estimate: int
    included_metrics: list[str]

@app.post("/api/reports/valuation/preview")
async def get_report_preview(
    request: ValuationReportRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Get a JSON preview of the PDF report content without generating the PDF.
    This allows users to preview the report interactively before downloading.
    """
    if not has_premium_entitlements(current_user, http_request):
        raise HTTPException(status_code=403, detail="Premium subscription required for valuation reports")
    sections = []
    included_metrics = []
    
    # Always include header and executive summary
    sections.append({
        "id": "header",
        "title": "Property Valuation Report",
        "subtitle": "Prepared by HomeyAI Valuation Services",
        "type": "header",
        "metadata": {
            "prepared_for": current_user.email,
            "property_type": "HDB",
            "postal_code": request.property_data.postal_code,
            "floor_area": f"{request.property_data.floor_area_sqm} sqm"
        }
    })
    
    sections.append({
        "id": "executive_summary",
        "title": "Executive Summary",
        "type": "summary",
        "content": f"Estimated market value: S${request.valuation_data['predicted_price']:,.2f}"
    })
    
    # Valuation Summary
    if request.report_config.include_valuation_summary:
        included_metrics.append("Valuation Summary")
        ci = request.valuation_data.get('confidence_interval', [0, 0])
        sections.append({
            "id": "valuation_summary",
            "title": "Valuation Summary",
            "type": "table",
            "data": [
                {"metric": "Estimated Market Value", "value": f"S${request.valuation_data['predicted_price']:,.2f}"},
                {"metric": "Lower range bound", "value": f"S${ci[0]:,.2f}"},
                {"metric": "Upper range bound", "value": f"S${ci[1]:,.2f}"},
                {"metric": "Range methodology", "value": report_service.interval_description(request.valuation_data)[1]},
            ]
        })
    
    # Property Details
    if request.report_config.include_property_details:
        included_metrics.append("Property Details")
        sections.append({
            "id": "property_details",
            "title": "Property Specifications",
            "type": "table",
            "data": [
                {"metric": "Property Type", "value": "HDB"},
                {"metric": "Postal Code", "value": request.property_data.postal_code},
                {"metric": "Floor Area", "value": f"{request.property_data.floor_area_sqm} sqm"},
                {"metric": "Remaining Lease", "value": f"{request.property_data.remaining_lease_years} years"},
                {"metric": "Floor Level", "value": request.property_data.storey_midpoint}
            ]
        })
    
    # Amenities
    if request.report_config.include_amenities:
        included_metrics.append("Amenities")
        amenities = request.valuation_data.get('amenities', {})
        sections.append({
            "id": "amenities",
            "title": "Location & Nearby Amenities",
            "type": "table",
            "data": [
                {"metric": "Nearest MRT", "value": amenities.get('mrt', 'N/A')},
                {"metric": "Nearest School", "value": amenities.get('school', 'N/A')},
                {"metric": "Distance to CBD", "value": amenities.get('cbd_distance', 'N/A')}
            ]
        })
    
    # Market Insights
    if request.report_config.include_market_insights:
        included_metrics.append("Market Insights")
        sections.append({
            "id": "market_insights",
            "title": "Market Analysis & Insights",
            "type": "text",
            "content": "AI-powered market analysis based on historical transaction data"
        })
    
    # Estimate page count (rough estimate)
    page_count = 1  # Header + Executive Summary
    if request.report_config.include_valuation_summary:
        page_count += 1
    if request.report_config.include_property_details:
        page_count += 1
    if request.report_config.include_amenities:
        page_count += 1
    if request.report_config.include_market_insights:
        page_count += 1  # This section has PageBreak
    
    return ReportPreview(
        sections=sections,
        page_count_estimate=page_count,
        included_metrics=included_metrics
    )


class HtmlPreviewResponse(BaseModel):
    """HTML preview response for interactive report display."""
    html: str
    page_count: int


@app.post("/api/reports/valuation/preview/html")
async def get_html_report_preview(
    request: ValuationReportRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Get an HTML preview of the PDF report for interactive display.
    Returns rendered HTML that can be displayed in an iframe.
    """
    if not has_premium_entitlements(current_user, http_request):
        raise HTTPException(status_code=403, detail="Premium subscription required for valuation reports")
    # Fetch extra analysis data
    market_sentiment = None
    sentiment_error = None
    if request.report_config.include_market_sentiment:
        try:
            market_sentiment = sentiment_service.get_market_sentiment()
        except Exception as e:
            sentiment_error = str(e)
            print(f"ERROR fetching market sentiment preview: {e}")

    comparative_data = None
    comparative_error = None
    if request.report_config.include_comparative_analysis:
        try:
            comparative_data = analytics_service.get_district_analytics(request.property_data.town)
        except Exception as e:
            comparative_error = str(e)
            print(f"ERROR fetching comparative data preview: {e}")

    property_data = {
        'postal_code': request.property_data.postal_code,
        'town': request.property_data.town,
        'flat_type': request.property_data.flat_type,
        'floor_area_sqm': request.property_data.floor_area_sqm,
        'remaining_lease_years': request.property_data.remaining_lease_years,
        'storey_midpoint': request.property_data.storey_midpoint
    }
    
    html, page_count = report_service.generate_html_preview(
        property_data=property_data,
        valuation_data=request.valuation_data,
        user_email=current_user.email,
        report_config=request.report_config.model_dump(),
        market_sentiment=market_sentiment,
        comparative_data=comparative_data,
        sentiment_error=sentiment_error,
        comparative_error=comparative_error,
    )

    return {"html": html, "page_count": page_count}


@app.get("/api/admin/data-catalog")
async def get_data_catalog(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    from sqlalchemy import text
    from minio import Minio
    import os
    
    # 1. Dynamically discover all user tables in PostgreSQL
    pg_tables = {}
    try:
        # Get all user-created tables (exclude pg system tables)
        tables_result = db.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """))
        table_names = [row[0] for row in tables_result]

        for table in table_names:
            try:
                # Row count
                count = db.execute(text(f"SELECT COUNT(*) FROM \"{table}\"")).scalar()

                # Column schema
                col_result = db.execute(text("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = 'public' AND table_name = :tname
                    ORDER BY ordinal_position
                """), {"tname": table})
                columns = [{"name": r[0], "type": r[1]} for r in col_result]

                # Check if it's a geospatial table (has geometry column)
                geo_check = db.execute(text("""
                    SELECT COUNT(*) FROM geometry_columns 
                    WHERE f_table_name = :tname
                """), {"tname": table}).scalar()

                pg_tables[table] = {
                    "row_count": count,
                    "columns": columns,
                    "is_geospatial": geo_check > 0,
                    "description": "PostGIS spatial table" if geo_check > 0 else "Relational table"
                }
            except Exception as te:
                pg_tables[table] = {"error": str(te)}
    except Exception as e:
        pg_tables["_error"] = str(e)

    # 2. MinIO Object Storage Stats
    minio_stats = {"datasets": [], "models": []}
    try:
        MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
        MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
        MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "password123")
        client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)

        for bucket in ["datasets", "models"]:
            if client.bucket_exists(bucket):
                objects = client.list_objects(bucket, recursive=True)
                for obj in objects:
                    minio_stats[bucket].append({
                        "name": obj.object_name,
                        "size_mb": round(obj.size / (1024 * 1024), 2),
                        "last_modified": str(obj.last_modified)
                    })
    except Exception as e:
        minio_stats["error"] = str(e)

    return {
        "serving_layer": pg_tables,
        "object_storage": minio_stats
    }


@app.get("/api/admin/minio/browse")
async def admin_minio_browse(
    bucket: str,
    prefix: str = "",
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        return minio_catalog.browse(bucket, prefix)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/admin/minio/preview")
async def admin_minio_preview(
    bucket: str,
    key: str,
    current_user: User = Depends(get_current_user),
):
    from minio.error import S3Error

    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        return minio_catalog.preview(bucket, key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except S3Error as e:
        if getattr(e, "code", None) == "NoSuchKey":
            raise HTTPException(status_code=404, detail="Object not found")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class DataQueryRequest(BaseModel):
    query_type: str # 'sample' or 'sql'
    table_name: Optional[str] = None
    n: Optional[int] = 10
    sql: Optional[str] = None

@app.post("/api/admin/data-query")
async def execute_data_query(query_request: DataQueryRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    from sqlalchemy import text
    
    if query_request.query_type == "sample":
        if not query_request.table_name:
            raise HTTPException(status_code=400, detail="table_name required for sample query")
        # Use simple limit for sampling
        query = text(f"SELECT * FROM {query_request.table_name} LIMIT {query_request.n or 10}")
    elif query_request.query_type == "sql":
        if not query_request.sql:
            raise HTTPException(status_code=400, detail="sql required for sql query")
        # Basic security: only Allow SELECT queries
        clean_sql = query_request.sql.strip()
        if not clean_sql.upper().startswith("SELECT"):
            raise HTTPException(status_code=400, detail="Only SELECT statements are allowed for security.")
        query = text(clean_sql)
    else:
        raise HTTPException(status_code=400, detail="Invalid query_type")

    try:
        result = db.execute(query)
        columns = result.keys()
        rows = [dict(zip(columns, row)) for row in result]
        return {
            "columns": list(columns),
            "data": rows
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database Query Error: {str(e)}")


# ---------------------------------------------------------------------------
# SYSTEM HEALTH ENDPOINT
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Admin-only endpoint that probes every layer of the remote data pipeline:
      - PostgreSQL (via Tailscale → VM:5432)
      - MinIO / S3  (via Tailscale → VM:9000)
    Returns green/red status for each service plus a masked environment audit
    so developers can instantly verify their Tailscale connection.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")

    _vm_ip = os.getenv("REMOTE_VM_IP", "").strip()
    _vm_reachability_hint = (
        f" — Check if Tailscale is connected and the VM is reachable ({_vm_ip})"
        if _vm_ip
        else " — Check if Tailscale is connected and the VM is reachable"
    )

    # --- Postgres probe (non-destructive SELECT 1) ---
    postgres_result: dict
    try:
        from sqlalchemy import text as sa_text
        db.execute(sa_text("SELECT 1"))
        postgres_result = {"status": "ok", "message": "SELECT 1 succeeded — database connection is active"}
    except Exception as exc:
        msg = str(exc)
        hint = _vm_reachability_hint if any(
            kw in msg.lower() for kw in ("timeout", "connect", "refused", "broken")
        ) else ""
        postgres_result = {"status": "error", "message": f"{msg}{hint}"}

    # --- MinIO probe (read-only list_buckets) ---
    minio_result: dict
    try:
        from minio import Minio
        endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
        access_key = os.getenv("MINIO_ACCESS_KEY", "admin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "password123")
        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
        buckets = [b.name for b in client.list_buckets()]
        bucket_list = ", ".join(buckets) if buckets else "none found"
        minio_result = {"status": "ok", "message": f"Buckets accessible: {bucket_list}"}
    except Exception as exc:
        msg = str(exc)
        hint = _vm_reachability_hint if any(
            kw in msg.lower() for kw in ("timeout", "connect", "refused", "broken")
        ) else ""
        minio_result = {"status": "error", "message": f"{msg}{hint}"}

    # --- Prefect probe (read-only health check) ---
    prefect_result: dict
    try:
        import httpx
        prefect_url = os.getenv("PREFECT_API_URL", "http://prefect-server:4200/api")
        resp = httpx.get(f"{prefect_url}/health", timeout=5.0)
        if resp.status_code == 200:
            prefect_result = {"status": "ok", "message": f"Prefect API is reachable at {prefect_url}"}
        else:
            prefect_result = {"status": "error", "message": f"Prefect returned HTTP {resp.status_code}"}
    except Exception as exc:
        msg = str(exc)
        hint = " — Check if Prefect server is running on the VM" if any(
            kw in msg.lower() for kw in ("timeout", "connect", "refused", "broken")
        ) else ""
        prefect_result = {"status": "error", "message": f"{msg}{hint}"}

    # --- Environment audit (no secrets exposed) ---
    database_url = os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL") or ""
    minio_endpoint = os.getenv("MINIO_ENDPOINT", "not configured")
    prefect_api_url = os.getenv("PREFECT_API_URL", "not configured")

    host_match = re.search(r"@([^:@/]+):(\d+)/", database_url)
    db_host = host_match.group(1) if host_match else "not configured"
    db_port = host_match.group(2) if host_match else "not configured"

    return {
        "api": {"status": "ok", "message": "FastAPI backend is reachable"},
        "postgres": postgres_result,
        "minio": minio_result,
        "prefect": prefect_result,
        "environment": {
            "db_host": db_host,
            "db_port": db_port,
            "minio_endpoint": minio_endpoint,
            "prefect_api_url": prefect_api_url,
        },
    }


# ---------------------------------------------------------------------------
# USER STORY #28: AI CHAT ASSISTANT
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    message: str
    conversation_history: Optional[List[dict]] = None

class ChatResponse(BaseModel):
    response: str
    sources: Optional[List[str]] = None
    confidence: Optional[float] = None
    mode: str = "local_data"

@app.post("/api/ai/chat")
async def chat_with_ai(
    chat_data: ChatMessage,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    User Story #28: Chat with AI assistant about market trends and property insights.
    Only available for PREMIUM users.
    """
    # Check if user is premium
    if not has_premium_entitlements(current_user, request):
        raise HTTPException(
            status_code=403,
            detail="AI Chat Assistant is only available for Premium subscribers"
        )
    
    history = [
        {"role": item["role"], "content": item["content"]}
        for item in (chat_data.conversation_history or [])[-20:]
        if item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str)
    ]
    history.append({"role": "user", "content": chat_data.message})
    blocks = await run_in_threadpool(lambda: list(ai_service.chat_completion(history)))
    content = "\n".join(block["content"] for block in blocks if block.get("type") == "text")
    return ChatResponse(
        response=content or "No analysis is available for this request.",
        sources=["Local HDB recorded resale transaction database"],
        mode="openai" if ai_service.OPENAI_API_KEY else "local_data",
    )


# ---------------------------------------------------------------------------
# USER STORY #29: MARKET SENTIMENT SCORE
# ---------------------------------------------------------------------------

class MarketSentimentResponse(BaseModel):
    overall_score: int  # 0-100
    sentiment_label: str  # Bullish, Neutral, Bearish
    confidence: float
    factors: List[dict]
    trend: str  # Improving, Stable, Declining
    last_updated: str

@app.get("/api/market/sentiment")
async def get_market_sentiment(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    User Story #29: Get market sentiment score based on news and social data.
    Only available for PREMIUM users.
    """
    # Check if user is premium
    if not has_premium_entitlements(current_user, request):
        raise HTTPException(
            status_code=403,
            detail="Market Sentiment Score is only available for Premium subscribers"
        )
    
    from services import sentiment_service
    try:
        return sentiment_service.get_market_sentiment()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sentiment computation failed: {exc}")
