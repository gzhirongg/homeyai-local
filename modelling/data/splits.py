"""Temporal train/test split and training-row window cap."""

from __future__ import annotations

import pandas as pd


def make_temporal_split(
    df: pd.DataFrame,
    target_column: str,
    test_fraction: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Hold out the last ``test_fraction`` of rows after sorting by ``month``."""
    work = df.copy()
    if "month" in work.columns:
        work = work.sort_values("month", kind="mergesort")
    n = len(work)
    if n == 0:
        y = work[target_column] if target_column in work.columns else pd.Series(dtype=float)
        empty = work.drop(columns=[target_column], errors="ignore")
        return empty, empty.copy(), y.iloc[:0], y.iloc[:0]

    frac = float(test_fraction)
    frac = min(max(frac, 0.01), 0.5) if n > 1 else 0.0
    n_test = max(1, int(round(n * frac))) if frac > 0 else 1
    if n > 1:
        n_test = min(n_test, n - 1)
    split_idx = n - n_test

    train = work.iloc[:split_idx]
    test = work.iloc[split_idx:]
    y_train = train[target_column]
    y_test = test[target_column]
    X_train = train.drop(columns=[target_column])
    X_test = test.drop(columns=[target_column])
    return X_train, X_test, y_train, y_test


def restrict_training_window(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    max_train_rows: int | None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Keep the most recent ``max_train_rows`` when set and positive."""
    if max_train_rows is None or int(max_train_rows) <= 0:
        return X_train, y_train
    cap = int(max_train_rows)
    if len(X_train) <= cap:
        return X_train, y_train
    if "month" in X_train.columns:
        order = X_train.sort_values("month", kind="mergesort").index
    else:
        order = X_train.index
    keep = order[-cap:]
    X_win = X_train.loc[keep].reset_index(drop=True)
    y_win = y_train.loc[keep].reset_index(drop=True)
    return X_win, y_win
