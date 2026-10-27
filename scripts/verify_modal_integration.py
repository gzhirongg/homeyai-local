#!/usr/bin/env python3
"""Repeatable Modal integration checks (local terminal → Modal → MinIO).

Does not print secret values. Requires: pip install modal python-dotenv minio (repo venv).

Examples:
  python scripts/verify_modal_integration.py --phase modal-cli
  python scripts/verify_modal_integration.py --phase minio --env-file .env
  python scripts/verify_modal_integration.py --phase snapshot --env-file .env
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODAL_APP = REPO_ROOT / "modelling" / "modal_app.py"


def _dotenv_interpolated(env_file: Path) -> dict[str, str | None]:
    """Resolved ``.env`` values (same semantics as ``python-dotenv`` interpolation)."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return {}
    if not env_file.is_file():
        return {}
    return dotenv_values(env_file, interpolate=True)


def _pick_env(raw: dict[str, str | None], key: str, default: str = "") -> str:
    v = raw.get(key)
    if v not in (None, ""):
        return str(v).strip()
    return default


def _minio_host_port_endpoint(raw: dict[str, str | None]) -> str:
    ep = _pick_env(raw, "MINIO_ENDPOINT")
    if ep:
        return ep.split("://", 1)[-1].strip().rstrip("/") if "://" in ep else ep
    host = _pick_env(raw, "MINIO_HOST")
    port = _pick_env(raw, "MINIO_INNER_PORT", "9000")
    return f"{host}:{port}" if host else ""


