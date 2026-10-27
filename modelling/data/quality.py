"""Training-data quality gates, YAML config, and engineered-frame preview checks."""

from __future__ import annotations

import math
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from modelling.config.feature_sets import get_feature_set


class DataQualityError(RuntimeError):
    """Raised when the training frame fails a pre-flight quality gate."""


@dataclass
class FeatureStats:
    """Per-column completeness / cardinality (JSON-serializable)."""

    null_rate: float
    nunique: int
    mean: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    p5: float | None = None
    p95: float | None = None
    kind: str = "numeric"  # numeric | categorical
    in_model: bool | None = None
    encoding: str | None = None  # e.g. ordinal_1_7, target_encoder, one_hot

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("in_model") is None:
            d.pop("in_model", None)
        if d.get("encoding") is None:
            d.pop("encoding", None)
        for k in ("mean", "std", "min", "max", "p5", "p95"):
            v = d.get(k)
            if v is not None and isinstance(v, float) and not math.isfinite(v):
                d[k] = None
        return d


@dataclass
class PillarResult:
    pillar: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


@dataclass
class DQReport:
    gates_passed: bool
    pillar_results: list[PillarResult]
    feature_stats: dict[str, dict[str, Any]]
    n_rows_evaluated: int
    evaluated_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "gates_passed": self.gates_passed,
            "pillar_results": [
                {"pillar": p.pillar, "passed": p.passed, "checks": p.checks, "failures": p.failures}
                for p in self.pillar_results
            ],
            "feature_stats": self.feature_stats,
            "n_rows_evaluated": self.n_rows_evaluated,
            "evaluated_at": self.evaluated_at,
        }


AREA_COL_SUFFIXES = tuple(f"area_{cat}_{r}m" for cat in ("comm", "park", "sports", "health", "worship") for r in (500, 1000, 1500))


def _default_gates_dict() -> dict[str, Any]:
    return {
        "base": {
            "enabled": True,
            "min_rows": 5000,
            "target_null_rate_max": 0.01,
            "coord_null_rate_max": 0.05,
            "allow_nat_months": False,
        },
        "mrt": {
            "enabled": True,
            "snapshot_hit_rate_min": 0.85,
            "scalar_nullity_agreement_rate_min": 0.99,
            "line_connectivity_min_value": 1,
            "require_future_upside_variance": True,
            "speculative_score_max": 1.0,
            "speculative_score_min": 0.0,
            "check_project_completion_fraction_when_future_upside": True,
        },
        "macro": {
            "enabled": True,
            "interest_rate_min_nunique": 5,
            "volume_lagged_notna_rate_min": 0.9,
            "allow_all_zero_columns": False,
        },
        "poi": {
            "enabled": True,
            "school_dist_notna_rate_min": 0.95,
            "mall_dist_notna_rate_min": 0.95,
            "distances_must_be_positive": True,
            "require_gravity_variance": True,
        },
        "poi_amenity_v2": {
            "enabled": True,
            "hawker_dist_notna_rate_min": 0.95,
            "mall_count_1_5km_notna_rate_min": 0.95,
        },
        "masterplan": {
            "enabled": True,
            "nonzero_gpr_rate_min": 0.40,
            "nonzero_area_row_rate_min": 0.50,
            "dist_cbd_notna_rate_min": 0.95,
            "hub_score_finite_rate_min": 0.95,
        },
        "post_split": {"enabled": True, "min_test_rows": 500, "min_train_rows": 2000},
    }


_ENV_OVERRIDE_RE = re.compile(r"^HOMEYAI_DQ_([a-z]+)__(.+)$", re.I)


