"""Training-matrix audit policy strings (loads backend helper without backend pytest conftest)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MOD_PATH = _REPO_ROOT / "backend" / "services" / "training_report_feature_labels.py"
_spec = importlib.util.spec_from_file_location("training_report_feature_labels_policy_testmod", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
format_training_matrix_audit_policy_text = _mod.format_training_matrix_audit_policy_text


def test_format_training_matrix_audit_policy_text_apply_and_advisory():
    apply_audit = {
        "feature_selection_policy": "apply_recommended_drops",
        "feature_selection": {
            "applied_to_pipeline": True,
            "columns_removed": ["col_a", "col_b"],
            "diagnostic_row_mask_true_count": 80,
            "n_train_rows": 100,
        },
    }
    s_apply = format_training_matrix_audit_policy_text(apply_audit)
    assert "apply_recommended_drops" in s_apply
    assert "col_a" in s_apply
    assert "coord-masked count=80 of 100" in s_apply

    adv_audit = {"feature_selection_policy": "advisory_only"}
    s_adv = format_training_matrix_audit_policy_text(adv_audit)
    assert "HOMEYAI_FEATURE_SELECTION_POLICY=apply_recommended_drops" in s_adv
    assert "advisory_only" in s_adv