def phase_modal_cli() -> int:
    print("== modal-cli: profile + deploy dry validation ==")
    r = subprocess.run(
        ["modal", "profile", "current"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print("FAIL modal profile current:", r.stderr.strip())
        return 1
    print("OK profile:", r.stdout.strip())
    src = MODAL_APP.read_text(encoding="utf-8")
    if ".add_local_dir" not in src:
        print("FAIL modal_app.py: missing add_local_dir")
        return 1
    i = src.find(".add_local_dir")
    tail_before_app = src[i : src.find("app = ", i)]
    if ".env(" in tail_before_app:
        print("FAIL modal_app.py: .env() must not appear after add_local_dir (Modal 1.4+)")
        return 1
    print("OK modal_app.py: image chain ends with add_local_dir (no trailing .env)")
    print("RUN manually: modal deploy modelling/modal_app.py")
    return 0


def phase_modal_secret_hint(env_file: Path, *, minio_host: str | None, model_env: str | None) -> int:
    print("== modal-secret egress hint (compare to modal secret create values) ==")
    raw = _dotenv_interpolated(env_file)
    if minio_host:
        host = minio_host.strip()
        me = (model_env or _pick_env(raw, "MODEL_ENV", "prod")).strip() or "prod"
    else:
        host = _pick_env(raw, "MINIO_HOST")
        port = _pick_env(raw, "MINIO_INNER_PORT", "9000")
        me = (_pick_env(raw, "MODEL_ENV", "prod").strip() or "prod")
        host_for_modal = f"{host}:{port}" if host else ""
        print("compose_ENDPOINT_reference", host_for_modal or "(unset)")
    if not host:
        print("WARN MINIO_HOST unset — Modal secret must still use reachable host:9000 (not Docker hostname `minio`)")
        return 0
    ok = host.lower() not in {"minio", "localhost", "127.0.0.1"}
    print("resolved_MINIO_HOST_for_reference", host)
    print("MODEL_ENV_reference", me)
    print("PASS_modal_should_not_use_docker_hostname_minio" if ok else "FAIL use VM/public/Tailscale IP in Modal secret MINIO_ENDPOINT")
    return 0 if ok else 1


def phase_minio_health(endpoint_host: str, port: str, timeout_sec: float) -> int:
    host = endpoint_host.strip()
    if not host:
        print("FAIL MINIO_HOST missing")
        return 1
    url = f"http://{host}:{port.strip()}/minio/health/live"
    print("GET", url)
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            code = resp.status
    except Exception as exc:
        print("FAIL MinIO health:", type(exc).__name__, exc)
        return 1
    ok = code == 200
    print("OK" if ok else "FAIL", "http_status", code)
    return 0 if ok else 1


def phase_snapshot(env_file: Path, *, endpoint: str | None, access_key: str | None, secret_key: str | None, secure: bool) -> int:
    print("== snapshot: datasets/training_snapshots/_latest.json ==", flush=True)
    try:
        from minio import Minio
    except ImportError:
        print("FAIL install minio: pip install minio")
        return 1
    raw = _dotenv_interpolated(env_file)
    ep = ak = sk = ""
    if endpoint and access_key and secret_key:
        ep = endpoint.strip().split("://", 1)[-1].strip().rstrip("/") if "://" in endpoint.strip() else endpoint.strip()
        ak = access_key.strip()
        sk = secret_key.strip()
    else:
        ep = _minio_host_port_endpoint(raw)
        ak = _pick_env(raw, "MINIO_ACCESS_KEY")
        sk = _pick_env(raw, "MINIO_SECRET_KEY")
        ms = _pick_env(raw, "MINIO_SECURE", "")
        if ms:
            secure = ms.lower() in ("1", "true", "yes")
    if not ep or not ak or not sk:
        print("FAIL missing MinIO endpoint or credentials (set env file or --minio-endpoint / *_ACCESS_KEY / *_SECRET_KEY)")
        return 1
    c = Minio(ep, access_key=ak, secret_key=sk, secure=secure)
    key = "training_snapshots/_latest.json"
    try:
        raw = c.get_object("datasets", key).read()
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        print("FAIL cannot read s3://datasets/", key, ":", exc)
        print("FIX run Prefect training-snapshot-default or export_training_snapshot_to_minio")
        return 1
    ver = str(doc.get("version") or "").strip()
    print("OK snapshot pointer version:", ver or repr(doc))
    if not ver:
        return 1
    resale = f"training_snapshots/{ver}/hdb_resale.parquet"
    try:
        c.stat_object("datasets", resale)
    except Exception as exc:
        print("FAIL missing", resale, exc)
        return 1
    print("OK parquet exists:", resale)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("modal-cli", "secret-hint", "minio", "snapshot", "all"), default="all")
    ap.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--minio-host", default="", help="Override MINIO host for secret-hint / minio (skip .env)")
    ap.add_argument("--minio-port", default="9000")
    ap.add_argument("--model-env", default="", help="Override MODEL_ENV for display")
    ap.add_argument("--minio-endpoint", default="", help="Override host:port for snapshot phase")
    ap.add_argument("--minio-access-key", default="")
    ap.add_argument("--minio-secret-key", default="")
    ap.add_argument("--minio-secure", action="store_true")
    args = ap.parse_args()
    raw_interp = _dotenv_interpolated(args.env_file)

    rc = 0
    if args.phase in ("modal-cli", "all"):
        rc |= phase_modal_cli()
    if args.phase in ("secret-hint", "all"):
        rc |= phase_modal_secret_hint(
            args.env_file,
            minio_host=args.minio_host or None,
            model_env=args.model_env or None,
        )
    if args.phase in ("minio", "all"):
        host = args.minio_host or _pick_env(raw_interp, "MINIO_HOST")
        port = args.minio_port or _pick_env(raw_interp, "MINIO_INNER_PORT", "9000")
        rc |= phase_minio_health(host, port, args.timeout)
    if args.phase in ("snapshot", "all"):
        ep = args.minio_endpoint.strip() if args.minio_endpoint else None
        ak = args.minio_access_key.strip() if args.minio_access_key else None
        sk = args.minio_secret_key.strip() if args.minio_secret_key else None
        rc |= phase_snapshot(
            args.env_file,
            endpoint=ep,
            access_key=ak,
            secret_key=sk,
            secure=args.minio_secure,
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