def load_quality_gates(project_root: Path) -> dict[str, Any]:
    """Load YAML (or HOMEYAI_DQ_CONFIG), merge defaults, apply HOMEYAI_DQ_<section>_<key> env."""

    gates = _default_gates_dict()
    yaml_path_env = os.environ.get("HOMEYAI_DQ_CONFIG", "").strip()
    if yaml_path_env:
        yp = Path(yaml_path_env).expanduser().resolve()
    else:
        yp = project_root.resolve() / "modelling" / "config" / "training_quality_gates.yml"

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        yaml = None  # type: ignore[assignment]

    if yaml is not None and yp.is_file():
        merged = yaml.safe_load(yp.read_text(encoding="utf-8"))
        if isinstance(merged, dict):
            for section, updates in merged.items():
                if section in gates and isinstance(updates, dict):
                    gates[section].update(updates)

    for k, raw in os.environ.items():
        m = _ENV_OVERRIDE_RE.match(k)
        if not m:
            continue
        sect, leaf_snake = m.group(1).lower(), m.group(2).lower()
        leaf = leaf_snake.replace("__", "_")
        if sect not in gates:
            continue
        v = raw.strip().lower()
        if v in ("true", "false"):
            gates[sect][leaf] = v == "true"
            continue
        try:
            gates[sect][leaf] = float(raw) if "." in raw else int(raw)
        except ValueError:
            gates[sect][leaf] = raw

    return gates


def engineer_preview_frame(exp, raw_df: pd.DataFrame, project_root: Path) -> pd.DataFrame:
    """Run feature-set engineer outside sklearn (for DQ on macro / POI / derived columns)."""
    fs = get_feature_set(project_root, exp.feature_set_id)
    kw: dict[str, Any] = {**fs.engineer_kwargs, **exp.extra_engineer_kwargs, "project_root": project_root}
    try:
        from modelling.training_db import get_training_database_url

        try:
            url = get_training_database_url()
        except Exception:
            url = os.environ.get("DATABASE_URL_READ_ONLY") or os.environ.get("DATABASE_URL")
        kw.setdefault("database_url", url)
        kw.setdefault("use_db", bool(url))
    except Exception:
        kw.setdefault("use_db", False)

    head_n = min(len(raw_df), 50_000)
    raw = raw_df.head(head_n).copy()
    return fs.engineer(raw)


def _compute_feature_stats(df: pd.DataFrame, *, max_cols: int | None = 80) -> dict[str, dict[str, Any]]:
    """Sample stats per column for report / diagnostics."""
    out: dict[str, dict[str, Any]] = {}
    cols = list(df.columns)
    if max_cols is not None:
        cols = cols[:max_cols]
    for c in cols:
        s = df[c]
        null_rate = float(s.isna().mean()) if len(s) else 0.0
        nuniq = int(s.nunique(dropna=True))
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            sn = pd.to_numeric(s, errors="coerce")
            stats = FeatureStats(null_rate=null_rate, nunique=nuniq, kind="numeric")
            vals = sn.dropna()
            if len(vals):
                stats.mean = float(vals.mean())
                stats.std = float(vals.std(ddof=0)) if len(vals) > 1 else 0.0
                stats.min = float(vals.min())
                stats.max = float(vals.max())
                stats.p5 = float(np.nanpercentile(vals.to_numpy(dtype=float), 5))
                stats.p95 = float(np.nanpercentile(vals.to_numpy(dtype=float), 95))
            out[c] = stats.as_dict()
        else:
            out[c] = FeatureStats(null_rate=null_rate, nunique=nuniq, kind="categorical").as_dict()
    return out


