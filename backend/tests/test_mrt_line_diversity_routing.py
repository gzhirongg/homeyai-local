"""Unit tests for pass-1 line-diversity greedy selection (no PostGIS required)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_BACKENDS = Path(__file__).resolve().parents[1]
_GEO_PATH = _BACKENDS / "services" / "geospatial_service.py"
_spec = importlib.util.spec_from_file_location("geospatial_service", _GEO_PATH)
assert _spec and _spec.loader
_gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gs)
greedy_line_diverse_physical_ids = _gs.greedy_line_diverse_physical_ids
MRT_ROUTING_PASS1_STATES = _gs.MRT_ROUTING_PASS1_STATES


def test_greedy_skips_redundant_line_only_station():
    # Nearest: interchange {NEL, DTL}; next: NEL-only → skip; third: EW → take.
    phys_order = [10, 20, 30]
    line_sets = {
        10: {"NEL", "DTL"},
        20: {"NEL"},
        30: {"EWL"},
    }
    out = greedy_line_diverse_physical_ids(phys_order, line_sets, max_stations=4)
    assert out == [10, 30]


def test_greedy_takes_overlap_when_new_line_exists():
    # Second shares NEL with first but adds TE → keep.
    phys_order = [1, 2]
    line_sets = {
        1: {"NEL"},
        2: {"NEL", "TEL"},
    }
    out = greedy_line_diverse_physical_ids(phys_order, line_sets, max_stations=4)
    assert out == [1, 2]


def test_greedy_stops_at_four():
    phys_order = [1, 2, 3, 4, 5]
    line_sets = {i: {f"L{i}"} for i in phys_order}
    out = greedy_line_diverse_physical_ids(phys_order, line_sets, max_stations=4)
    assert out == [1, 2, 3, 4]


def test_pass1_states_exclude_unknown():
    assert "UNKNOWN" not in MRT_ROUTING_PASS1_STATES
    assert "OPERATIONAL" in MRT_ROUTING_PASS1_STATES
    assert "ANNOUNCED_UNDATED" in MRT_ROUTING_PASS1_STATES
