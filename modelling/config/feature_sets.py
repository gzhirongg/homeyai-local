"""Registered feature sets: name → engineering function + column lists."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from modelling.features.base import base_categorical_columns, base_numeric_columns, engineer_base_features
from modelling.features.estate_maturity import (
    ESTATE_MATURITY_NUMERIC_FEATURES,
    engineer_estate_maturity_bundle,
)
from modelling.features.macro_sentiment import MACRO_NUMERIC_FEATURES, engineer_macro_frame
from modelling.features.masterplan_landuse_pit import (
    MASTERPLAN_AREA_NUMERIC,
    MASTERPLAN_LAND_USE_NUMERIC,
    MASTERPLAN_PROXIMITY_NUMERIC,
    engineer_macro_masterplan_landuse_pit_frame,
    engineer_masterplan_landuse_pit_only,
    engineer_mrt_macro_masterplan_frame,
)
from modelling.features.mrt_pit import engineer_mrt_pit_frame, mrt_numeric_feature_names
from modelling.features.primary_school import (
    PRIMARY_SCHOOL_NUMERIC,
    engineer_mrt_landuse_primary_school_frame,
    engineer_primary_school_frame,
)
from modelling.features.poi_amenity_v2 import POI_AMENITY_V2_NUMERIC_FEATURES, engineer_poi_amenity_v2_frame
from modelling.features.poi_distancing import (
    POI_NUMERIC_FEATURES,
    engineer_poi_frame,
    load_poi_tables,
    load_poi_tables_from_db,
)

_BASELINE_NUMERIC_EXCLUDED_FOR_CORE35_STACK: frozenset[str] = frozenset({"sale_year"})


class _LazyPoiKwargs(dict[str, Any]):
    """Resolves POI source (files vs DB) on first access, not at registry build time."""

    def __init__(self, project_root: Path, *, include_macro: bool) -> None:
        super().__init__()
        self._root = project_root
        self._include_macro = include_macro
        self._resolved = False

    def _resolve(self) -> None:
        if not self._resolved:
            self._resolved = True
            self.update(_resolve_poi_engineer_kwargs(self._root, include_macro=self._include_macro))

    def __getitem__(self, key):  # type: ignore[override]
        self._resolve()
        return super().__getitem__(key)

    def __contains__(self, key):  # type: ignore[override]
        self._resolve()
        return super().__contains__(key)

    def __iter__(self):  # type: ignore[override]
        self._resolve()
        return super().__iter__()

    def __len__(self) -> int:  # type: ignore[override]
        self._resolve()
        return super().__len__()

    def items(self):  # type: ignore[override]
        self._resolve()
        return super().items()

    def keys(self):  # type: ignore[override]
        self._resolve()
        return super().keys()

    def values(self):  # type: ignore[override]
        self._resolve()
        return super().values()

    def get(self, key, default=None):  # type: ignore[override]
        self._resolve()
        return super().get(key, default)


class _LazyCore35L40StackKwargs(_LazyPoiKwargs):
    """POI sourcing for Macro + DB URL, plus optional block coord merge pin (parity with CUDA full_stack runs)."""

    def _resolve(self) -> None:
        super()._resolve()
        coords = self._root / "data" / "pois" / "hdb_block_coords.csv"
        if coords.is_file():
            dict.__setitem__(self, "merge_coords_csv", str(coords))


def _resolve_poi_engineer_kwargs(project_root: Path, *, include_macro: bool) -> dict[str, Any]:
    """Use ``data/pois`` CSV/GeoJSON when present; else read ``poi_locations`` via training DB URL."""
    from modelling.features.poi_distancing import POI_FILENAMES, pois_dir

    base = pois_dir(project_root.resolve())
    has_files = all((base / fname).is_file() for fname in POI_FILENAMES.values())
    kw: dict[str, Any] = {"include_macro": include_macro}
    if has_files:
        return kw
    from modelling.training_db import get_training_database_url

    kw["use_db"] = True
    kw["database_url"] = get_training_database_url()
    return kw


def _dedupe_nums(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


@dataclass(frozen=False)
class FeatureSet:
    """Describes one reusable bundle of engineered columns."""

    id: str
    description: str
    categorical_features: list[str]
    numeric_features: list[str]
    engineer: Callable[..., pd.DataFrame]
    engineer_kwargs: dict[str, Any]


def _eng_baseline(raw: pd.DataFrame, **_kwargs: Any) -> pd.DataFrame:
    return engineer_base_features(
        raw,
        categorical_style="legacy",
        include_months_since_2015=bool(_kwargs.get("include_months_since_2015")),
    )


def _eng_grouped(raw: pd.DataFrame, **_kwargs: Any) -> pd.DataFrame:
    return engineer_base_features(
        raw,
        categorical_style="grouped",
        include_months_since_2015=bool(_kwargs.get("include_months_since_2015")),
    )


def _eng_macro(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.base import repo_root

    kw = dict(kwargs)
    root = kw.pop("project_root", None) or repo_root()
    return engineer_macro_frame(raw, categorical_style="legacy", project_root=root, **kw)


def _eng_mrt_pit(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.base import repo_root

    kw = dict(kwargs)
    root = kw.pop("project_root", None) or repo_root()
    return engineer_mrt_pit_frame(raw, categorical_style="legacy", project_root=root, **kw)


def _eng_landuse(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.base import repo_root

    kw = dict(kwargs)
    root = kw.pop("project_root", None) or repo_root()
    return engineer_masterplan_landuse_pit_only(raw, categorical_style="legacy", project_root=root, **kw)


def _eng_macro_landuse(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.base import repo_root

    kw = dict(kwargs)
    root = kw.pop("project_root", None) or repo_root()
    return engineer_macro_masterplan_landuse_pit_frame(
        raw, categorical_style="legacy", project_root=root, **kw
    )


def _eng_macro_landuse_mrt(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.base import repo_root

    kw = dict(kwargs)
    root = kw.pop("project_root", None) or repo_root()
    return engineer_mrt_macro_masterplan_frame(raw, categorical_style="legacy", project_root=root, **kw)


def _eng_poi(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    merge_coords = kwargs.get("merge_coords_csv")
    path = Path(merge_coords) if merge_coords else None
    return engineer_poi_frame(
        raw,
        merge_coords_csv=path,
        include_mrt=False,
        categorical_style="legacy",
        project_root=kwargs.get("project_root"),
        use_db=bool(kwargs.get("use_db")),
        database_url=kwargs.get("database_url"),
        gravity_weights=kwargs.get("gravity_weights"),
        include_macro=bool(kwargs.get("include_macro")),
    )


def _eng_poi_amenity_v2(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    merge_coords = kwargs.get("merge_coords_csv")
    path = Path(merge_coords) if merge_coords else None
    forbidden = frozenset(
        {
            "merge_coords_csv",
            "include_mrt",
            "categorical_style",
            "project_root",
            "use_db",
            "database_url",
            "prefer_hdb_poi_features",
        }
    )
    kw_rest = {k: v for k, v in kwargs.items() if k not in forbidden}
    return engineer_poi_amenity_v2_frame(
        raw,
        merge_coords_csv=path,
        include_mrt=False,
        categorical_style="legacy",
        project_root=kwargs.get("project_root"),
        use_db=bool(kwargs.get("use_db")),
        database_url=kwargs.get("database_url"),
        prefer_hdb_poi_features=bool(kwargs.get("prefer_hdb_poi_features", True)),
        **kw_rest,
    )


def _eng_primary_school(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    merge_coords = kwargs.get("merge_coords_csv")
    path = Path(merge_coords) if merge_coords else None
    forbidden = frozenset(
        {
            "merge_coords_csv",
            "include_mrt",
            "categorical_style",
            "project_root",
            "use_db",
            "database_url",
            "prefer_hdb_poi_features",
        }
    )
    kw_rest = {k: v for k, v in kwargs.items() if k not in forbidden}
    return engineer_primary_school_frame(
        raw,
        merge_coords_csv=path,
        include_mrt=False,
        categorical_style="legacy",
        project_root=kwargs.get("project_root"),
        use_db=bool(kwargs.get("use_db")),
        database_url=kwargs.get("database_url"),
        **kw_rest,
    )


def _eng_mrt_landuse_primary_school(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    merge_coords = kwargs.get("merge_coords_csv")
    path = Path(merge_coords) if merge_coords else None
    forbidden = frozenset(
        {
            "merge_coords_csv",
            "include_mrt",
            "categorical_style",
            "project_root",
            "use_db",
            "database_url",
            "prefer_hdb_poi_features",
        }
    )
    kw_rest = {k: v for k, v in kwargs.items() if k not in forbidden}
    return engineer_mrt_landuse_primary_school_frame(
        raw,
        merge_coords_csv=path,
        categorical_style="legacy",
        project_root=kwargs.get("project_root"),
        use_db=bool(kwargs.get("use_db")),
        database_url=kwargs.get("database_url"),
        **kw_rest,
    )


def _eng_mrt_landuse_primary_school_estate(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    base = _eng_mrt_landuse_primary_school(raw, **kwargs)
    return engineer_estate_maturity_bundle(base, raw)


def _eng_mrt_primary_school(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    merge_coords = kwargs.get("merge_coords_csv")
    path = Path(merge_coords) if merge_coords else None
    forbidden = frozenset(
        {
            "merge_coords_csv",
            "include_mrt",
            "categorical_style",
            "project_root",
            "use_db",
            "database_url",
            "prefer_hdb_poi_features",
        }
    )
    kw_rest = {k: v for k, v in kwargs.items() if k not in forbidden}
    return engineer_primary_school_frame(
        raw,
        merge_coords_csv=path,
        include_mrt=True,
        categorical_style="legacy",
        project_root=kwargs.get("project_root"),
        use_db=bool(kwargs.get("use_db")),
        database_url=kwargs.get("database_url"),
        **kw_rest,
    )


def _eng_mrt_primary_school_estate(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    base = _eng_mrt_primary_school(raw, **kwargs)
    return engineer_estate_maturity_bundle(base, raw)


def _eng_mrt_poi_amenity_v2(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    merge_coords = kwargs.get("merge_coords_csv")
    path = Path(merge_coords) if merge_coords else None
    forbidden = frozenset(
        {
            "merge_coords_csv",
            "include_mrt",
            "categorical_style",
            "project_root",
            "use_db",
            "database_url",
            "prefer_hdb_poi_features",
        }
    )
    kw_rest = {k: v for k, v in kwargs.items() if k not in forbidden}
    return engineer_poi_amenity_v2_frame(
        raw,
        merge_coords_csv=path,
        include_mrt=True,
        categorical_style="legacy",
        project_root=kwargs.get("project_root"),
        use_db=bool(kwargs.get("use_db")),
        database_url=kwargs.get("database_url"),
        prefer_hdb_poi_features=bool(kwargs.get("prefer_hdb_poi_features", True)),
        **kw_rest,
    )


def _eng_mrt_poi(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    merge_coords = kwargs.get("merge_coords_csv")
    path = Path(merge_coords) if merge_coords else None
    forbidden = frozenset(
        {
            "merge_coords_csv",
            "include_mrt",
            "categorical_style",
            "project_root",
            "use_db",
            "database_url",
            "gravity_weights",
            "include_macro",
        }
    )
    kw_rest = {k: v for k, v in kwargs.items() if k not in forbidden}
    return engineer_poi_frame(
        raw,
        merge_coords_csv=path,
        include_mrt=True,
        categorical_style="legacy",
        project_root=kwargs.get("project_root"),
        use_db=bool(kwargs.get("use_db")),
        database_url=kwargs.get("database_url"),
        gravity_weights=kwargs.get("gravity_weights"),
        include_macro=bool(kwargs.get("include_macro")),
        **kw_rest,
    )


def _eng_mrt_poi_grouped(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    merge_coords = kwargs.get("merge_coords_csv")
    path = Path(merge_coords) if merge_coords else None
    forbidden = frozenset(
        {
            "merge_coords_csv",
            "include_mrt",
            "categorical_style",
            "project_root",
            "use_db",
            "database_url",
            "gravity_weights",
            "include_macro",
        }
    )
    kw_rest = {k: v for k, v in kwargs.items() if k not in forbidden}
    return engineer_poi_frame(
        raw,
        merge_coords_csv=path,
        include_mrt=True,
        categorical_style="grouped",
        project_root=kwargs.get("project_root"),
        use_db=bool(kwargs.get("use_db")),
        database_url=kwargs.get("database_url"),
        gravity_weights=kwargs.get("gravity_weights"),
        include_macro=bool(kwargs.get("include_macro")),
        **kw_rest,
    )


def _eng_all_features(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.masterplan_landuse_pit import append_masterplan_landuse_from_raw_columns

    kw_mrt = dict(kwargs)
    kw_mrt.setdefault("include_macro", True)
    out = _eng_mrt_poi(raw, **kw_mrt)
    return append_masterplan_landuse_from_raw_columns(out, raw, require_columns=False)


def _eng_all_features_grouped(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.masterplan_landuse_pit import append_masterplan_landuse_from_raw_columns

    kw_mrt = dict(kwargs)
    kw_mrt.setdefault("include_macro", True)
    out = _eng_mrt_poi_grouped(raw, **kw_mrt)
    return append_masterplan_landuse_from_raw_columns(out, raw, require_columns=False)


def _eng_mrt_macro_proximity_primary_school_estate(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    """MRT + macro + masterplan snapshot + school counts + estate (no POI distance numerics in contract)."""
    from modelling.features.base import repo_root
    from modelling.features.masterplan_landuse_pit import append_masterplan_landuse_from_raw_columns
    from modelling.features.primary_school import append_primary_school_features
    from modelling.features.poi_distancing import _ensure_lat_lon, _log_lat_lon_coverage, merge_block_coordinates

    merge_coords = kwargs.get("merge_coords_csv")
    path = Path(merge_coords) if merge_coords else None

    frame = raw.copy()
    n_before = len(frame)
    if path is not None:
        frame = merge_block_coordinates(frame, path)
    _ensure_lat_lon(frame)
    frame = frame.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    _log_lat_lon_coverage(n_before, len(frame))
    if frame.empty:
        raise ValueError(
            "No rows left after dropping missing lat/lon — cannot engineer "
            "mrt_macro_proximity_primary_school_estate."
        )

    out = _eng_mrt_pit_macro(frame, **kwargs)
    out = append_masterplan_landuse_from_raw_columns(out, frame, require_columns=False)

    root = kwargs.get("project_root") or repo_root()
    use_db = bool(kwargs.get("use_db"))
    database_url = kwargs.get("database_url")
    if use_db:
        if not database_url or not str(database_url).strip():
            raise ValueError(
                "_eng_mrt_macro_proximity_primary_school_estate(..., use_db=True) requires database_url."
            )
        pois = load_poi_tables_from_db(str(database_url).strip())
    else:
        pois = load_poi_tables(root)

    out = append_primary_school_features(out, pois)
    return engineer_estate_maturity_bundle(out, frame)


def _baseline_nums(*, grouped: bool, months2015: bool) -> tuple[list[str], list[str]]:
    style = "grouped" if grouped else "legacy"
    nums = base_numeric_columns(style, include_months_since_2015=months2015)
    cats = base_categorical_columns(style)
    return list(nums), list(cats)


def _baseline_nums_without_columns(
    *,
    grouped: bool,
    months2015: bool,
    exclude: frozenset[str],
) -> tuple[list[str], list[str]]:
    nums, cats = _baseline_nums(grouped=grouped, months2015=months2015)
    return [c for c in nums if c not in exclude], cats


def _eng_mrt_pit_macro(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.base import repo_root
    from modelling.features.macro_sentiment import append_macro_features

    kw = dict(kwargs)
    root = kw.pop("project_root", None) or repo_root()
    base = engineer_mrt_pit_frame(raw, categorical_style="legacy", project_root=root, **kw)
    return append_macro_features(base, raw, project_root=root)


def _eng_baseline_estate(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    base = engineer_base_features(
        raw,
        categorical_style="legacy",
        include_months_since_2015=bool(kwargs.get("include_months_since_2015")),
    )
    return engineer_estate_maturity_bundle(base, raw)


def _eng_macro_estate(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.base import repo_root

    kw = dict(kwargs)
    root = kw.pop("project_root", None) or repo_root()
    base = engineer_macro_frame(raw, categorical_style="legacy", project_root=root, **kw)
    return engineer_estate_maturity_bundle(base, raw)


def _eng_macro_landuse_mrt_estate(raw: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    from modelling.features.base import repo_root

    kw = dict(kwargs)
    root = kw.pop("project_root", None) or repo_root()
    base = engineer_mrt_macro_masterplan_frame(raw, categorical_style="legacy", project_root=root, **kw)
    return engineer_estate_maturity_bundle(base, raw)


def build_feature_set_registry(root: Path) -> dict[str, FeatureSet]:
    """Instantiate feature lists that depend on MRT line vocabulary size."""
    num_b, cat_b = _baseline_nums(grouped=False, months2015=False)
    num_bench, cat_bench = _baseline_nums(grouped=False, months2015=True)
    num_bg, cat_bg = _baseline_nums(grouped=True, months2015=False)

    mrt_extra = mrt_numeric_feature_names(root)
    num_mrt = num_b + mrt_extra
    num_macro = num_b + MACRO_NUMERIC_FEATURES
    num_mrt_macro = num_mrt + MACRO_NUMERIC_FEATURES
    num_poi = num_b + POI_NUMERIC_FEATURES
    num_macro_poi = _dedupe_nums(num_b + MACRO_NUMERIC_FEATURES + POI_NUMERIC_FEATURES)
    num_mrt_poi = num_mrt + POI_NUMERIC_FEATURES
    num_mrt_macro_poi = _dedupe_nums(num_mrt_macro + POI_NUMERIC_FEATURES)
    num_land = num_b + MASTERPLAN_LAND_USE_NUMERIC
    num_macro_land = _dedupe_nums(num_b + MACRO_NUMERIC_FEATURES + MASTERPLAN_LAND_USE_NUMERIC)
    num_macro_land_mrt = _dedupe_nums(num_macro_land + mrt_extra)
    num_estate = _dedupe_nums(num_b + ESTATE_MATURITY_NUMERIC_FEATURES)
    num_macro_estate = _dedupe_nums(num_macro + ESTATE_MATURITY_NUMERIC_FEATURES)
    num_macro_land_mrt_estate = _dedupe_nums(num_macro_land_mrt + ESTATE_MATURITY_NUMERIC_FEATURES)
    num_mrt_macro_poi_g = _dedupe_nums(num_bg + mrt_extra + MACRO_NUMERIC_FEATURES + POI_NUMERIC_FEATURES)
    num_amenity_v2 = num_b + POI_AMENITY_V2_NUMERIC_FEATURES
    num_mrt_amenity_v2 = num_mrt + POI_AMENITY_V2_NUMERIC_FEATURES
    num_primary_school = num_b + PRIMARY_SCHOOL_NUMERIC
    num_mrt_primary_school = num_mrt + PRIMARY_SCHOOL_NUMERIC
    num_mrt_primary_school_estate = _dedupe_nums(num_mrt_primary_school + ESTATE_MATURITY_NUMERIC_FEATURES)
    num_mrt_landuse_primary_school = _dedupe_nums(
        num_mrt + MASTERPLAN_LAND_USE_NUMERIC + PRIMARY_SCHOOL_NUMERIC
    )
    num_mrt_masterplan_area_primary_school = _dedupe_nums(num_mrt + MASTERPLAN_AREA_NUMERIC + PRIMARY_SCHOOL_NUMERIC)
    num_mrt_masterplan_proximity_primary_school = _dedupe_nums(
        num_mrt + MASTERPLAN_PROXIMITY_NUMERIC + PRIMARY_SCHOOL_NUMERIC
    )
    num_mrt_masterplan_area_proximity_primary_school = num_mrt_landuse_primary_school
    num_mrt_landuse_primary_school_estate = _dedupe_nums(
        num_mrt_landuse_primary_school + ESTATE_MATURITY_NUMERIC_FEATURES
    )
    num_mrt_masterplan_area_primary_school_estate = _dedupe_nums(
        num_mrt_masterplan_area_primary_school + ESTATE_MATURITY_NUMERIC_FEATURES
    )
    num_mrt_masterplan_proximity_primary_school_estate = _dedupe_nums(
        num_mrt_masterplan_proximity_primary_school + ESTATE_MATURITY_NUMERIC_FEATURES
    )
    num_all = _dedupe_nums(num_mrt_macro_poi + MASTERPLAN_LAND_USE_NUMERIC)
    num_all_g = _dedupe_nums(num_mrt_macro_poi_g + MASTERPLAN_LAND_USE_NUMERIC)

    num_b_core35, cat_b_core35 = _baseline_nums_without_columns(
        grouped=False,
        months2015=False,
        exclude=_BASELINE_NUMERIC_EXCLUDED_FOR_CORE35_STACK,
    )
    num_mrt_core35 = num_b_core35 + mrt_extra
    num_core35_macro_proximity_estate_school = _dedupe_nums(
        num_mrt_core35
        + MACRO_NUMERIC_FEATURES
        + MASTERPLAN_PROXIMITY_NUMERIC
        + PRIMARY_SCHOOL_NUMERIC
        + ESTATE_MATURITY_NUMERIC_FEATURES
    )

    return {
        "baseline_v1": FeatureSet(
            id="baseline_v1",
            description=(
                "Core HDB structured features without transport or POI packs "
                "(includes block WGS84 lat/lon as numerics)."
            ),
            categorical_features=cat_b,
            numeric_features=num_b,
            engineer=_eng_baseline,
            engineer_kwargs={},
        ),
        "baseline_v1__months_since_2015": FeatureSet(
            id="baseline_v1__months_since_2015",
            description="baseline_v1 + months_since_2015 (benchmark parity with reference slice tooling).",
            categorical_features=cat_b,
            numeric_features=num_bench,
            engineer=_eng_baseline,
            engineer_kwargs={"include_months_since_2015": True},
        ),
        "baseline_grouped_v1": FeatureSet(
            id="baseline_grouped_v1",
            description="Grouped flat_model + coarse region (reference-style categorical split).",
            categorical_features=cat_bg,
            numeric_features=num_bg,
            engineer=_eng_grouped,
            engineer_kwargs={},
        ),
        "baseline_v1__macro": FeatureSet(
            id="baseline_v1__macro",
            description=(
                "Baseline + resale volume lag + lagged blended rates "
                "(HDB RPI used for target normalization only, not model inputs)."
            ),
            categorical_features=cat_b,
            numeric_features=num_macro,
            engineer=_eng_macro,
            engineer_kwargs={},
        ),
        "mrt_pit__macro": FeatureSet(
            id="mrt_pit__macro",
            description="MRT PIT + macro sentiment numerics.",
            categorical_features=cat_b,
            numeric_features=num_mrt_macro,
            engineer=_eng_mrt_pit_macro,
            engineer_kwargs={},
        ),
        "masterplan_landuse_pit": FeatureSet(
            id="masterplan_landuse_pit",
            description="Baseline + GPR/amenity polygons (PIT via snapshot merge before training).",
            categorical_features=cat_b,
            numeric_features=num_land,
            engineer=_eng_landuse,
            engineer_kwargs={},
        ),
        "baseline_v1__macro__masterplan_landuse_pit": FeatureSet(
            id="baseline_v1__macro__masterplan_landuse_pit",
            description="Macro + Land Use polygons (snapshot + MinIO PIT-aware revision choice).",
            categorical_features=cat_b,
            numeric_features=num_macro_land,
            engineer=_eng_macro_landuse,
            engineer_kwargs={},
        ),
        "baseline_v1__macro__masterplan_landuse_pit__mrt_pit": FeatureSet(
            id="baseline_v1__macro__masterplan_landuse_pit__mrt_pit",
            description="Full stack: baseline + macro + Land Use polygon scalars + MRT PIT.",
            categorical_features=cat_b,
            numeric_features=num_macro_land_mrt,
            engineer=_eng_macro_landuse_mrt,
            engineer_kwargs={},
        ),
        "baseline_v1__estate_maturity": FeatureSet(
            id="baseline_v1__estate_maturity",
            description="Baseline + harmonised estate maturity aggregates (town × month from DB merge).",
            categorical_features=cat_b,
            numeric_features=num_estate,
            engineer=_eng_baseline_estate,
            engineer_kwargs={},
        ),
        "baseline_v1__macro__estate_maturity": FeatureSet(
            id="baseline_v1__macro__estate_maturity",
            description="Macro sentiment + estate maturity aggregates (tier-1 completions FY + catalogue stock).",
            categorical_features=cat_b,
            numeric_features=num_macro_estate,
            engineer=_eng_macro_estate,
            engineer_kwargs={},
        ),
        "baseline_v1__macro__masterplan_landuse_pit__mrt_pit__estate_maturity": FeatureSet(
            id="baseline_v1__macro__masterplan_landuse_pit__mrt_pit__estate_maturity",
            description=(
                "Full stack + estate maturity panel (dwellings UC/lag completions, densities, ratios)."
            ),
            categorical_features=cat_b,
            numeric_features=num_macro_land_mrt_estate,
            engineer=_eng_macro_landuse_mrt_estate,
            engineer_kwargs={},
        ),
        "mrt_pit": FeatureSet(
            id="mrt_pit",
            description="Baseline (+ WGS84 lat/lon numerics) + point-in-time MRT accessibility/speculation pack.",
            categorical_features=cat_b,
            numeric_features=num_mrt,
            engineer=_eng_mrt_pit,
            engineer_kwargs={},
        ),
        "poi_distancing": FeatureSet(
            id="poi_distancing",
            description="Baseline (+ lat/lon) + school/mall/park/amenity distances (raw lat/lon required for POI engineering).",
            categorical_features=cat_b,
            numeric_features=num_poi,
            engineer=_eng_poi,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__poi_distancing": FeatureSet(
            id="mrt_pit__poi_distancing",
            description="Full Colab-style stack: baseline + MRT PIT + POI distances.",
            categorical_features=cat_b,
            numeric_features=num_mrt_poi,
            engineer=_eng_mrt_poi,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "poi_amenity_v2": FeatureSet(
            id="poi_amenity_v2",
            description=(
                "Baseline + slim POI pack (primary school / hawker / mall only). "
                "When training from DB, blends school and mall distances from hdb_poi_features when present."
            ),
            categorical_features=cat_b,
            numeric_features=num_amenity_v2,
            engineer=_eng_poi_amenity_v2,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__poi_amenity_v2": FeatureSet(
            id="mrt_pit__poi_amenity_v2",
            description="Baseline + MRT PIT + slim POI amenity pack (school / hawker / mall).",
            categorical_features=cat_b,
            numeric_features=num_mrt_amenity_v2,
            engineer=_eng_mrt_poi_amenity_v2,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "primary_school": FeatureSet(
            id="primary_school",
            description=(
                "Baseline + top-20 primary school counts in [0, 1 km] and (1 km, 2 km] annuli "
                "(count_top20_schools_within_1km, count_top20_schools_within_1km_2km; no distance column). "
                "Counts are always computed from POI points, not from hdb_poi_features."
            ),
            categorical_features=cat_b,
            numeric_features=num_primary_school,
            engineer=_eng_primary_school,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__primary_school": FeatureSet(
            id="mrt_pit__primary_school",
            description="Baseline + MRT PIT + top-20 school counts (two annulus columns only).",
            categorical_features=cat_b,
            numeric_features=num_mrt_primary_school,
            engineer=_eng_mrt_primary_school,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__primary_school__estate_maturity": FeatureSet(
            id="mrt_pit__primary_school__estate_maturity",
            description=(
                "Baseline + MRT PIT + top-20 school counts + estate maturity (no masterplan, no macro)."
            ),
            categorical_features=cat_b,
            numeric_features=num_mrt_primary_school_estate,
            engineer=_eng_mrt_primary_school_estate,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__masterplan_landuse_pit__primary_school": FeatureSet(
            id="mrt_pit__masterplan_landuse_pit__primary_school",
            description=(
                "Baseline + MRT PIT + masterplan land-use PIT + top-20 school counts "
                "(no macro sentiment). Same engineer as split packs; numeric list is full masterplan "
                "(area intersection columns + proximity/scalars incl. B2/business-park distances). "
                "Prefer `mrt_pit__masterplan_area_proximity__primary_school` for explicit naming."
            ),
            categorical_features=cat_b,
            numeric_features=num_mrt_landuse_primary_school,
            engineer=_eng_mrt_landuse_primary_school,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__masterplan_area__primary_school": FeatureSet(
            id="mrt_pit__masterplan_area__primary_school",
            description=(
                "Pack 1 only: polygon intersection areas (comm/park/sports/health/worship × 500/1000/1500 m), "
                "+ MRT + primary-school counts. Engineer still attaches full snapshot columns; model uses area list only."
            ),
            categorical_features=cat_b,
            numeric_features=num_mrt_masterplan_area_primary_school,
            engineer=_eng_mrt_landuse_primary_school,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__masterplan_proximity__primary_school": FeatureSet(
            id="mrt_pit__masterplan_proximity__primary_school",
            description=(
                "Pack 2 only: GPR mean, dist_cbd/dist_airport, derived hub/density_age, "
                "LOI proximity (B2/BP/cemetery/special-use distances + b2_zoning_ratio_1km), "
                "+ MRT + primary-school counts."
            ),
            categorical_features=cat_b,
            numeric_features=num_mrt_masterplan_proximity_primary_school,
            engineer=_eng_mrt_landuse_primary_school,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__masterplan_area_proximity__primary_school": FeatureSet(
            id="mrt_pit__masterplan_area_proximity__primary_school",
            description=(
                "Both masterplan packs (area + proximity/scalars); alias numerics to full `MASTERPLAN_LAND_USE_NUMERIC`."
            ),
            categorical_features=cat_b,
            numeric_features=num_mrt_masterplan_area_proximity_primary_school,
            engineer=_eng_mrt_landuse_primary_school,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__masterplan_area__primary_school__estate_maturity": FeatureSet(
            id="mrt_pit__masterplan_area__primary_school__estate_maturity",
            description="Pack 1 (area intersections) + estate maturity + MRT + primary-school counts.",
            categorical_features=cat_b,
            numeric_features=num_mrt_masterplan_area_primary_school_estate,
            engineer=_eng_mrt_landuse_primary_school_estate,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__masterplan_proximity__primary_school__estate_maturity": FeatureSet(
            id="mrt_pit__masterplan_proximity__primary_school__estate_maturity",
            description="Pack 2 (proximity/scalars incl. B2/BP) + estate maturity + MRT + primary-school counts.",
            categorical_features=cat_b,
            numeric_features=num_mrt_masterplan_proximity_primary_school_estate,
            engineer=_eng_mrt_landuse_primary_school_estate,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "mrt_pit__masterplan_landuse_pit__primary_school__estate_maturity": FeatureSet(
            id="mrt_pit__masterplan_landuse_pit__primary_school__estate_maturity",
            description=(
                "Baseline + MRT PIT + full masterplan + top-20 primary-school counts "
                "+ estate maturity town×month aggregates (no macro sentiment)."
            ),
            categorical_features=cat_b,
            numeric_features=num_mrt_landuse_primary_school_estate,
            engineer=_eng_mrt_landuse_primary_school_estate,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=False),
        ),
        "poi_distancing__macro": FeatureSet(
            id="poi_distancing__macro",
            description="POI distances plus macro sentiment (reference-style macros).",
            categorical_features=cat_b,
            numeric_features=num_macro_poi,
            engineer=_eng_poi,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=True),
        ),
        "mrt_pit__poi_distancing__macro": FeatureSet(
            id="mrt_pit__poi_distancing__macro",
            description="MRT + POI + macro.",
            categorical_features=cat_b,
            numeric_features=num_mrt_macro_poi,
            engineer=_eng_mrt_poi,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=True),
        ),
        "mrt_pit__poi_distancing__macro__masterplan_landuse_pit": FeatureSet(
            id="mrt_pit__poi_distancing__macro__masterplan_landuse_pit",
            description="All pillars: base + MRT PIT + POI + macro + masterplan Land Use PIT.",
            categorical_features=cat_b,
            numeric_features=num_all,
            engineer=_eng_all_features,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=True),
        ),
        "mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity": FeatureSet(
            id="mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity",
            description=(
                "Core35 L40S stack: MRT + macro + masterplan **proximity** (no area_* intersections) "
                "+ top-20 school annulus counts + estate maturity. No POI distance numerics; school signal "
                "via primary_school counts only (POI tables still used at engineer time). "
                "Baseline numerics exclude sale_year (month sin/cos retained). "
                "Engineer still attaches full masterplan snapshot columns for derived proximity scalars; "
                "model contract omits area_* and sale_year."
            ),
            categorical_features=cat_b_core35,
            numeric_features=num_core35_macro_proximity_estate_school,
            engineer=_eng_mrt_macro_proximity_primary_school_estate,
            engineer_kwargs=_LazyCore35L40StackKwargs(root, include_macro=True),
        ),
        "mrt_pit__poi_distancing__macro__masterplan_landuse_pit__grouped": FeatureSet(
            id="mrt_pit__poi_distancing__macro__masterplan_landuse_pit__grouped",
            description="Grouped categoricals variant of full-stack feature set for xgboost_grouped.",
            categorical_features=cat_bg,
            numeric_features=num_all_g,
            engineer=_eng_all_features_grouped,
            engineer_kwargs=_LazyPoiKwargs(root, include_macro=True),
        ),
    }


_REGISTRY_CACHE: dict[str, dict[str, FeatureSet]] = {}


def get_feature_registry(project_root: Path) -> dict[str, FeatureSet]:
    key = str(project_root.resolve())
    if key not in _REGISTRY_CACHE:
        _REGISTRY_CACHE[key] = build_feature_set_registry(project_root)
    return _REGISTRY_CACHE[key]


def get_feature_set(project_root: Path, feature_set_id: str) -> FeatureSet:
    reg = get_feature_registry(project_root)
    if feature_set_id not in reg:
        raise KeyError(f"Unknown feature set '{feature_set_id}'. Options: {sorted(reg)}")
    return reg[feature_set_id]


__all__ = ["FeatureSet", "build_feature_set_registry", "get_feature_registry", "get_feature_set"]
