"""HDB resale town harmonisation mirrored for modelling/training inference.

Must stay aligned with ``backend/hdb_resale_town_geo.normalize_hdb_town_label`` (training joins).
"""


def normalize_hdb_town_label(raw: str | None) -> str:
    if raw is None:
        return ""
    return " ".join(str(raw).strip().upper().split())
