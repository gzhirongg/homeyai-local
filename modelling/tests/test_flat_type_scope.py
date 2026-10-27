"""Training row subset by canonical HDB flat type (core 3/4/5 ROOM)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from modelling.config.experiments import CORE35_SOURCE_EXPERIMENT_IDS, default_experiments, get_experiment
from modelling.data.flat_type_scope import CORE_FLAT_TYPES_35, apply_flat_type_scope

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_core_flat_types_35_set_contents():
    assert CORE_FLAT_TYPES_35 == frozenset({"3 ROOM", "4 ROOM", "5 ROOM"})


def test_core35_keeps_canonical_spaces_hyphen_upper():
    df = pd.DataFrame(
        {
            "flat_type": ["4 ROOM", "4-room", "4-ROOM", "5 Room", "3 ROOM", "junk"],
            "v": range(6),
        }
    )
    out, audit = apply_flat_type_scope(df, "core_35")
    assert len(out) == 5
    assert audit["applied"] is True
    assert audit["rows_before"] == 6
    assert audit["rows_after"] == 5
    assert audit["rows_dropped"] == 1


def test_core35_excludes_executive_and_multi_generation():
    df = pd.DataFrame({"flat_type": ["EXECUTIVE", "MULTI GENERATION", "2 ROOM"], "x": [1, 2, 3]})
    out, audit = apply_flat_type_scope(df, "core_35")
    assert len(out) == 0
    ex_counts = {(e["flat_type"], int(e["count"])) for e in audit["excluded_flat_types"]}
    assert ex_counts == {("EXECUTIVE", 1), ("MULTI-GENERATION", 1), ("2 ROOM", 1)}
    assert audit["rows_after"] == 0


def test_all_scope_is_no_op_with_audit_not_applied():
    df = pd.DataFrame({"flat_type": ["1 ROOM"], "x": [1]})
    out, audit = apply_flat_type_scope(df, "all")
    pd.testing.assert_frame_equal(out.reset_index(drop=True), df.reset_index(drop=True))
    assert audit["applied"] is False
    assert audit["rows_dropped"] == 0
    assert audit["excluded_flat_types"] == []


def test_core35_requires_flat_type_column():
    df = pd.DataFrame({"town": ["X"]})
    with pytest.raises(RuntimeError, match="requires column"):
        apply_flat_type_scope(df, "core_35")


def test_apply_flat_type_scope_rejects_unknown_scope():
    df = pd.DataFrame({"flat_type": ["4 ROOM"]})
    with pytest.raises(ValueError, match="Unknown flat_type_scope"):
        apply_flat_type_scope(df, "bogus")


def test_get_experiment_resolves_registered_core35():
    exp = get_experiment(_REPO_ROOT, "xgboost_tuned__mrt__core35")
    assert exp.id == "xgboost_tuned__mrt__core35"
    assert exp.flat_type_scope == "core_35"


def test_all_core35_source_ids_have_registered_variants():
    reg = default_experiments(_REPO_ROOT)
    for bid in CORE35_SOURCE_EXPERIMENT_IDS:
        assert bid in reg, f"missing base {bid}"
        core_id = f"{bid}__core35"
        assert core_id in reg, f"missing variant {core_id}"
        assert reg[core_id].flat_type_scope == "core_35"
