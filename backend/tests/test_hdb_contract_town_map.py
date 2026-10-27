"""Tests for HDB Property Information → resale town mapping and street normalisation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SPEC_AN = importlib.util.spec_from_file_location(
    "address_normalize",
    _REPO_ROOT / "backend" / "scripts" / "address_normalize.py",
)
assert _SPEC_AN and _SPEC_AN.loader
_address_mod = importlib.util.module_from_spec(_SPEC_AN)
_SPEC_AN.loader.exec_module(_address_mod)
normalize_street = _address_mod.normalize_street

_SPEC_HCDM = importlib.util.spec_from_file_location(
    "hdb_contract_town_map",
    _REPO_ROOT / "backend" / "hdb_contract_town_map.py",
)
assert _SPEC_HCDM and _SPEC_HCDM.loader
_hcdm_mod = importlib.util.module_from_spec(_SPEC_HCDM)
_SPEC_HCDM.loader.exec_module(_hcdm_mod)
BLDG_CONTRACT_TOWN_TO_HDB_TOWN = _hcdm_mod.BLDG_CONTRACT_TOWN_TO_HDB_TOWN
hdb_town_from_contract_code = _hcdm_mod.hdb_town_from_contract_code


def test_expected_contract_codes_count_and_csv_coverage():
    assert len(BLDG_CONTRACT_TOWN_TO_HDB_TOWN) == 27

    csv_path = _REPO_ROOT / "data" / "HDBPropertyInformation.csv"
    if not csv_path.is_file():
        pytest.skip("Optional source dataset data/HDBPropertyInformation.csv is not included")
    df = pd.read_csv(csv_path, usecols=["bldg_contract_town"])
    codes = sorted({str(x).strip().upper() for x in df["bldg_contract_town"].dropna().unique()})
    assert codes == sorted(BLDG_CONTRACT_TOWN_TO_HDB_TOWN.keys())


@pytest.mark.parametrize(
    ("code", "town"),
    [
        ("BD", "BEDOK"),
        ("CT", "CENTRAL AREA"),
        ("KWN", "KALLANG/WHAMPOA"),
        ("TG", "TENGAH"),
        ("AMK", "ANG MO KIO"),
    ],
)
def test_hdb_town_from_contract_code_samples(code: str, town: str) -> None:
    assert hdb_town_from_contract_code(code) == town
    assert hdb_town_from_contract_code(code.lower()) == town


def test_unknown_contract_raises() -> None:
    with pytest.raises(ValueError, match="Unknown bldg_contract_town"):
        hdb_town_from_contract_code("ZZZ")


def test_blk_street_first_row_matches_onemap_formula() -> None:
    csv_path = _REPO_ROOT / "data" / "HDBPropertyInformation.csv"
    if not csv_path.is_file():
        pytest.skip("Optional source dataset data/HDBPropertyInformation.csv is not included")
    df = pd.read_csv(csv_path, nrows=1)
    row = df.iloc[0]
    blk_no = str(row["blk_no"]).strip().upper()
    street_raw = str(row["street"]).strip()
    blk_street = f"{blk_no} {normalize_street(street_raw)}"
    assert blk_street == "1 BEACH ROAD"

