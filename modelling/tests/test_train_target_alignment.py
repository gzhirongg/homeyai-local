"""Training row cap indexing and target/engineered alignment for sklearn fits."""

from __future__ import annotations

import pandas as pd
import pytest

from modelling.data.splits import restrict_training_window
from modelling.runners.train_core import _align_target_to_engineered


def test_restrict_training_window_resets_index_when_capped() -> None:
    idx = pd.Index([100 + i * 10 for i in range(500)])
    X_train = pd.DataFrame({"month": range(500), "x": range(500)}, index=idx)
    y_train = pd.Series(range(500), index=idx, name="resale_price")
    X_out, y_out = restrict_training_window(X_train, y_train, max_train_rows=100)
    assert len(X_out) == 100
    assert len(y_out) == 100
    assert list(X_out.index) == list(range(100))
    assert list(y_out.index) == list(range(100))


def test_restrict_training_window_no_reset_when_under_cap() -> None:
    idx = pd.Index([7, 8, 9])
    X_train = pd.DataFrame({"month": [1, 2, 3], "x": [1, 2, 3]}, index=idx)
    y_train = pd.Series([1.0, 2.0, 3.0], index=idx, name="resale_price")
    X_out, y_out = restrict_training_window(X_train, y_train, max_train_rows=10)
    assert X_out.index.equals(idx)
    assert y_out.index.equals(idx)


def test_align_target_to_engineered_matches_engineered_index() -> None:
    eng = pd.DataFrame({"a": [1, 2, 3]}, index=[0, 1, 2])
    y = pd.Series([10.0, 20.0, 30.0], index=[900, 901, 902], name="resale_price_rpi_adj")
    aligned = _align_target_to_engineered(eng, y, raw_row_count=3, context="train")
    assert aligned.index.equals(eng.index)
    assert aligned.to_numpy(dtype=float).tolist() == [10.0, 20.0, 30.0]


def test_align_target_to_engineered_row_count_mismatch_raises() -> None:
    eng = pd.DataFrame({"a": [1, 2]}, index=[0, 1])
    y = pd.Series([1.0, 2.0, 3.0], index=[0, 1, 2])
    with pytest.raises(RuntimeError, match="feature engineering changed row count"):
        _align_target_to_engineered(eng, y, raw_row_count=3, context="train")


def test_align_target_to_engineered_noop_when_already_aligned() -> None:
    eng = pd.DataFrame({"a": [1, 2]}, index=[5, 6])
    y = pd.Series([1.0, 2.0], index=[5, 6])
    aligned = _align_target_to_engineered(eng, y, raw_row_count=2, context="train")
    assert aligned is y
