"""Population Stability Index (PSI) utilities."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_psi(
    expected: pd.Series | np.ndarray,
    actual: pd.Series | np.ndarray,
    *,
    buckets: int = 10,
) -> float:
    expected = pd.Series(expected).dropna()
    actual = pd.Series(actual).dropna()
    is_numeric = pd.api.types.is_numeric_dtype(expected)

    if is_numeric:
        br = np.unique(np.percentile(expected, np.linspace(0, 100, buckets + 1)))
        if len(br) == 1:
            br = np.array([br[0] - 0.1, br[0] + 0.1])
        br[0] = -np.inf
        br[-1] = np.inf
        expected_pct = pd.cut(expected, bins=br, include_lowest=True).value_counts(normalize=True).sort_index()
        actual_pct = pd.cut(actual, bins=br, include_lowest=True).value_counts(normalize=True).sort_index()
    else:
        expected_cats = set(expected.unique())
        actual_mapped = actual.apply(lambda x: x if x in expected_cats else "Other")
        all_cats = list(expected_cats) + ["Other"]
        expected_pct = expected.value_counts(normalize=True).reindex(all_cats, fill_value=0)
        actual_pct = actual_mapped.value_counts(normalize=True).reindex(all_cats, fill_value=0)

    e_smooth = np.maximum(expected_pct.values, 0.0001)
    a_smooth = np.maximum(actual_pct.values, 0.0001)
    psi_components = (a_smooth - e_smooth) * np.log(a_smooth / e_smooth)
    return float(np.sum(psi_components))


def psi_summary_table(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    *,
    buckets: int = 10,
) -> pd.DataFrame:
    rows = []
    for feature in features:
        if feature not in train.columns or feature not in test.columns:
            continue
        score = calculate_psi(train[feature], test[feature], buckets=buckets)
        if score < 0.1:
            sev = "Stable"
        elif score <= 0.25:
            sev = "Warning"
        else:
            sev = "Action Required"
        rows.append({"Feature Name": feature, "PSI Score": round(score, 4), "Drift Severity": sev})
    return pd.DataFrame(rows)
