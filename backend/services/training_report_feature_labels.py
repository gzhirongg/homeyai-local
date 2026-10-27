"""Human-readable feature-set labels and pillar grouping for training reports."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_SERVICES_ROOT = Path(__file__).resolve().parent
_BACKEND_ROOT = _SERVICES_ROOT.parent
_REPO_ROOT = _BACKEND_ROOT.parent
_FEATURE_MODULES_PATH = _REPO_ROOT / "modelling" / "config" / "feature_modules.py"
if not _FEATURE_MODULES_PATH.is_file():
    _FEATURE_MODULES_PATH = _BACKEND_ROOT / "modelling" / "config" / "feature_modules.py"


def _load_feature_modules_dyn() -> Any:
    name = "homeyai_training_report_feature_modules"
    spec = importlib.util.spec_from_file_location(name, _FEATURE_MODULES_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"feature_modules not loadable: {_FEATURE_MODULES_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_fmods = _load_feature_modules_dyn()
FEATURE_SET_BUILD_MODULES = _fmods.FEATURE_SET_BUILD_MODULES
TAG_ESTATE_MATURITY = _fmods.TAG_ESTATE_MATURITY
TAG_MASTERPLAN_LANDUSE = _fmods.TAG_MASTERPLAN_LANDUSE
TAG_MRT_PIT = _fmods.TAG_MRT_PIT
TAG_RESALE_BASELINE = _fmods.TAG_RESALE_BASELINE
feature_modules_for_feature_set = _fmods.feature_modules_for_feature_set

from modelling.features.base import base_categorical_columns, base_numeric_columns
from modelling.features.macro_sentiment import MACRO_NUMERIC_FEATURES
from modelling.features.mrt_pit import mrt_numeric_feature_names
from modelling.features.poi_distancing import POI_NUMERIC_FEATURES

try:
    from modelling.features.estate_maturity import ESTATE_MATURITY_NUMERIC_FEATURES
except ModuleNotFoundError:
    ESTATE_MATURITY_NUMERIC_FEATURES = ()

try:
    from modelling.features.primary_school import PRIMARY_SCHOOL_NUMERIC
except ModuleNotFoundError:
    PRIMARY_SCHOOL_NUMERIC = ()

try:
    from modelling.features.masterplan_landuse_pit import MASTERPLAN_LAND_USE_NUMERIC
except ModuleNotFoundError:
    MASTERPLAN_LAND_USE_NUMERIC = ()

_PILLAR_ORDER = (
    "baseline",
    "mrt",
    "landuse",
    "macro",
    "poi",
    "primary_school",
    "estate",
    "other",
)

_BASELINE_EXTRA = frozenset(
    {
        "months_since_2015",
        "resale_price",
    }
)

_BASELINE_NAMES: frozenset[str] = (
    frozenset(_fmods._BASELINE_SQL_COLUMNS)
    | frozenset(base_numeric_columns("legacy"))
    | frozenset(base_numeric_columns("grouped"))
    | frozenset(base_categorical_columns("legacy"))
    | frozenset(base_categorical_columns("grouped"))
    | _BASELINE_EXTRA
)

_MRT_NAMES: frozenset[str] = frozenset(_fmods._MRT_PIT_SQL_COLUMNS) | frozenset(mrt_numeric_feature_names(None))
_LANDUSE_NAMES: frozenset[str] = frozenset(_fmods._MASTERPLAN_SQL_COLUMNS) | frozenset(MASTERPLAN_LAND_USE_NUMERIC)
_MACRO_NAMES: frozenset[str] = frozenset(MACRO_NUMERIC_FEATURES)
_POI_NAMES: frozenset[str] = frozenset(POI_NUMERIC_FEATURES)
_PRIMARY_SCHOOL_NAMES: frozenset[str] = frozenset(PRIMARY_SCHOOL_NUMERIC)
_ESTATE_NAMES: frozenset[str] = frozenset(ESTATE_MATURITY_NUMERIC_FEATURES)


def format_feature_set_display(feature_set_id: str | None, *, description: str | None = None) -> str:
    """Compose a short human label like ``Baseline + MRT + Macro (grouped)``."""
    fs = (feature_set_id or "").strip() or "unknown"
    parts: list[str] = []
    notes: list[str] = []

    try:
        mods = feature_modules_for_feature_set(fs)
    except KeyError:
        mods = FEATURE_SET_BUILD_MODULES.get(fs, ())

    if TAG_RESALE_BASELINE in mods:
        parts.append("Baseline")
    if TAG_MRT_PIT in mods:
        parts.append("MRT")
    if TAG_MASTERPLAN_LANDUSE in mods:
        parts.append("Land use")

    if "macro" in fs:
        parts.append("Macro")
    if "poi" in fs:
        parts.append("POI")
    if "primary_school" in fs:
        parts.append("Primary school")
    if TAG_ESTATE_MATURITY in mods:
        parts.append("Estate maturity")

    if "grouped" in fs:
        notes.append("grouped")
    if "months_since_2015" in fs:
        notes.append("months_since_2015")

    if not parts:
        parts.append(fs)

    label = " + ".join(parts)
    if notes:
        label += f" ({', '.join(notes)})"

    if description and str(description).strip():
        short = str(description).strip().replace("\n", " ")
        if len(short) > 140:
            short = short[:137] + "…"
        label = f"{label} — {short}"

    return label


def enabled_pillars_for_feature_set(feature_set_id: str | None) -> frozenset[str]:
    fs = (feature_set_id or "").strip() or "baseline_v1"
    tags: tuple[str, ...]
    try:
        tags = feature_modules_for_feature_set(fs)
    except KeyError:
        tags = FEATURE_SET_BUILD_MODULES.get(fs, (TAG_RESALE_BASELINE,))

    out: set[str] = set()
    if TAG_RESALE_BASELINE in tags:
        out.add("baseline")
    if TAG_MRT_PIT in tags:
        out.add("mrt")
    if TAG_MASTERPLAN_LANDUSE in tags:
        out.add("landuse")
    if "macro" in fs:
        out.add("macro")
    if "poi" in fs:
        out.add("poi")
    if "primary_school" in fs:
        out.add("primary_school")
    if TAG_ESTATE_MATURITY in tags:
        out.add("estate")
    out.add("other")
    return frozenset(out)


def classify_feature_pillar(column_name: str) -> str:
    """Assign one pillar bucket per column (for grouping in Section 2)."""
    c = str(column_name)
    if c in _BASELINE_NAMES:
        return "baseline"
    if c in _PRIMARY_SCHOOL_NAMES:
        return "primary_school"
    if c in _ESTATE_NAMES:
        return "estate"
    if c in _MRT_NAMES:
        return "mrt"
    if c in _LANDUSE_NAMES:
        return "landuse"
    if c in _MACRO_NAMES:
        return "macro"
    if c in _POI_NAMES:
        return "poi"
    return "other"


def group_feature_stats_by_pillar(
    fstats: dict[str, Any],
    *,
    feature_set_id: str | None,
) -> dict[str, dict[str, Any]]:
    """Partition ``feature_stats_full`` entries by pillar; skip empty disabled buckets later."""
    enabled = enabled_pillars_for_feature_set(feature_set_id)
    grouped: dict[str, dict[str, Any]] = {p: {} for p in _PILLAR_ORDER}
    for name, meta in fstats.items():
        if not isinstance(meta, dict):
            continue
        pillar = classify_feature_pillar(str(name))
        if pillar not in enabled and pillar != "other":
            pillar = "other"
        grouped[pillar][str(name)] = meta
    return grouped


def build_selection_flags(selection_artifacts: dict[str, Any]) -> dict[str, list[str]]:
    """Merge variance / correlation / MI / permutation JSON into diagnostic flag lists per feature."""
    flags: dict[str, list[str]] = {}

    def add_feat(fname: str, tag: str) -> None:
        flags.setdefault(fname, []).append(tag)

    fv = selection_artifacts.get("feature_variance")
    if isinstance(fv, dict):
        for c in fv.get("dropped_low_variance") or []:
            add_feat(str(c), "low_variance")

    cp = selection_artifacts.get("correlated_pairs")
    if isinstance(cp, dict):
        for p in cp.get("pairs") or []:
            if isinstance(p, dict) and p.get("recommended_drop"):
                add_feat(str(p["recommended_drop"]), "high_correlation_pair")

    mi = selection_artifacts.get("feature_mi_scores")
    if isinstance(mi, dict):
        for c in mi.get("flagged_low_mi") or []:
            add_feat(str(c), "low_mutual_information")

    perm = selection_artifacts.get("feature_permutation_importance")
    if isinstance(perm, dict):
        names = perm.get("feature_names") or []
        means = perm.get("importances_mean") or []
        if isinstance(names, list) and isinstance(means, list):
            for name, mean in zip(names, means):
                try:
                    if float(mean) <= 0.0:
                        add_feat(str(name), "permutation_importance_le_0")
                except (TypeError, ValueError):
                    continue

    return flags


def load_selection_artifacts_from_dir(root: Path) -> dict[str, Any]:
    """Load optional JSON artefacts from an experiment directory (same layout as MinIO upload)."""
    mapping = {
        "feature_variance": "feature_variance.json",
        "correlated_pairs": "correlated_pairs.json",
        "feature_mi_scores": "feature_mi_scores.json",
        "feature_permutation_importance": "feature_permutation_importance.json",
        "features_dropped": "features_dropped.json",
    }
    out: dict[str, Any] = {}
    root = root.resolve()
    for key, filename in mapping.items():
        p = root / filename
        if not p.is_file():
            continue
        try:
            out[key] = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError):
            continue
    return out


def _reasons_map_from_features_dropped(doc: dict[str, Any] | None) -> dict[str, list[str]]:
    """Normalize ``features_dropped.json`` ``reasons`` map to ``column -> sorted tag strings``."""
    if not isinstance(doc, dict):
        return {}
    raw = doc.get("reasons")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        key = str(k)
        if isinstance(v, list):
            out[key] = sorted({str(x) for x in v})
        elif isinstance(v, (tuple, frozenset, set)):
            out[key] = sorted({str(x) for x in v})
    return out


def build_pillar_feature_inventory(
    *,
    training_matrix_audit: dict[str, Any],
    selection_flags: dict[str, list[str]],
    feature_set_id: str | None,
    features_dropped_doc: dict[str, Any] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Full registry column inventory per pillar with retained / dropped / advisory-flag outcomes.

    Returns ``(inventory_by_pillar_id, pack_summary_rows)`` where each inventory row has
    ``feature``, ``kind`` (``numeric`` | ``categorical``), ``outcome``, ``notes``.
    """
    reg = training_matrix_audit.get("registered_feature_set")
    if not isinstance(reg, dict):
        return {}, []

    fs_audit = training_matrix_audit.get("feature_selection")
    fs_audit_dict = fs_audit if isinstance(fs_audit, dict) else {}

    nums_before = fs_audit_dict.get("numeric_features_before_apply")
    if isinstance(nums_before, list) and nums_before:
        numerics_registry = [str(x) for x in nums_before]
    else:
        rn = reg.get("numeric_features") or []
        numerics_registry = [str(x) for x in rn] if isinstance(rn, list) else []

    cats_raw = reg.get("categorical_features") or []
    categoricals_registry = [str(x) for x in cats_raw] if isinstance(cats_raw, list) else []

    removed_raw = fs_audit_dict.get("columns_removed") or []
    removed_set = frozenset(str(x) for x in removed_raw) if isinstance(removed_raw, list) else frozenset()

    numeric_union = sorted(frozenset(numerics_registry) | removed_set)

    fd_reasons = _reasons_map_from_features_dropped(features_dropped_doc)

    pol = str(training_matrix_audit.get("feature_selection_policy") or "advisory_only")
    applied_raw = fs_audit_dict.get("applied_to_pipeline")
    applied_to_pipeline = applied_raw is True

    enabled = enabled_pillars_for_feature_set(feature_set_id)

    grouped: dict[str, list[dict[str, Any]]] = {p: [] for p in _PILLAR_ORDER}

    def pillar_for(name: str) -> str:
        p = classify_feature_pillar(name)
        if p not in enabled and p != "other":
            return "other"
        return p

    def outcome_and_notes(fname: str, *, kind: str) -> tuple[str, str]:
        flags = sorted(selection_flags.get(fname, []))
        if fname in removed_set:
            note_tags = fd_reasons.get(fname) or flags
            notes = ", ".join(note_tags) if note_tags else "—"
            return "Dropped (pipeline)", notes

        if kind == "categorical":
            return "Retained", "—"

        show_advisory_flagged = pol == "advisory_only" or not applied_to_pipeline
        if flags and show_advisory_flagged:
            return "Flagged (advisory)", ", ".join(flags)
        if flags:
            return "Retained", "Diagnostics (not dropped): " + ", ".join(flags)
        return "Retained", "—"

    for fname in numeric_union:
        outcome, notes = outcome_and_notes(fname, kind="numeric")
        grouped[pillar_for(fname)].append(
            {
                "feature": fname,
                "kind": "numeric",
                "outcome": outcome,
                "notes": notes,
            }
        )

    for fname in sorted(set(categoricals_registry)):
        outcome, notes = outcome_and_notes(fname, kind="categorical")
        grouped[pillar_for(fname)].append(
            {
                "feature": fname,
                "kind": "categorical",
                "outcome": outcome,
                "notes": notes,
            }
        )

    for plist in grouped.values():
        plist.sort(key=lambda r: str(r.get("feature", "")))

    pack_summary: list[dict[str, Any]] = []
    for pid in _PILLAR_ORDER:
        rows = grouped.get(pid) or []
        if not rows:
            continue
        n_reg = len(rows)
        n_ret = sum(1 for r in rows if r["outcome"] == "Retained")
        n_drop = sum(1 for r in rows if r["outcome"] == "Dropped (pipeline)")
        n_flag = sum(1 for r in rows if r["outcome"] == "Flagged (advisory)")
        pack_summary.append(
            {
                "pillar_id": pid,
                "registered": n_reg,
                "retained": n_ret,
                "dropped": n_drop,
                "flagged_advisory": n_flag,
            }
        )

    return grouped, pack_summary


