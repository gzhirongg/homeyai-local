"""train_from_frame applies diagnostic drops before pipeline build when policy requests it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from modelling.config.experiments import Experiment
from modelling.config.feature_sets import FeatureSet


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _stub_feature_set() -> FeatureSet:
    def _eng(raw: pd.DataFrame, **_kw: object) -> pd.DataFrame:
        n = len(raw)
        rng = np.random.default_rng(42)
        return pd.DataFrame(
            {
                "const_like": np.ones(n),
                "n2": rng.normal(size=n),
                "n3": rng.normal(size=n),
                "n4": rng.normal(size=n),
            },
            index=raw.index,
        )

    return FeatureSet(
        id="unit_custom",
        description="",
        categorical_features=[],
        numeric_features=["const_like", "n2", "n3", "n4"],
        engineer=_eng,
        engineer_kwargs={},
    )


def _rpi_stub_levels_df() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for y in range(2018, 2032):
        for q in (1, 2, 3, 4):
            rows.append({"quarter": f"{y}-Q{q}", "index": float(148.0 + 0.2 * len(rows))})
    return pd.DataFrame(rows)


def _patch_rpi_for_train(monkeypatch: pytest.MonkeyPatch, tc) -> None:
    lv = _rpi_stub_levels_df()
    monkeypatch.setattr(tc, "load_rpi_index_series", lambda _pr: (lv.copy(), "unit_stub"))


def test_train_from_frame_applies_drops_before_pipeline(monkeypatch, project_root: Path, tmp_path: Path) -> None:
    """Near-constant column is flagged; apply policy removes it before preprocessor pipeline sees FeatureSet."""
    import modelling.feature_selection as fs_mod
    import modelling.runners.train_core as tc

    _patch_rpi_for_train(monkeypatch, tc)

    def only_const_like(*_a, registered_numeric: list[str], **_k):
        return {
            "dropped": ["const_like"],
            "reasons": {"const_like": ["low_variance"]},
            "n_registered_numeric": len(registered_numeric),
            "n_recommended_drop": 1,
        }

    monkeypatch.setattr(fs_mod, "aggregate_recommended_drops", only_const_like)

    n = 120
    months = pd.period_range("2020-01", periods=n, freq="M").strftime("%Y-%m")
    raw_df = pd.DataFrame(
        {
            "month": months,
            "resale_price": np.linspace(300_000, 400_000, n),
            "town": ["X"] * n,
        }
    )

    fs = _stub_feature_set()
    monkeypatch.setattr(tc, "get_feature_set", lambda _pr, _fid: fs)

    captured: dict[str, list[str]] = {}

    def capture_build(fset: FeatureSet, _ms: object):
        captured["numeric_features"] = list(fset.numeric_features)
        pre = MagicMock()
        pre.get_feature_names_out.return_value = ["num__x"]
        pipe = MagicMock()
        pipe.named_steps = {"preprocessor": pre, "model": MagicMock(regressor_=MagicMock(spec=[]))}

        def _pred(X: pd.DataFrame) -> np.ndarray:
            return np.full(len(X), 350_000.0, dtype=float)

        pipe.predict.side_effect = _pred
        return pipe

    monkeypatch.setattr(tc, "build_preprocessor_only_pipeline", capture_build)

    def passthrough_wrap(partial: MagicMock, _fs: FeatureSet, _pr: Path):
        full = MagicMock()
        full.named_steps = {"feature_engineering": MagicMock(), **partial.named_steps}
        full.predict = partial.predict
        return full

    monkeypatch.setattr(tc, "wrap_pipeline_with_feature_engineering", passthrough_wrap)

    monkeypatch.setattr(
        tc,
        "get_model_spec",
        lambda _pr, _mid, random_state=42: SimpleNamespace(
            search_kind="grid",
            param_grid={"k": [1]},
            display_name="stub",
        ),
    )

    class StubGridSearch:
        def __init__(self, estimator: object, *args: object, **kwargs: object) -> None:
            self._estimator = estimator

        def fit(self, X: object, y: object) -> StubGridSearch:
            self.best_estimator_ = self._estimator
            self.cv_results_ = {}
            for i in range(4):
                self.cv_results_[f"split{i}_test_score"] = np.array([-100.0])
                self.cv_results_[f"split{i}_train_score"] = np.array([-50.0])
            self.best_index_ = 0
            self.best_score_ = -100.0
            self.best_params_ = {}
            return self

    monkeypatch.setattr(tc, "GridSearchCV", StubGridSearch)
    monkeypatch.setattr(tc, "RandomizedSearchCV", StubGridSearch)

    def fake_perm(_est, X_te: pd.DataFrame, _y, **_kw):
        class R:
            importances_mean = np.zeros(len(X_te.columns))
            importances_std = np.zeros(len(X_te.columns))

        return R()

    monkeypatch.setattr(tc, "permutation_importance", fake_perm)
    monkeypatch.setattr(tc, "write_feature_selection_plot_pngs", lambda *a, **k: None)
    monkeypatch.setattr(tc.joblib, "dump", lambda obj, path: Path(path).write_bytes(b""))
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, path, **kw: Path(path).write_bytes(b""))

    exp = Experiment(
        id="unit_test__fs_apply",
        feature_set_id="unit_custom",
        model_id="linear",
        description="",
        test_fraction=0.2,
        cv_splits=4,
        max_train_rows=None,
    )
    out_dir = tmp_path / "run_out"
    tc.train_from_frame(exp, raw_df, project_root, out_dir, feature_selection_policy="apply")

    assert captured["numeric_features"] == ["n2", "n3", "n4"]

    fd = (out_dir / "features_dropped.json").read_text(encoding="utf-8")
    assert "const_like" in fd


def test_train_from_frame_advisory_keeps_numeric(monkeypatch, project_root: Path, tmp_path: Path) -> None:
    import modelling.runners.train_core as tc

    _patch_rpi_for_train(monkeypatch, tc)

    n = 120
    months = pd.period_range("2020-01", periods=n, freq="M").strftime("%Y-%m")
    raw_df = pd.DataFrame(
        {
            "month": months,
            "resale_price": np.linspace(300_000, 400_000, n),
            "town": ["X"] * n,
        }
    )

    fs = _stub_feature_set()
    monkeypatch.setattr(tc, "get_feature_set", lambda _pr, _fid: fs)

    captured: dict[str, list[str]] = {}

    def capture_build(fset: FeatureSet, _ms: object):
        captured["numeric_features"] = list(fset.numeric_features)
        pre = MagicMock()
        pre.get_feature_names_out.return_value = ["num__x"]
        pipe = MagicMock()
        pipe.named_steps = {"preprocessor": pre, "model": MagicMock(regressor_=MagicMock(spec=[]))}

        def _pred(X: pd.DataFrame) -> np.ndarray:
            return np.full(len(X), 350_000.0, dtype=float)

        pipe.predict.side_effect = _pred
        return pipe

    monkeypatch.setattr(tc, "build_preprocessor_only_pipeline", capture_build)

    def passthrough_wrap(partial: MagicMock, _fs: FeatureSet, _pr: Path):
        full = MagicMock()
        full.named_steps = {"feature_engineering": MagicMock(), **partial.named_steps}
        full.predict = partial.predict
        return full

    monkeypatch.setattr(tc, "wrap_pipeline_with_feature_engineering", passthrough_wrap)
    monkeypatch.setattr(
        tc,
        "get_model_spec",
        lambda _pr, _mid, random_state=42: SimpleNamespace(
            search_kind="grid",
            param_grid={"k": [1]},
            display_name="stub",
        ),
    )

    class StubGridSearch:
        def __init__(self, estimator: object, *args: object, **kwargs: object) -> None:
            self._estimator = estimator

        def fit(self, X: object, y: object) -> StubGridSearch:
            self.best_estimator_ = self._estimator
            self.cv_results_ = {}
            for i in range(4):
                self.cv_results_[f"split{i}_test_score"] = np.array([-100.0])
                self.cv_results_[f"split{i}_train_score"] = np.array([-50.0])
            self.best_index_ = 0
            self.best_score_ = -100.0
            self.best_params_ = {}
            return self

    monkeypatch.setattr(tc, "GridSearchCV", StubGridSearch)
    monkeypatch.setattr(tc, "RandomizedSearchCV", StubGridSearch)

    def fake_perm(_est, X_te: pd.DataFrame, _y, **_kw):
        class R:
            importances_mean = np.zeros(len(X_te.columns))
            importances_std = np.zeros(len(X_te.columns))

        return R()

    monkeypatch.setattr(tc, "permutation_importance", fake_perm)
    monkeypatch.setattr(tc, "write_feature_selection_plot_pngs", lambda *a, **k: None)
    monkeypatch.setattr(tc.joblib, "dump", lambda obj, path: Path(path).write_bytes(b""))
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, path, **kw: Path(path).write_bytes(b""))

    exp = Experiment(
        id="unit_test__fs_advisory",
        feature_set_id="unit_custom",
        model_id="linear",
        description="",
        test_fraction=0.2,
        cv_splits=4,
        max_train_rows=None,
    )
    out_dir = tmp_path / "run_out_adv"
    tc.train_from_frame(exp, raw_df, project_root, out_dir, feature_selection_policy="advisory_only")

    assert captured["numeric_features"] == ["const_like", "n2", "n3", "n4"]
