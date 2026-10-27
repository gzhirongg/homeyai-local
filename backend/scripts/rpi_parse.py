"""Shared parsing for HDB Resale Price Index CSV (quarter, index columns)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_MONTH_START = {1: 1, 2: 4, 3: 7, 4: 10}


@dataclass(frozen=True)
class RpiRow:
    quarter_label: str
    year: int
    quarter_num: int
    period_start: date
    index_value: float


def parse_quarter_and_index(quarter_raw: object, index_raw: object) -> RpiRow:
    ql = str(quarter_raw).strip()
    m = _QUARTER_RE.match(ql)
    if not m:
        raise ValueError(f"invalid quarter label: {quarter_raw!r}")

    yr, qn = int(m.group(1)), int(m.group(2))
    try:
        v = float(index_raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"invalid index for {ql}: {index_raw!r}") from e
    if v <= 0 or v != v:  # NaN
        raise ValueError(f"index must be positive for {ql}: {index_raw!r}")

    ps = date(yr, _MONTH_START[qn], 1)
    return RpiRow(
        quarter_label=ql,
        year=yr,
        quarter_num=qn,
        period_start=ps,
        index_value=round(v, 2),
    )


def load_normalized_rpi_rows(csv_path: Path) -> tuple[list[RpiRow], pd.DataFrame]:
    """Read CSV with quarter/index (case-insensitive headers), validate, sort by period."""
    df = pd.read_csv(csv_path)
    lc = {str(c).lower().strip(): c for c in df.columns}
    if "quarter" not in lc or "index" not in lc:
        raise ValueError(f"{csv_path} must have quarter and index columns; got {list(df.columns)!r}")

    qcol, icol = lc["quarter"], lc["index"]
    rows: list[RpiRow] = []
    for idx, (_, r) in enumerate(df.iterrows()):
        try:
            rows.append(parse_quarter_and_index(r[qcol], r[icol]))
        except ValueError as e:
            raise ValueError(f"row {idx + 2} (after header): {e}") from e

    ctr = Counter(x.quarter_label for x in rows)
    dup = {lbl for lbl, n in ctr.items() if n > 1}
    if dup:
        raise ValueError(f"duplicate quarter_label(s): {sorted(dup)}")

    rows.sort(key=lambda r: r.period_start)
    out_df = pd.DataFrame(
        {
            "quarter": [r.quarter_label for r in rows],
            "index": [r.index_value for r in rows],
        }
    )
    return rows, out_df


def dataframe_to_normalized_csv_bytes(out_df: pd.DataFrame) -> bytes:
    return out_df.to_csv(index=False).encode("utf-8")