def feature_selection_policy_from_metrics(metrics: dict[str, Any] | None) -> str | None:
    """Return ``training_matrix_audit.feature_selection_policy`` if present."""
    if not isinstance(metrics, dict):
        return None
    audit = metrics.get("training_matrix_audit")
    if not isinstance(audit, dict):
        return None
    pol = audit.get("feature_selection_policy")
    if pol is None:
        return None
    s = str(pol).strip()
    return s or None


def feature_selection_summary_from_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Subset of audit fields for APIs / UI (no full metrics blob needed on slim rows when duplicated)."""
    pol = feature_selection_policy_from_metrics(metrics)
    out: dict[str, Any] = {"policy": pol, "applied_to_pipeline": None, "columns_removed_count": None}
    if not isinstance(metrics, dict):
        return out
    audit = metrics.get("training_matrix_audit")
    if not isinstance(audit, dict):
        return out
    fs_audit = audit.get("feature_selection")
    if not isinstance(fs_audit, dict):
        return out
    ap = fs_audit.get("applied_to_pipeline")
    if isinstance(ap, bool):
        out["applied_to_pipeline"] = ap
    removed = fs_audit.get("columns_removed") or []
    if isinstance(removed, list):
        out["columns_removed_count"] = len(removed)
    return out


def format_feature_selection_policy_short(policy: str | None) -> str:
    """Cover table / badge label for stored policy value."""
    if policy is None:
        return "Not recorded"
    if policy == "apply_recommended_drops":
        return "Drops applied"
    if policy == "advisory_only":
        return "Advisory only"
    return policy


def format_feature_selection_policy_badge(policy: str | None) -> str:
    """One-line bold callout for audit page (matches short labels)."""
    return format_feature_selection_policy_short(policy)


def format_columns_removed_cover_preview(metrics: dict[str, Any] | None, *, max_names: int = 48) -> str | None:
    """Comma-separated column preview for cover row when policy is apply; ``None`` if N/A."""
    if feature_selection_policy_from_metrics(metrics) != "apply_recommended_drops":
        return None
    if not isinstance(metrics, dict):
        return None
    audit = metrics.get("training_matrix_audit")
    if not isinstance(audit, dict):
        return None
    fs_audit = audit.get("feature_selection")
    if not isinstance(fs_audit, dict):
        return None
    removed = fs_audit.get("columns_removed") or []
    if not isinstance(removed, list):
        return None
    names = [str(x) for x in removed[:max_names]]
    preview = ", ".join(names)
    if len(removed) > max_names:
        preview += " …"
    return preview if preview else "(none)"


def format_training_matrix_audit_policy_text(training_matrix_audit: dict[str, Any]) -> str:
    """Single paragraph describing recorded feature-selection policy for the audit page."""
    pol = str(training_matrix_audit.get("feature_selection_policy") or "advisory_only")
    fs_audit = (
        training_matrix_audit["feature_selection"]
        if isinstance(training_matrix_audit.get("feature_selection"), dict)
        else {}
    )
    if pol == "apply_recommended_drops":
        applied = fs_audit.get("applied_to_pipeline")
        removed = fs_audit.get("columns_removed") or []
        if not isinstance(removed, list):
            removed = []
        n_diag = fs_audit.get("diagnostic_row_mask_true_count")
        n_tr = fs_audit.get("n_train_rows")
        preview = ", ".join(map(str, removed[:48]))
        if len(removed) > 48:
            preview += " …"
        return (
            "Policy apply_recommended_drops was enabled: numeric columns flagged by variance / correlation / "
            "mutual-information diagnostics were removed from the FeatureSet before fitting when safe "
            f"(minimum numeric column floor enforced). Applied to pipeline: {applied!r}. "
            f"Removed {len(removed)} column(s): {preview or '(none)'}. "
            "Diagnostics used rows with finite target"
            + (
                f"; coord-masked count={n_diag} of {n_tr} train rows for POI feature sets."
                if n_diag is not None
                else "."
            )
        )
    return (
        "Variance, correlation, and mutual-information artefacts flag columns for review only—they do not remove "
        "columns from the fitted sklearn pipeline unless you enable HOMEYAI_FEATURE_SELECTION_POLICY=apply_recommended_drops "
        "(or pass --feature-selection-policy apply) so failing numeric columns are dropped before fit. "
        f"Recorded policy: {pol!r}."
    )


__all__ = [
    "build_pillar_feature_inventory",
    "build_selection_flags",
    "classify_feature_pillar",
    "enabled_pillars_for_feature_set",
    "feature_selection_policy_from_metrics",
    "feature_selection_summary_from_metrics",
    "format_columns_removed_cover_preview",
    "format_feature_selection_policy_badge",
    "format_feature_selection_policy_short",
    "format_feature_set_display",
    "format_training_matrix_audit_policy_text",
    "group_feature_stats_by_pillar",
    "load_selection_artifacts_from_dir",
]
