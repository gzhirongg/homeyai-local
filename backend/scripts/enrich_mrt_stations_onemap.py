"""
Enrich MRT station CSV with lat/long from OneMap elastic search.

Requires ONEMAP_EMAIL and ONEMAP_PASSWORD in the environment (see backend .env).
Uses pandas and requests; `onemap_service` is loaded by file path so you do not need
the full backend stack (SQLAlchemy, etc.) in the interpreter.

Usage (from repo root):
    python backend/scripts/enrich_mrt_stations_onemap.py
    python backend/scripts/enrich_mrt_stations_onemap.py --limit 5
    python backend/scripts/enrich_mrt_stations_onemap.py --input data/foo.csv --output data/foo_enriched.csv

Coordinates are written only when OneMap returns exactly one result (accuracy over completeness).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
_REPO_ROOT = _BACKEND_DIR.parent

for _env_candidate in [_BACKEND_DIR / ".env", _REPO_ROOT / ".env"]:
    if _env_candidate.exists():
        for _line in _env_candidate.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                k, _, v = _line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        break

# Load OneMapService without importing backend.services (package __init__ pulls heavy deps).
_om_spec = importlib.util.spec_from_file_location(
    "onemap_service", _BACKEND_DIR / "services" / "onemap_service.py"
)
_om_mod = importlib.util.module_from_spec(_om_spec)
assert _om_spec.loader is not None
_om_spec.loader.exec_module(_om_mod)
OneMapService = _om_mod.OneMapService  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_INPUT = _REPO_ROOT / "data" / "Full_MRT_Stn_List_caaApr2026_ChatGPT.csv"
DEFAULT_OUTPUT = _REPO_ROOT / "data" / "Full_MRT_Stn_List_caaApr2026_onemap_enriched.csv"


def _norm(s: object) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip()
    return t


def _build_search_term(code: object, name: object) -> tuple[str | None, str | None]:
    c, n = _norm(code), _norm(name)
    if not c or not n:
        return None, None
    return f"{c} {n}", None


def _extract_coords(single: dict) -> tuple[float | None, float | None]:
    try:
        lat = float(single.get("LATITUDE"))
        lon = float(single.get("LONGITUDE"))
        return lat, lon
    except (TypeError, ValueError):
        return None, None


def enrich_row(
    service: OneMapService,
    station_code: object,
    station_name: object,
) -> dict:
    """Return lat, long, search_term, found, api_response for one logical station row."""
    search_term, skip_reason = _build_search_term(station_code, station_name)
    if search_term is None:
        return {
            "lat": None,
            "long": None,
            "search_term": "",
            "found": 0,
            "api_response": json.dumps({"skipped": skip_reason or "missing_code_or_name"}),
        }

    try:
        resp = service.search_address(search_term, include_raw=True)
    except Exception as exc:
        logger.warning("OneMap search failed for %r: %s", search_term, exc)
        return {
            "lat": None,
            "long": None,
            "search_term": search_term,
            "found": 0,
            "api_response": json.dumps({"error": str(exc), "search_term": search_term}),
        }

    results = resp.get("results") or []
    found = int(resp.get("found", 0))
    raw = resp.get("raw")
    api_payload = raw if isinstance(raw, dict) else {"results": results, "found": found}

    if found == 1 and len(results) == 1:
        lat, lon = _extract_coords(results[0])
        return {
            "lat": lat,
            "long": lon,
            "search_term": search_term,
            "found": found,
            "api_response": json.dumps(api_payload, ensure_ascii=False),
        }

    return {
        "lat": None,
        "long": None,
        "search_term": search_term,
        "found": found,
        "api_response": json.dumps(api_payload, ensure_ascii=False),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Enrich MRT CSV with OneMap lat/long.")
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input CSV path")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output CSV path")
    p.add_argument("--limit", type=int, default=None, help="Process at most N rows (after start)")
    p.add_argument("--start-row", type=int, default=0, help="0-based row offset into data rows")
    p.add_argument("--sleep", type=float, default=0.0, help="Extra seconds to sleep after each API call")
    args = p.parse_args()

    df = pd.read_csv(args.input)
    if args.start_row:
        df = df.iloc[args.start_row :].reset_index(drop=True)
    if args.limit is not None:
        df = df.iloc[: args.limit].copy()

    service = OneMapService(logger=logger)

    lats: list[float | None] = []
    longs: list[float | None] = []
    terms: list[str] = []
    founds: list[int] = []
    responses: list[str] = []

    for idx, row in df.iterrows():
        out = enrich_row(service, row.get("station_code"), row.get("station_name"))
        lats.append(out["lat"])
        longs.append(out["long"])
        terms.append(out["search_term"])
        founds.append(out["found"])
        responses.append(out["api_response"])
        if args.sleep > 0:
            time.sleep(args.sleep)
        if (idx + 1) % 25 == 0:
            logger.info("Processed %s rows …", idx + 1)

    df["lat"] = lats
    df["long"] = longs
    df["search_term"] = terms
    df["found"] = founds
    df["api_response"] = responses

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    logger.info("Wrote %s (%s rows)", args.output, len(df))


if __name__ == "__main__":
    main()
