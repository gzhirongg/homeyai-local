"""Shared helpers for point-in-time MRT features (line registry, tokens, validation)."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path


def speculative_upside_score(
    days_to_opening: float | None, k: float = 0.005, midpoint_days: float = 365.0
) -> float | None:
    """
    Mirrors the SQL speculative score: sigmoid centred at `midpoint_days`.
    Returns None when days_to_opening is unknown (no planned station signal).
    """
    if days_to_opening is None or math.isnan(days_to_opening):
        return None
    return 1.0 / (1.0 + math.exp(k * (float(days_to_opening) - midpoint_days)))


def mrt_line_feature_slug(network_line: str) -> str:
    """Stable sklearn-safe column suffix from a network_line label."""
    s = network_line.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# Display strings must match entries in modelling/_mrt_lines.json (extend both when adding a line).
_MRT_NEAREST_LINE_INDICATOR_CODES: dict[str, str] = {
    "Circle Line": "CCL",
    "Cross Island Line": "CRL",
    "Downtown Line": "DTL",
    "East-West Line": "EWL",
    "Jurong Region Line": "JRL",
    "North East Line": "NEL",
    "North-South Line": "NSL",
    "Thomson-East Coast Line": "TEL",
}


def mrt_nearest_line_indicator_suffix(registry_label: str) -> str:
    """Short stable suffix for ``is_nearest_line_<CODE>`` columns (e.g. ``East-West Line`` → ``EWL``)."""
    label = registry_label.strip()
    code = _MRT_NEAREST_LINE_INDICATOR_CODES.get(label)
    if code is None:
        raise ValueError(
            f"No nearest-line indicator code for registry label {label!r}. "
            "Add it to modelling.features.line_vocab._MRT_NEAREST_LINE_INDICATOR_CODES "
            "and modelling/_mrt_lines.json."
        )
    return code


def _mrt_lines_registry_paths(project_root: Path) -> list[Path]:
    """Candidate ``_mrt_lines.json`` locations (pickled root may be stale in Docker)."""
    seen: set[Path] = set()
    out: list[Path] = []

    def add(candidate: Path) -> None:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)

    root = project_root.resolve()
    add(root / "modelling" / "_mrt_lines.json")
    add(root / "_mrt_lines.json")

    env = os.environ.get("HOMEYAI_MODELLING_DIR", "").strip()
    if env:
        add(Path(env).resolve() / "_mrt_lines.json")

    add(Path(__file__).resolve().parents[1] / "_mrt_lines.json")
    return out


def load_mrt_line_vocab(project_root: Path) -> list[str]:
    for path in _mrt_lines_registry_paths(project_root):
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return [str(x).strip() for x in data if str(x).strip()]
    return []


def line_tokens(cell: object) -> set[str]:
    """Normalize Postgres array / list cell into a set of trimmed line strings."""
    if cell is None:
        return set()
    if hasattr(cell, "tolist"):  # numpy
        items = cell.tolist()
    else:
        items = cell
    if not isinstance(items, (list, tuple)):
        items = [items]
    out: set[str] = set()
    for x in items:
        if x is None:
            continue
        sx = str(x).strip()
        if sx:
            out.add(sx)
    return out


def expanded_line_vocab_from_frame(nearest_op, nearest_pl) -> list[str]:
    """Union of observed line tokens (used before strict registry checks)."""
    seen: set[str] = set()
    for series in (nearest_op, nearest_pl):
        if series is None:
            continue
        for cell in series:
            seen.update(line_tokens(cell))
    return sorted(seen)


def assert_lines_in_vocab(lines_found: set[str], vocab: set[str]) -> None:
    extra = sorted(lines_found - vocab)
    if extra:
        missing = ", ".join(extra[:20])
        more = "" if len(extra) <= 20 else f" …(+{len(extra) - 20} more)"
        raise ValueError(
            "MRT line labels in snapshot are missing from modelling/_mrt_lines.json registry. "
            f"Rebuild the snapshot/script or extend the registry: {missing}{more}"
        )
