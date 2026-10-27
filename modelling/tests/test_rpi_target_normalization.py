"""Unit tests for RPI index alignment and nominal rescaling."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modelling.targets import rpi_normalization as rn


def test_adjust_and_rescale_round_trip_vector() -> None:
    prices = np.array([500_000.0, 372_341.57])
    rpi = np.array([150.0, 173.52])
    adj = rn.adjust_prices_to_baseline100(prices, rpi)
    back = rn.rescale_adjusted_to_nominal(adj, rpi)
    np.testing.assert_allclose(back, prices, rtol=1e-9)


def test_sale_quarter_labels() -> None:
    months = pd.Series(["2024-03", "2024-06", "2023-01"])
    q = rn.sale_quarter_labels(months)
    assert q.tolist() == ["2024-Q1", "2024-Q2", "2023-Q1"]


def test_align_rpi_index_to_months_simple() -> None:
    rpi_df = pd.DataFrame(
        {
            "quarter": ["2023-Q4", "2024-Q1", "2024-Q2"],
            "index": [170.0, 175.0, 178.5],
        }
    )
    months = pd.Series(["2024-03", "2024-05"])
    out = rn.align_rpi_index_to_months(months, rpi_df)
    assert out.shape == (2,)
    np.testing.assert_allclose(out, [175.0, 178.5])


def test_load_rpi_index_series_prefers_postgres(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = pd.DataFrame({"quarter": ["2023-Q4", "2024-Q1"], "index": [170.05, 175.43]})
    monkeypatch.setattr(
        "modelling.training_db.load_hdb_rpi_index_levels",
        lambda engine=None: fake,
    )
    df, src = rn.load_rpi_index_series(tmp_path)
    assert src == "postgres"
    assert len(df) == 2


def test_validate_rpi_alignment_ok_small_frame() -> None:
    rn.validate_rpi_alignment(np.array([170.0, 173.51]), context="sanity")


def test_validate_rpi_alignment_raises_when_too_sparse() -> None:
    arr = np.array([np.nan, np.nan], dtype=float)
    with pytest.raises(RuntimeError):
        rn.validate_rpi_alignment(arr, context="sparse", max_missing_rate=0.01)


def test_best_rpi_index_exact_quarter() -> None:
    lev = pd.DataFrame({"quarter": ["2026-Q1", "2026-Q2"], "index": [200.0, 201.5]})
    val, cf = rn._best_rpi_index_for_valuation_quarter(lev, "2026-Q2")
    assert val == pytest.approx(201.5)
    assert cf is False


def test_best_rpi_index_carry_forward_when_future_quarter_missing() -> None:
    lev = pd.DataFrame({"quarter": ["2025-Q4", "2026-Q1"], "index": [198.0, 200.25]})
    val, cf = rn._best_rpi_index_for_valuation_quarter(lev, "2026-Q2")
    assert val == pytest.approx(200.25)
    assert cf is True

    val_same, cf_same = rn._best_rpi_index_for_valuation_quarter(lev, "2026-Q1")
    assert val_same == pytest.approx(200.25)
    assert cf_same is False


def test_rpi_index_for_valuation_month_carry_forward_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub series ends at Q1 — May (Q2) uses Q1 with carry-forward source tag."""

    lev = pd.DataFrame({"quarter": ["2025-Q4", "2026-Q1"], "index": [198.5, 201.6]})

    def _stub_load_db(_url: str) -> pd.DataFrame:
        return lev

    monkeypatch.setattr(rn, "load_rpi_levels_database", _stub_load_db)
    monkeypatch.setattr(rn, "load_rpi_index_series", lambda _root, database_url=None: (pd.DataFrame(), "none"))

    monkeypatch.delenv("DATABASE_URL_ADMIN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_READ_ONLY", raising=False)

    val, src = rn.rpi_index_for_valuation_month("2026-05", database_url="postgresql://x")
    assert val == pytest.approx(201.6)
    assert src == "postgres_carryforward"


def test_rpi_index_for_valuation_month_exact_still_plain_source(monkeypatch: pytest.MonkeyPatch) -> None:
    lev = pd.DataFrame({"quarter": ["2026-Q1", "2026-Q2"], "index": [201.6, 202.0]})

    monkeypatch.setattr(rn, "load_rpi_levels_database", lambda _url: lev)
    monkeypatch.setattr(rn, "load_rpi_index_series", lambda _root, database_url=None: (pd.DataFrame(), "none"))
    monkeypatch.delenv("DATABASE_URL_ADMIN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_READ_ONLY", raising=False)

    val, src = rn.rpi_index_for_valuation_month("2026-05", database_url="postgresql://x")  # 2026-Q2
    assert val == pytest.approx(202.0)
    assert src == "postgres"


def test_best_rpi_index_before_first_quarter_returns_none() -> None:
    lev = pd.DataFrame({"quarter": ["2026-Q1"], "index": [200.0]})
    assert rn._best_rpi_index_for_valuation_quarter(lev, "2025-Q4") == (None, False)