def compute_feature_stats_all_columns(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Per-column completeness / stats for every column in ``df`` (for transparency reports)."""
    return _compute_feature_stats(df, max_cols=None)


def merge_raw_and_engineered_feature_stats(
    raw_df: pd.DataFrame,
    engineered_df: pd.DataFrame,
    *,
    engineered_head_rows: int = 50_000,
) -> dict[str, dict[str, Any]]:
    """Full stats on raw columns plus engineered-only columns (same merge strategy as DQ gates)."""
    stats_raw = compute_feature_stats_all_columns(raw_df)
    eng_only = engineered_df.head(min(len(engineered_df), engineered_head_rows))
    eng_cols = [c for c in eng_only.columns if c not in stats_raw]
    extras = compute_feature_stats_all_columns(eng_only[eng_cols]) if eng_cols else {}
    merged = {**stats_raw, **extras}
    return finalize_feature_stats_for_model_report(merged)


def finalize_feature_stats_for_model_report(
    stats: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Align transparency stats with the trained design matrix.

    Raw ``flat_type`` (string, 7 levels) is not fed to the preprocessor after ordinal
    encoding; only ``flat_type_encoded`` is. Drop the raw column from pillar tables when
    the ordinal column is present so reports are not mistaken for one-hot inputs.
    """
    out = {k: dict(v) for k, v in stats.items() if isinstance(v, dict)}
    if "flat_type_encoded" in out:
        out.pop("flat_type", None)
        enc = out.setdefault("flat_type_encoded", {})
        enc["encoding"] = "ordinal_1_7"
        enc["in_model"] = True
    return out


def annotate_model_feature_stats(
    stats: dict[str, dict[str, Any]],
    *,
    numeric_features: list[str],
    categorical_features: list[str],
) -> dict[str, dict[str, Any]]:
    """Set ``in_model`` on each profiled column from the registered FeatureSet lists."""
    model_cols = frozenset(numeric_features) | frozenset(categorical_features)
    out: dict[str, dict[str, Any]] = {}
    for name, meta in stats.items():
        if not isinstance(meta, dict):
            continue
        row = dict(meta)
        if row.get("in_model") is None:
            row["in_model"] = name in model_cols
        out[name] = row
    return out


def _pillar_base(raw: pd.DataFrame, g: dict[str, Any]) -> PillarResult:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    passed = True
    n = len(raw)
    min_rows = int(g.get("min_rows", 5000))
    checks["min_rows"] = n >= min_rows
    if not checks["min_rows"]:
        failures.append(f"Too few rows: {n} < {min_rows}")
        passed = False

    if "resale_price" in raw.columns:
        null_rate = float(raw["resale_price"].isna().mean())
        cap = float(g.get("target_null_rate_max", 0.01))
        checks["target_null_rate_ok"] = null_rate <= cap
        if not checks["target_null_rate_ok"]:
            failures.append(f"resale_price null rate {null_rate:.3f} exceeds max {cap}")
            passed = False
    else:
        failures.append("resale_price column missing")
        passed = False

    allow_nat = bool(g.get("allow_nat_months", False))
    if "month" in raw.columns:
        mt = pd.to_datetime(raw["month"], format="%Y-%m", errors="coerce")
        nat_frac = float(mt.isna().mean())
        checks["month_parse_ok"] = allow_nat or nat_frac == 0.0
        if not checks["month_parse_ok"]:
            failures.append(f"month has NaT after parse ({100 * nat_frac:.2f}% of rows)")
            passed = False
    else:
        failures.append("month column missing")
        passed = False

    cap_c = float(g.get("coord_null_rate_max", 0.05))
    if {"lat", "lon"}.issubset(raw.columns):
        lat_null = float(raw["lat"].isna().mean())
        lon_null = float(raw["lon"].isna().mean())
        checks["coords_ok"] = lat_null <= cap_c and lon_null <= cap_c
        if not checks["coords_ok"]:
            failures.append(f"coordinates null lat={lat_null:.3f}, lon={lon_null:.3f} (max {cap_c})")
            passed = False
    else:
        checks["coords_ok"] = False
        failures.append("lat/lon columns missing from training frame")
        passed = False

    return PillarResult(pillar="base", passed=passed, checks=checks, failures=failures)


def _pillar_mrt(raw: pd.DataFrame, g: dict[str, Any]) -> PillarResult:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    passed = True
    if "dist_to_nearest_op_mrt" not in raw.columns:
        return PillarResult(pillar="mrt", passed=True, checks={"skipped_no_column": True}, failures=[])

    dist = pd.to_numeric(raw["dist_to_nearest_op_mrt"], errors="coerce")
    tt = raw.get("travel_time_to_active_mrt")
    if tt is not None:
        tt = pd.to_numeric(tt, errors="coerce")
    hit_rate = float(dist.notna().mean())
    hr_min = float(g.get("snapshot_hit_rate_min", 0.85))
    checks["snapshot_hit_rate_ok"] = hit_rate >= hr_min
    if not checks["snapshot_hit_rate_ok"]:
        failures.append(f"MRT snapshot hit rate {hit_rate:.3f} < {hr_min}")
        passed = False

    if tt is not None:
        agree = float((dist.isna() == tt.isna()).mean())
        agr_min = float(g.get("scalar_nullity_agreement_rate_min", 0.99))
        checks["dist_travel_agree"] = agree >= agr_min
        if not checks["dist_travel_agree"]:
            failures.append(f"dist vs travel_time nullity mismatch rate {agree:.4f}")
            passed = False

    if "line_connectivity_index" in raw.columns:
        lci = pd.to_numeric(raw["line_connectivity_index"], errors="coerce")
        sub = lci[lci.notna()]
        vmin = float(g.get("line_connectivity_min_value", 1))
        ok = True if len(sub) == 0 else bool((sub >= vmin).all())
        checks["line_connectivity_min"] = ok
        if not ok:
            failures.append(f"line_connectivity_index below {vmin} found")
            passed = False

    if bool(g.get("require_future_upside_variance", True)) and "days_to_mrt_opening" in raw.columns:
        dto = pd.to_numeric(raw["days_to_mrt_opening"], errors="coerce")
        if dto.notna().any() and "has_future_upside" in raw.columns:
            h = pd.to_numeric(raw["has_future_upside"], errors="coerce").fillna(0.0)
            var_ok = float(h.var()) > 0
            checks["future_upside_variance"] = var_ok
            if not var_ok:
                failures.append(
                    "has_future_upside has zero variance despite planned-opening rows (masked join?)"
                )
                passed = False

    if "speculative_upside_score" in raw.columns:
        s = pd.to_numeric(raw["speculative_upside_score"], errors="coerce")
        sub = s[s.notna()]
        lo = float(g.get("speculative_score_min", 0.0))
        hi = float(g.get("speculative_score_max", 1.0))
        rng_ok = bool(((sub > lo) & (sub < hi)).all()) if len(sub) else True
        checks["speculative_in_open_interval"] = rng_ok
        if not rng_ok:
            failures.append(f"speculative_upside_score not strictly in ({lo}, {hi})")
            passed = False

    if bool(g.get("check_project_completion_fraction_when_future_upside", True)) and "project_completion_fraction" in raw.columns:
        h = pd.to_numeric(raw["has_future_upside"], errors="coerce").fillna(0.0) == 1.0 if "has_future_upside" in raw.columns else pd.Series(False, index=raw.index)
        pcf = pd.to_numeric(raw["project_completion_fraction"], errors="coerce")
        sub = pcf[h]
        if len(sub):
            bounds_ok = sub.notna().all() and bool(((sub >= 0.0) & (sub <= 1.0)).all())
            checks["project_completion_fraction_bounded_when_future_upside"] = bounds_ok
            if not bounds_ok:
                failures.append(
                    "project_completion_fraction must be non-null and in [0, 1] when has_future_upside = 1"
                )
                passed = False
        else:
            checks["project_completion_fraction_bounded_when_future_upside"] = True

    return PillarResult(pillar="mrt", passed=passed, checks=checks, failures=failures)


def _pillar_masterplan(raw: pd.DataFrame, g: dict[str, Any]) -> PillarResult:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    passed = True
    gpr_col = "nearby_high_density_score"
    if gpr_col not in raw.columns:
        return PillarResult(pillar="masterplan", passed=True, checks={"skipped_no_column": True}, failures=[])

    gpr = pd.to_numeric(raw[gpr_col], errors="coerce").fillna(0.0)
    thresh = float(g.get("nonzero_gpr_rate_min", 0.4))
    rate = float((gpr > 0).mean())
    checks["nonzero_gpr_rate_ok"] = rate >= thresh
    if not checks["nonzero_gpr_rate_ok"]:
        failures.append(f"nearby_high_density_score > 0 rate {rate:.3f} < {thresh}")
        passed = False

    area_cols = [c for c in AREA_COL_SUFFIXES if c in raw.columns]
    if area_cols:
        mat = pd.DataFrame({c: pd.to_numeric(raw[c], errors="coerce").fillna(0.0) for c in area_cols})
        row_rates = float((mat.sum(axis=1) > 0).mean())
        t2 = float(g.get("nonzero_area_row_rate_min", 0.5))
        checks["nonzero_area_row_rate_ok"] = row_rates >= t2
        if not checks["nonzero_area_row_rate_ok"]:
            failures.append(f"rows with sum(area_*) > 0: {row_rates:.3f} < {t2}")
            passed = False

    if "dist_cbd" in raw.columns:
        d = pd.to_numeric(raw["dist_cbd"], errors="coerce")
        t_dc = float(g.get("dist_cbd_notna_rate_min", 0.95))
        checks["dist_cbd_notna_ok"] = float(d.notna().mean()) >= t_dc
        if not checks["dist_cbd_notna_ok"]:
            failures.append(f"dist_cbd non-null rate {float(d.notna().mean()):.3f} < {t_dc}")
            passed = False

    if "hub_score" in raw.columns:
        hs = pd.to_numeric(raw["hub_score"], errors="coerce")
        fin_arr = hs.to_numpy(dtype=float, copy=True)
        fin_arr = np.where(pd.isna(hs), False, np.isfinite(fin_arr))
        fin = fin_arr.astype(bool)
        t_h = float(g.get("hub_score_finite_rate_min", 0.95))
        checks["hub_score_finite_ok"] = float(fin.astype(float).mean()) >= t_h
        if not checks["hub_score_finite_ok"]:
            failures.append(f"hub_score finite rate {float(fin.astype(float).mean()):.3f} < {t_h}")
            passed = False

    return PillarResult(pillar="masterplan", passed=passed, checks=checks, failures=failures)


def _pillar_macro(engineered: pd.DataFrame, g: dict[str, Any]) -> PillarResult:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    passed = True
    need = {"volume_lagged_3m", "interest_rate_lagged"}
    if not need.issubset(engineered.columns):
        return PillarResult(pillar="macro", passed=True, checks={"skipped_no_macro_columns": True}, failures=[])

    vol = engineered["volume_lagged_3m"]
    vmin = float(g.get("volume_lagged_notna_rate_min", 0.9))
    checks["volume_notna_ok"] = float(vol.notna().mean()) >= vmin
    if not checks["volume_notna_ok"]:
        failures.append(f"volume_lagged_3m not-null rate {float(vol.notna().mean()):.3f}")
        passed = False

    col_ir = "interest_rate_lagged"
    nk_ir = int(g.get("interest_rate_min_nunique", 5))
    s = pd.to_numeric(engineered[col_ir], errors="coerce")
    nu = int(s.nunique(dropna=True))
    checks[f"{col_ir}_nunique_ok"] = nu >= nk_ir
    if not checks[f"{col_ir}_nunique_ok"]:
        failures.append(f"{col_ir} distinct values {nu} < {nk_ir}")
        passed = False

    allow_zero = bool(g.get("allow_all_zero_columns", False))
    if not allow_zero:
        col = "interest_rate_lagged"
        s2 = pd.to_numeric(engineered[col], errors="coerce")
        dr = s2.dropna()
        if len(dr):
            identical_zero = bool(np.all(np.isclose(dr.to_numpy(dtype=float), 0.0)))
            checks[f"{col}_not_identically_zero"] = not identical_zero
            if identical_zero:
                failures.append(f"{col} identically zero (macro fallback masking)")
                passed = False
    return PillarResult(pillar="macro", passed=passed, checks=checks, failures=failures)


def _pillar_poi(engineered: pd.DataFrame, g: dict[str, Any]) -> PillarResult:
    failures: list[str] = []
    checks: dict[str, bool] = {}
    passed = True

    schol = engineered.get("dist_nearest_top20_school")
    if schol is None and "dist_nearest_primary_school" in engineered.columns:
        schol = engineered["dist_nearest_primary_school"]
    if schol is None and "within_1km_top20_school" in engineered.columns:
        schol = engineered["within_1km_top20_school"]
    if schol is None and "count_top20_schools_within_1km" in engineered.columns:
        schol = engineered["count_top20_schools_within_1km"]
    mall_col = engineered.get("dist_nearest_mall")
    if schol is None and mall_col is None:
        return PillarResult(pillar="poi", passed=True, checks={"skipped_no_poi_columns": True}, failures=[])

    sr = float(g.get("school_dist_notna_rate_min", 0.95))
    mr = float(g.get("mall_dist_notna_rate_min", 0.95))
    must_pos = bool(g.get("distances_must_be_positive", True))
    if "dist_nearest_primary_school" in engineered.columns:
        school_col_name = "dist_nearest_primary_school"
    elif "dist_nearest_top20_school" in engineered.columns:
        school_col_name = "dist_nearest_top20_school"
    elif "within_1km_top20_school" in engineered.columns:
        school_col_name = "within_1km_top20_school"
    elif "count_top20_schools_within_1km" in engineered.columns:
        school_col_name = "count_top20_schools_within_1km"
    else:
        school_col_name = "school_signal"
    school_is_distance = school_col_name.startswith("dist_")

    if schol is not None:
        s = pd.to_numeric(schol, errors="coerce")
        checks["school_notna_ok"] = float(s.notna().mean()) >= sr
        if not checks["school_notna_ok"]:
            failures.append(f"{school_col_name} non-null rate {float(s.notna().mean()):.3f}")
            passed = False
        if must_pos and school_is_distance and s.dropna().any():
            pos = bool((s.dropna() > 0).all())
            checks["school_dist_positive"] = pos
            if not pos:
                failures.append(f"{school_col_name} contains non-positive values")
                passed = False

    if mall_col is not None:
        m = pd.to_numeric(mall_col, errors="coerce")
        checks["mall_notna_ok"] = float(m.notna().mean()) >= mr
        if not checks["mall_notna_ok"]:
            failures.append(f"dist_nearest_mall non-null rate {float(m.notna().mean()):.3f}")
            passed = False
        if must_pos and m.dropna().any():
            pos_m = bool((m.dropna() > 0).all())
            checks["mall_dist_positive"] = pos_m
            if not pos_m:
                failures.append("dist_nearest_mall contains non-positive values")
                passed = False

    if bool(g.get("require_gravity_variance", True)) and "gravity_malls" in engineered.columns:
        gm = pd.to_numeric(engineered["gravity_malls"], errors="coerce")
        v_ok = float(gm.var()) > 1e-12
        checks["gravity_malls_variance"] = v_ok
        if not v_ok:
            failures.append("gravity_malls has no variance")
            passed = False

    return PillarResult(pillar="poi", passed=passed, checks=checks, failures=failures)


def _pillar_poi_amenity_v2(engineered: pd.DataFrame, g: dict[str, Any]) -> PillarResult:
    """Extra gates for slim amenity pack (hawker + mall density columns)."""
    failures: list[str] = []
    checks: dict[str, bool] = {}
    passed = True
    need_any = ("dist_nearest_hawker", "hawker_count_within_1km", "mall_count_within_1_5km")
    if not any(c in engineered.columns for c in need_any):
        return PillarResult(
            pillar="poi_amenity_v2",
            passed=True,
            checks={"skipped_no_amenity_v2_columns": True},
            failures=[],
        )

    hk = engineered.get("dist_nearest_hawker")
    if hk is not None:
        h = pd.to_numeric(hk, errors="coerce")
        t_h = float(g.get("hawker_dist_notna_rate_min", 0.95))
        checks["hawker_dist_notna_ok"] = float(h.notna().mean()) >= t_h
        if not checks["hawker_dist_notna_ok"]:
            failures.append(f"dist_nearest_hawker non-null rate {float(h.notna().mean()):.3f} < {t_h}")
            passed = False

    mc = engineered.get("mall_count_within_1_5km")
    if mc is not None:
        m = pd.to_numeric(mc, errors="coerce")
        t_m = float(g.get("mall_count_1_5km_notna_rate_min", 0.95))
        checks["mall_count_15km_notna_ok"] = float(m.notna().mean()) >= t_m
        if not checks["mall_count_15km_notna_ok"]:
            failures.append(f"mall_count_within_1_5km non-null rate {float(m.notna().mean()):.3f} < {t_m}")
            passed = False

    return PillarResult(pillar="poi_amenity_v2", passed=passed, checks=checks, failures=failures)


def evaluate_data_quality_report(
    raw_df: pd.DataFrame,
    *,
    engineered_df: pd.DataFrame,
    project_root: Path,
) -> DQReport:
    """Run all enabled pillar checks."""
    gates = load_quality_gates(project_root)
    pillars: list[PillarResult] = []

    if gates["base"]["enabled"]:
        pillars.append(_pillar_base(raw_df, gates["base"]))
    if gates["mrt"]["enabled"]:
        pillars.append(_pillar_mrt(raw_df, gates["mrt"]))
    if gates["masterplan"]["enabled"]:
        pillars.append(_pillar_masterplan(raw_df, gates["masterplan"]))
    if gates["macro"]["enabled"]:
        pillars.append(_pillar_macro(engineered_df, gates["macro"]))
    if gates["poi"]["enabled"]:
        pillars.append(_pillar_poi(engineered_df, gates["poi"]))
    pa = gates.get("poi_amenity_v2") or {}
    if bool(pa.get("enabled", False)):
        pillars.append(_pillar_poi_amenity_v2(engineered_df, pa))

    stats_raw = _compute_feature_stats(raw_df)
    # Merge engineered-specific columns not overlapping (macro/poi extras)
    eng_only = engineered_df.head(min(len(engineered_df), 50_000))
    eng_cols = [c for c in eng_only.columns if c not in stats_raw][:40]
    extras = _compute_feature_stats(eng_only[eng_cols]) if eng_cols else {}
    feature_stats = {**stats_raw, **extras}

    all_pass = all(p.passed for p in pillars)

    return DQReport(
        gates_passed=all_pass,
        pillar_results=pillars,
        feature_stats=feature_stats,
        n_rows_evaluated=len(raw_df),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )


def append_post_split_to_quality_summary(
    summary: dict[str, Any],
    *,
    n_train: int,
    n_test: int,
    project_root: Path,
) -> dict[str, Any]:
    """Append ``post_split`` pillar to serialized DQ summary before writing metrics.json."""
    out = dict(summary)
    gates = load_quality_gates(project_root)["post_split"]
    if not gates["enabled"]:
        return out

    nt = int(gates["min_test_rows"])
    ntr = int(gates["min_train_rows"])
    checks = {"test_rows_ok": n_test >= nt, "train_rows_ok": n_train >= ntr}
    failures: list[str] = []
    ok = checks["train_rows_ok"] and checks["test_rows_ok"]
    if not checks["train_rows_ok"]:
        failures.append(f"n_train={n_train} < {ntr}")
    if not checks["test_rows_ok"]:
        failures.append(f"n_test={n_test} < {nt}")

    pillar = {"pillar": "post_split", "passed": ok, "checks": checks, "failures": failures}
    pr = list(out.get("pillar_results", []))
    pr.append(pillar)
    out["pillar_results"] = pr
    out["gates_passed"] = bool(out.get("gates_passed", False)) and ok
    out["post_split_checks"] = {
        "n_train": int(n_train),
        "n_test": int(n_test),
    }
    return out


def assert_training_frame_ready(
    raw_df: pd.DataFrame,
    *,
    engineered_df: pd.DataFrame,
    experiment_id: str,
    feature_set_id: str,
    project_root: Path,
) -> DQReport:
    """Evaluate gates; raises DataQualityError on first pillar failure."""

    dq = evaluate_data_quality_report(
        raw_df, engineered_df=engineered_df, project_root=project_root
    )
    if dq.gates_passed:
        return dq

    lines = [f"Data quality gates failed ({experiment_id} / {feature_set_id})"]
    for p in dq.pillar_results:
        if not p.passed:
            lines.append(f"  [{p.pillar}] FAILED: " + "; ".join(p.failures))

    raise DataQualityError("\n".join(lines))
