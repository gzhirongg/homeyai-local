"""Load HDB training frames from Postgres or MinIO manifest parquets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from modelling.config.minio_sources import load_minio_sources_dict, resolve_object
from modelling.storage import minio_io


@dataclass
class LoaderConfig:
    project_root: Path
    parquet_minio: bool = False
    use_database: bool = True
    min_tx_month: str | None = None
    merge_masterplan_landuse_parquet: bool | None = None


def _apply_min_tx_month(df: pd.DataFrame, min_tx_month: str | None) -> pd.DataFrame:
    if not min_tx_month or "month" not in df.columns:
        return df
    cutoff = str(min_tx_month).strip()
    if not cutoff:
        return df
    return df[df["month"].astype(str) >= cutoff].copy()


def _merge_sidecar(
    base: pd.DataFrame,
    side: pd.DataFrame,
    *,
    left_addr: str,
    left_month: str,
    right_addr: str,
    right_month: str,
) -> pd.DataFrame:
    if side.empty:
        return base
    right = side.copy()
    if right_addr in right.columns and right_addr != left_addr:
        right = right.rename(columns={right_addr: left_addr})
    if right_month in right.columns and right_month != left_month:
        right = right.rename(columns={right_month: left_month})
    if not {left_addr, left_month}.issubset(base.columns) or not {left_addr, left_month}.issubset(right.columns):
        return base
    extra = [c for c in right.columns if c not in (left_addr, left_month)]
    if not extra:
        return base
    merged = base.merge(
        right[[left_addr, left_month, *extra]],
        on=[left_addr, left_month],
        how="left",
        suffixes=("", "_sidecar"),
    )
    dup = [c for c in merged.columns if c.endswith("_sidecar")]
    if dup:
        merged = merged.drop(columns=dup)
    return merged


def _load_parquet_manifest_frame(cfg: dict[str, Any], loader: LoaderConfig) -> pd.DataFrame:
    resale_bk = resolve_object(cfg, "training_hdb_resale_parquet")
    df = minio_io.load_parquet_dataframe(resale_bk.bucket, resale_bk.key)

    mrt_path = ""
    try:
        mrt_bk = resolve_object(cfg, "mrt_features_parquet")
        mrt_df = minio_io.load_parquet_dataframe(mrt_bk.bucket, mrt_bk.key)
        mrt_path = f"minio:{mrt_bk.bucket}/{mrt_bk.key}"
        if {"hdb_addr_id", "tx_year_month"}.issubset(mrt_df.columns):
            df = _merge_sidecar(
                df,
                mrt_df,
                left_addr="enriched_addr_id",
                left_month="month",
                right_addr="hdb_addr_id",
                right_month="tx_year_month",
            )
        elif {"enriched_addr_id", "month"}.issubset(mrt_df.columns):
            df = _merge_sidecar(
                df,
                mrt_df,
                left_addr="enriched_addr_id",
                left_month="month",
                right_addr="enriched_addr_id",
                right_month="month",
            )
    except KeyError:
        pass

    merge_mp = loader.merge_masterplan_landuse_parquet
    if merge_mp is None:
        merge_mp = True
    if merge_mp:
        try:
            mp_bk = resolve_object(cfg, "masterplan_landuse_pit_parquet")
            mp_df = minio_io.load_parquet_dataframe(mp_bk.bucket, mp_bk.key)
            if {"enriched_addr_id", "revision_year"}.issubset(mp_df.columns) and "month" in df.columns:
                mp_df = mp_df.sort_values("revision_year").drop_duplicates(
                    subset=["enriched_addr_id"], keep="last"
                )
                mp_cols = [c for c in mp_df.columns if c not in ("enriched_addr_id", "revision_year")]
                df = df.merge(
                    mp_df[["enriched_addr_id", *mp_cols]],
                    on="enriched_addr_id",
                    how="left",
                    suffixes=("", "_mp_dup"),
                )
                dup = [c for c in df.columns if c.endswith("_mp_dup")]
                if dup:
                    df = df.drop(columns=dup)
        except KeyError:
            pass

    _ = mrt_path  # reserved for describe_training_source enrichment
    return df


def load_training_frame(loader: LoaderConfig) -> pd.DataFrame:
    """Postgres full join (default) or manifest-backed MinIO parquets."""
    if loader.parquet_minio or not loader.use_database:
        cfg = load_minio_sources_dict(loader.project_root)
        df = _load_parquet_manifest_frame(cfg, loader)
    else:
        from modelling.training_db import load_hdb_resale_dataframe_from_db

        df = load_hdb_resale_dataframe_from_db()
    return _apply_min_tx_month(df, loader.min_tx_month)


def describe_training_source(loader: LoaderConfig) -> tuple[str, str]:
    """Human label and URI for metrics / reports."""
    if loader.parquet_minio or not loader.use_database:
        try:
            cfg = load_minio_sources_dict(loader.project_root)
            bk = resolve_object(cfg, "training_hdb_resale_parquet")
            return "parquet_minio", f"minio:{bk.bucket}/{bk.key}"
        except Exception:
            return "parquet_minio", "minio:manifest-unresolved"
    return "postgresql", "postgresql:hdb_resale_training_view"
