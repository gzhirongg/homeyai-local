"""TCP / outbound probes for training (especially Modal) — fail fast on unreachable infra."""

from __future__ import annotations

import logging
import os
import socket
from typing import Any

from modelling.storage.minio_io import normalize_minio_endpoint

logger = logging.getLogger(__name__)

_DEFAULT_TCP_TIMEOUT_S = float(os.getenv("HOMEYAI_NETWORK_PROBE_TIMEOUT_S", "8"))


def _parse_host_port(endpoint: str) -> tuple[str, int]:
    ep = normalize_minio_endpoint(endpoint)
    if not ep:
        raise ValueError("MINIO_ENDPOINT is empty")
    if "://" in ep:
        raise ValueError(
            "MINIO_ENDPOINT must be host:port (no scheme); use MINIO_SECURE for HTTPS."
        )
    if ":" not in ep:
        return ep, 9000
    host, _, port_s = ep.rpartition(":")
    host = host.strip()
    if host.startswith("["):
        raise ValueError("Bracket IPv6 in MINIO_ENDPOINT is not supported by this probe.")
    try:
        return host.strip(), int(port_s.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid MINIO_ENDPOINT port in {endpoint!r}") from exc


def probe_tcp(host: str, port: int, *, timeout_s: float, purpose: str) -> None:
    """Raise RuntimeError if TCP connect fails within ``timeout_s``."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        err = sock.connect_ex((host, int(port)))
        if err != 0:
            raise OSError(f"connect_ex errno={err}")
    except OSError as exc:
        raise RuntimeError(
            f"Network probe failed ({purpose}): cannot reach {host}:{port} within {timeout_s}s "
            f"({exc}). Check firewall, public bind on VM, MINIO_ENDPOINT, or Modal egress rules."
        ) from exc
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _postgres_tcp_target() -> tuple[str, int] | None:
    raw = (os.getenv("DATABASE_URL_READ_ONLY") or "").strip()
    if raw:
        try:
            from sqlalchemy.engine.url import make_url

            u = make_url(raw)
            if u.host:
                return str(u.host), int(u.port or 5432)
        except Exception:
            logger.warning(
                "Could not parse DATABASE_URL_READ_ONLY for Postgres TCP probe; "
                "skipping DB host probe.",
                exc_info=True,
            )
    host = (os.getenv("DB_HOST") or os.getenv("REMOTE_VM_IP") or "").strip()
    if not host:
        return None
    port_s = (os.getenv("DB_PORT") or os.getenv("DB_INNER_PORT") or "5432").strip()
    try:
        return host, int(port_s)
    except ValueError:
        return None


def probe_https_head(url: str, *, timeout_s: float, purpose: str) -> tuple[bool, str]:
    """Return (ok, detail); never raises — used for optional macro-source probes."""
    try:
        import requests

        resp = requests.head(url, timeout=timeout_s, allow_redirects=True)
        if resp.status_code < 400:
            return True, f"HTTP {resp.status_code}"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        logger.debug("%s: HEAD %s failed", purpose, url, exc_info=True)
        return False, f"{type(exc).__name__}: {exc}"


def run_modal_preflight_checks(
    *,
    tcp_timeout_s: float | None = None,
    skip_minio_tcp_probe: bool = False,
) -> None:
    """Run before loading snapshots / DB-heavy engineering inside Modal.

    - Probes ``MINIO_ENDPOINT`` TCP unless ``skip_minio_tcp_probe=True`` (dataset supplied via gRPC).
      Upload paths still use MinIO — skipping the probe only defers failure until upload if unreachable.
    - Probes Postgres TCP only when ``HOMEYAI_MODAL_PROBE_POSTGRES=1`` (not default).
    - Optionally probes public macro endpoints when ``HOMEYAI_PROBE_PUBLIC_APIS=1`` (informational).
    """
    timeout = tcp_timeout_s if tcp_timeout_s is not None else _DEFAULT_TCP_TIMEOUT_S

    if not skip_minio_tcp_probe:
        endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000").strip()
        host, port = _parse_host_port(endpoint)
        probe_tcp(host, port, timeout_s=timeout, purpose="MinIO/S3 endpoint")
    else:
        logger.info("Skipping MinIO TCP preflight (dataset loaded via parquet passthrough)")

    probe_pg = os.getenv("HOMEYAI_MODAL_PROBE_POSTGRES", "").lower() in ("1", "true", "yes")
    if probe_pg:
        pg = _postgres_tcp_target()
        if pg:
            probe_tcp(pg[0], pg[1], timeout_s=timeout, purpose="Postgres read-only host")
    elif _postgres_tcp_target():
        logger.debug(
            "Postgres TCP probe skipped — set HOMEYAI_MODAL_PROBE_POSTGRES=1 to enable fail-fast DB checks"
        )

    if os.getenv("HOMEYAI_PROBE_PUBLIC_APIS", "").lower() in ("1", "true", "yes"):
        gov_ok, gov_d = probe_https_head(
            "https://data.gov.sg",
            timeout_s=min(timeout, 10.0),
            purpose="data.gov.sg",
        )
        logger.info("Outbound probe data.gov.sg: ok=%s detail=%s", gov_ok, gov_d)

        mas_key = (os.getenv("MAS_API_KEY") or "").strip()
        if mas_key:
            mas_ok, mas_d = probe_https_head(
                "https://eservices.mas.gov.sg",
                timeout_s=min(timeout, 10.0),
                purpose="MAS API gateway",
            )
            logger.info("Outbound probe eservices.mas.gov.sg: ok=%s detail=%s", mas_ok, mas_d)
        else:
            logger.info(
                "MAS_API_KEY unset — macro rates column falls back to zero unless "
                "MinIO macro_interest_csv exists."
            )


def training_macro_sources_summary(project_root: Any) -> dict[str, Any]:
    """Which macro paths avoid live HTTP (call log-only helpers before engineer)."""
    from pathlib import Path

    root = Path(project_root).resolve()
    out: dict[str, Any] = {"volume_cached_minio": False, "rpi_cached_minio": False, "ir_cached_minio": False}

    try:
        from modelling.features.macro_sentiment import (
            _csv_macro_from_minio,
            _volume_from_minio_manifest,
        )

        mq = _volume_from_minio_manifest(root)
        out["volume_cached_minio"] = mq is not None and len(mq) > 0
        out["rpi_cached_minio"] = _csv_macro_from_minio(root, "macro_rpi_csv") is not None
        out["ir_cached_minio"] = _csv_macro_from_minio(root, "macro_interest_csv") is not None
    except Exception:
        logger.warning("macro_sources_summary skipped", exc_info=True)

    return out

