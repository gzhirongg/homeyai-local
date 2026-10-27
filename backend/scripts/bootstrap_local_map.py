#!/usr/bin/env python3
"""Populate map overlays in the isolated local database from archived public data.

MRT locations require an exact name match between the LTA exits layer and the
archived OneMap station registry downloaded by bootstrap_local_valuation.py.
No opening/announcement dates or operational status are guessed from geometry.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(Path(__file__).resolve().parent)]
from bootstrap_local_valuation import ADDRESS_URL, require_local_database

DATASETS = {
    "regions": "d_bf4d24df9129d5a8ff8cf82e20959ee0",
    "planning": "d_4765db0e87b9c86336792efe8a1f7a66",
    "mrt_exits": "d_b39d3a0871985372d7e1637193335da5",
}
LINES = {
    "NS": "North-South Line", "EW": "East-West Line", "CG": "East-West Line",
    "NE": "North East Line", "CC": "Circle Line", "CE": "Circle Line",
    "DT": "Downtown Line", "TE": "Thomson-East Coast Line",
}


def station_name(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s+MRT STATION$", "", value.strip().upper()))


def station_rows(exits: dict, addresses: list[dict]) -> tuple[list[dict], list[str]]:
    """One physical location per MRT station; exclude LRT and unmatched names."""
    known_exits = defaultdict(list)
    for feature in exits["features"]:
        name = feature["properties"]["STATION_NA"]
        if "LRT STATION" not in name:
            known_exits[station_name(name)].append(feature["geometry"]["coordinates"])
    coded = defaultdict(dict)
    for row in addresses:
        match = re.fullmatch(r"(.+?) MRT STATION \(([A-Z0-9 /]+)\)", row["name"])
        if not match:
            continue
        name = station_name(match[1])
        if name not in known_exits:
            continue
        lon, lat = float(row["lon"]), float(row["lat"])
        if not (103.5 < lon < 104.2 and 1.1 < lat < 1.6):
            raise ValueError(f"Invalid station coordinates for {name}")
        # Require location agreement, not only a same-name text match.
        if not any((lon-x)**2 + (lat-y)**2 < 0.01**2 for x, y in known_exits[name]):
            raise ValueError(f"Station {name} is more than 1 km from every published exit")
        for code in match[2].replace(" ", "").split("/"):
            prefix = re.sub(r"\d+$", "", code)
            if prefix in LINES and re.fullmatch(r"[A-Z]+\d+", code):
                coded[name][code] = (lon, lat, LINES[prefix])
    rows = []
    for name, codes in sorted(coded.items()):
        coords = list(codes.values())
        rows.append({"name": name, "lon": sum(c[0] for c in coords)/len(coords),
                     "lat": sum(c[1] for c in coords)/len(coords),
                     "codes": {code: values[2] for code, values in sorted(codes.items())}})
    return rows, sorted(known_exits.keys() - coded.keys())


def download_assets() -> tuple[dict[str, Path], dict]:
    from minio import Minio
    from minio.error import S3Error
    directory = ROOT / "data"
    directory.mkdir(exist_ok=True)
    paths, provenance = {}, {}
    for name, dataset in DATASETS.items():
        path = directory / f"{name}.geojson"
        if not path.exists():
            for attempt in range(12):
                response = requests.get(f"https://api-open.data.gov.sg/v1/public/api/datasets/{dataset}/poll-download", timeout=45)
                url = response.json().get("data", {}).get("url")
                if url:
                    response = requests.get(url, timeout=180)
                    response.raise_for_status()
                    # Validate before accepting a cache entry.
                    if response.json().get("type") != "FeatureCollection":
                        raise ValueError(f"Invalid GeoJSON for {dataset}")
                    partial = path.with_suffix(".part")
                    partial.write_bytes(response.content)
                    partial.replace(path)
                    break
                time.sleep(12)
            else:
                raise RuntimeError(f"Download unavailable for {dataset}")
            time.sleep(12)
        paths[name] = path
        provenance[name] = {"source": f"https://data.gov.sg/datasets/{dataset}/view", "dataset_id": dataset}
    paths["station_codes"] = directory / "OneMapAddresses20260215.csv"
    if not paths["station_codes"].exists():
        response = requests.get(ADDRESS_URL, timeout=180)
        response.raise_for_status()
        paths["station_codes"].write_bytes(response.content)
    provenance["station_codes"] = {"source": ADDRESS_URL, "snapshot_date": "2026-02-15"}
    client = Minio(os.environ["MINIO_ENDPOINT"], access_key=os.environ["MINIO_ACCESS_KEY"],
                   secret_key=os.environ["MINIO_SECRET_KEY"], secure=False)
    for name, path in paths.items():
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        key = f"raw/local_bootstrap/map/{name}/{digest}/{path.name}"
        try:
            client.stat_object("datasets", key)
        except S3Error as exc:
            if exc.code != "NoSuchKey":
                raise
            client.put_object("datasets", key, io.BytesIO(content), len(content))
        provenance[name].update(sha256=digest, object_key=key, bytes=len(content))
    return paths, provenance


def main() -> None:
    require_local_database()
    from sqlalchemy import func
    from models import SessionLocal, UraRegion, UraPlanningArea, MrtPhysicalStation, MrtStationLine
    paths, provenance = download_assets()
    geo = {name: json.loads(path.read_text()) for name, path in paths.items() if path.suffix == ".geojson"}
    with paths["station_codes"].open() as handle:
        stations, unmatched = station_rows(geo["mrt_exits"], list(csv.DictReader(handle)))
    if len(geo["regions"]["features"]) != 5 or len(geo["planning"]["features"]) != 55 or len(stations) < 140:
        raise ValueError("Unexpected map coverage; refusing partial import")
    with SessionLocal() as db:
        # Upsert preserves IDs and any independently enriched MRT dates/routes.
        for name, model, code_field, mapping in (
            ("regions", UraRegion, "region_c", {"region_n": "REGION_N", "region_c": "REGION_C"}),
            ("planning", UraPlanningArea, "pln_area_c", {"pln_area_n": "PLN_AREA_N", "pln_area_c": "PLN_AREA_C", "region_c": "REGION_C"}),
        ):
            for feature in geo[name]["features"]:
                values = {field: feature["properties"][prop] for field, prop in mapping.items()}
                if not all(values.values()):
                    raise ValueError("Boundary has missing identifiers")
                row = db.query(model).filter(getattr(model, code_field) == values[code_field]).one_or_none()
                if row is None:
                    row = model()
                    db.add(row)
                for key, value in values.items():
                    setattr(row, key, value)
                geometry = func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(feature["geometry"])), 4326)
                row.geom = func.ST_Multi(geometry) if name == "regions" else geometry
        for item in stations:
            physical = db.query(MrtPhysicalStation).filter_by(canonical_name=item["name"]).one_or_none()
            if physical is None:
                physical = MrtPhysicalStation(canonical_name=item["name"], lat=item["lat"], long=item["lon"],
                    geom=func.ST_SetSRID(func.ST_MakePoint(item["lon"], item["lat"]), 4326),
                    is_interchange=len(set(item["codes"].values())) > 1)
                db.add(physical)
                db.flush()
            for code, line in item["codes"].items():
                if db.query(MrtStationLine).filter_by(station_code=code).first():
                    continue
                db.add(MrtStationLine(physical_station_id=physical.id, station_name=item["name"],
                    station_code=code, network_line=line, derived_state="UNKNOWN", found=1,
                    code_source_type="archived_onemap", dates_source_type="unavailable",
                    source_url=provenance["mrt_exits"]["source"],
                    source_note="Local map: archived OneMap station coordinates/codes, corroborated by LTA exits. Opening/status history unavailable; future stations omitted."))
        db.commit()
    report = {"imported_at": datetime.now(timezone.utc).isoformat(), "sources": provenance,
              "regions": 5, "planning_areas": 55, "mrt_physical_stations": len(stations),
              "mrt_line_entries": sum(len(s["codes"]) for s in stations), "unmatched_mrt_names": unmatched,
              "limitation": "Station location snapshot only. No invented opening dates/status; planned stations not included."}
    (ROOT / "data" / "local_map_provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "sources"}, indent=2))


if __name__ == "__main__":
    main()
