"""Shared stdout logging for training runs (Modal, Prefect worker, CLI)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


def configure_training_logging(
    *,
    force: bool = True,
    source: str | None = None,
) -> None:
    """Ensure INFO logs go to stderr with timestamps (Modal containers have no prior config).

    When ``source`` is set (e.g. ``"MODAL"``, ``"PREFECT"``), every line is prefixed with
    ``[SOURCE]`` so Prefect UI logs that mix worker + streamed Modal output stay readable.
    Falls back to env ``HOMEYAI_LOG_SOURCE`` when ``source`` is omitted.
    """
    level_name = (os.getenv("HOMEYAI_TRAINING_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    tag = (source or os.getenv("HOMEYAI_LOG_SOURCE") or "").strip().upper()
    if tag:
        fmt = f"%(asctime)s %(levelname)s [{tag}] [%(name)s] %(message)s"
    else:
        fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        force=force,
    )

    if level > logging.DEBUG:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("botocore").setLevel(logging.WARNING)


class _PrefectPrefixAdapter(logging.LoggerAdapter):
    """Prefix messages from ``get_run_logger()`` without changing Prefect's handler setup."""

    def process(self, msg: object, kwargs: dict[str, Any]) -> tuple[object, dict[str, Any]]:
        prefix = str(self.extra.get("log_prefix") or "PREFECT").strip().upper()
        if prefix and isinstance(msg, str):
            tag = f"[{prefix}] "
            if not msg.startswith(tag):
                msg = tag + msg
        return msg, kwargs


def prefect_training_logger(prefix: str = "PREFECT") -> logging.LoggerAdapter:
    """Prefect run logger with a ``[PREFIX]`` tag on each message."""
    from prefect import get_run_logger

    return _PrefectPrefixAdapter(get_run_logger(), {"log_prefix": prefix.strip().upper()})


def training_logger(name: str) -> logging.Logger:
    """Namespaced logger under ``homeyai.training``."""
    return logging.getLogger(f"homeyai.training.{name}")


def _fmt_fields(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for k, v in sorted(fields.items(), key=lambda kv: kv[0]):
        if v is None:
            continue
        parts.append(f"{k}={v}")
    return " ".join(parts)


def log_phase(logger: logging.Logger, phase: str, **fields: Any) -> None:
    """Single-line structured INFO message."""
    logger.info("phase=%s %s", phase, _fmt_fields(fields))


def phase_dict(phase: str, **fields: Any) -> dict[str, Any]:
    """Same message shape as :func:`log_phase`, as a dict for Modal generator streaming."""
    rest = _fmt_fields(fields)
    msg = f"phase={phase} {rest}" if rest else f"phase={phase}"
    return {"level": "INFO", "msg": msg}


def make_log_yielder() -> Callable[..., dict[str, Any]]:
    """Return a callable that builds ``{level, msg}`` dicts for Modal ``yield`` streaming."""

    def _yield_log(level: str, msg: str, **fields: Any) -> dict[str, Any]:
        extra = _fmt_fields(fields)
        full = f"{msg} {extra}".strip() if extra else msg
        return {"level": str(level).upper(), "msg": full}

    return _yield_log


@contextmanager
def log_elapsed(logger: logging.Logger, phase: str, **fields: Any) -> Iterator[None]:
    t0 = time.perf_counter()
    log_phase(logger, f"{phase}_start", **fields)
    try:
        yield
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        log_phase(logger, f"{phase}_done", **fields, elapsed_s=elapsed)
