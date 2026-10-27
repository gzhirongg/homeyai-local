#!/usr/bin/env python3
"""Benchmark POST /api/valuation latency with ``debug_timings=true``.

Runs cold + warm repeats against a fixed postcode set and reports pass/fail
against the warm ``wall_ms`` gate (default 5000 ms).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "label": "Clementi",
        "payload": {
            "postal_code": "120601",
            "town": "CLEMENTI",
            "flat_type": "4 ROOM",
            "flat_model_grouped": "Model A",
            "region": "West",
            "storey_midpoint": 5,
            "floor_area_sqm": 90.0,
            "remaining_lease_years": 90,
        },
    },
    {
        "label": "Ang Mo Kio",
        "payload": {
            "postal_code": "560601",
            "town": "ANG MO KIO",
            "flat_type": "4 ROOM",
            "flat_model_grouped": "Model A",
            "region": "North",
            "storey_midpoint": 8,
            "floor_area_sqm": 93.0,
            "remaining_lease_years": 85,
        },
    },
    {
        "label": "Bedok",
        "payload": {
            "postal_code": "460022",
            "town": "BEDOK",
            "flat_type": "3 ROOM",
            "flat_model_grouped": "Improved",
            "region": "East",
            "storey_midpoint": 3,
            "floor_area_sqm": 67.0,
            "remaining_lease_years": 78,
        },
    },
    {
        "label": "Woodlands",
        "payload": {
            "postal_code": "730123",
            "town": "WOODLANDS",
            "flat_type": "5 ROOM",
            "flat_model_grouped": "Model A",
            "region": "North",
            "storey_midpoint": 10,
            "floor_area_sqm": 110.0,
            "remaining_lease_years": 92,
        },
    },
    {
        "label": "Pasir Ris",
        "payload": {
            "postal_code": "510123",
            "town": "PASIR RIS",
            "flat_type": "4 ROOM",
            "flat_model_grouped": "Model A",
            "region": "East",
            "storey_midpoint": 6,
            "floor_area_sqm": 88.0,
            "remaining_lease_years": 80,
        },
    },
]

_TIMING_KEYS = (
    "wall_ms",
    "resolve_addr_ms",
    "mrt_features_ms",
    "feature_extras_ms",
    "predict_ms",
    "amenities_ms",
    "shap_ms",
)


def _post_valuation(base_url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/valuation?debug_timings=true"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_cases(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return DEFAULT_CASES
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("cases file must be a JSON array")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default http://localhost:8000)",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=None,
        help="Optional JSON file with [{label, payload}, ...]",
    )
    parser.add_argument(
        "--warm-repeats",
        type=int,
        default=3,
        help="Warm repeats per postcode after first request (default 3)",
    )
    parser.add_argument(
        "--gate-ms",
        type=float,
        default=5000.0,
        help="Warm wall_ms pass threshold (default 5000)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP timeout per request in seconds (default 120)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write full results JSON",
    )
    args = parser.parse_args()

    try:
        cases = _load_cases(args.cases)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR loading cases: {exc}", file=sys.stderr)
        return 1

    results: list[dict[str, Any]] = []
    all_warm_walls: list[float] = []
    gate_failures: list[str] = []
    phase2_hints: dict[str, int] = {
        "mrt_function": 0,
        "feature_extras_high": 0,
        "predict_high": 0,
    }

    print(f"Benchmark POST /api/valuation @ {args.base_url}")
    print(f"Gate: warm wall_ms <= {args.gate_ms:.0f} ms\n")

    for case in cases:
        label = str(case.get("label") or case.get("postal_code") or "case")
        payload = case["payload"]
        case_runs: list[dict[str, Any]] = []

        for run_idx in range(1 + max(0, args.warm_repeats)):
            phase = "cold" if run_idx == 0 else "warm"
            t0 = time.perf_counter()
            try:
                data = _post_valuation(args.base_url, payload, timeout=args.timeout)
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                print(f"  [{label}] {phase} HTTP {exc.code}: {err_body[:300]}")
                return 1
            except urllib.error.URLError as exc:
                print(f"  [{label}] {phase} connection error: {exc.reason}")
                print("  Hint: start the API (uvicorn) and ensure the valuation model is loaded.")
                return 1

            elapsed_client = round((time.perf_counter() - t0) * 1000, 2)
            timings = data.get("_timings") or {}
            wall = float(timings.get("wall_ms") or elapsed_client)
            run_rec = {
                "phase": phase,
                "wall_ms": wall,
                "client_ms": elapsed_client,
                "timings": timings,
                "mrt_features_source": timings.get("mrt_features_source"),
                "feature_set_id": timings.get("feature_set_id"),
            }
            case_runs.append(run_rec)

            seg_parts = [
                f"wall={wall:.0f}ms",
                *(f"{k}={timings[k]}" for k in _TIMING_KEYS if k != "wall_ms" and k in timings),
            ]
            if timings.get("mrt_features_source"):
                seg_parts.append(f"mrt_src={timings['mrt_features_source']}")
            print(f"  [{label}] {phase}: " + " ".join(seg_parts))

            if phase == "warm":
                all_warm_walls.append(wall)
                if wall > args.gate_ms:
                    gate_failures.append(f"{label} wall_ms={wall:.0f}")
                if timings.get("mrt_features_source") == "function":
                    phase2_hints["mrt_function"] += 1
                if float(timings.get("feature_extras_ms") or 0) > 2000:
                    phase2_hints["feature_extras_high"] += 1
                if float(timings.get("predict_ms") or 0) > 2000:
                    phase2_hints["predict_high"] += 1

        warm_walls = [r["wall_ms"] for r in case_runs if r["phase"] == "warm"]
        summary = {
            "label": label,
            "runs": case_runs,
            "warm_p95_ms": max(warm_walls) if warm_walls else None,
            "warm_median_ms": statistics.median(warm_walls) if warm_walls else None,
        }
        results.append(summary)

    print("\n=== Summary ===")
    for s in results:
        print(
            f"  {s['label']}: warm median={s['warm_median_ms']:.0f}ms "
            f"p95={s['warm_p95_ms']:.0f}ms"
        )

    if all_warm_walls:
        overall_p95 = max(all_warm_walls)
        print(f"\nOverall warm p95 wall_ms: {overall_p95:.0f} ms")
    else:
        overall_p95 = None

    passed = overall_p95 is not None and overall_p95 <= args.gate_ms and not gate_failures
    if passed:
        print(f"\nPASS: warm wall_ms within {args.gate_ms:.0f} ms gate — Phase 2 not required.")
    else:
        print(f"\nFAIL: warm wall_ms exceeds {args.gate_ms:.0f} ms gate.")
        if gate_failures:
            print("  Slow cases:", ", ".join(gate_failures))
        print("  Phase 2 hints (warm runs):")
        print(f"    mrt_features_source=function: {phase2_hints['mrt_function']}")
        print(f"    feature_extras_ms > 2000:     {phase2_hints['feature_extras_high']}")
        print(f"    predict_ms > 2000:            {phase2_hints['predict_high']}")

    if args.json_out:
        out_doc = {
            "base_url": args.base_url,
            "gate_ms": args.gate_ms,
            "passed": passed,
            "overall_warm_p95_ms": overall_p95,
            "phase2_hints": phase2_hints,
            "cases": results,
        }
        args.json_out.write_text(json.dumps(out_doc, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")

    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
