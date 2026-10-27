"""Map HDB Property Information ``bldg_contract_town`` codes to resale ``town`` labels.

Official dataset uses ~3-letter building contract-town codes aligned with planning-area
short codes where applicable (e.g. BD → Bedok resale town).

Source catalogue: ``data.gov.sg`` HDB Property Information
(``source_resource_id`` ``d_17f5382f26140b1fdae0ba2ef6239d2f``).
"""

from __future__ import annotations

# Stable mapping for all codes observed through 2026 dataset snapshots.
BLDG_CONTRACT_TOWN_TO_HDB_TOWN: dict[str, str] = {
    "AMK": "ANG MO KIO",
    "BB": "BUKIT BATOK",
    "BD": "BEDOK",
    "BH": "BISHAN",
    "BM": "BUKIT MERAH",
    "BP": "BUKIT PANJANG",
    "BT": "BUKIT TIMAH",
    "CCK": "CHOA CHU KANG",
    "CL": "CLEMENTI",
    "CT": "CENTRAL AREA",
    "GL": "GEYLANG",
    "HG": "HOUGANG",
    "JE": "JURONG EAST",
    "JW": "JURONG WEST",
    "KWN": "KALLANG/WHAMPOA",
    "MP": "MARINE PARADE",
    "PG": "PUNGGOL",
    "PRC": "PASIR RIS",
    "QT": "QUEENSTOWN",
    "SB": "SEMBAWANG",
    "SGN": "SENGKANG",
    "SK": "SERANGOON",
    "TAP": "TAMPINES",
    "TG": "TENGAH",
    "TP": "TOA PAYOH",
    "WL": "WOODLANDS",
    "YS": "YISHUN",
}


def hdb_town_from_contract_code(code: str | None) -> str:
    """Resolve building contract-town code (e.g. ``BD``) to HDB resale town name."""
    if not code or not str(code).strip():
        raise ValueError("bldg_contract_town must be non-empty")
    normalized = str(code).strip().upper()
    try:
        return BLDG_CONTRACT_TOWN_TO_HDB_TOWN[normalized]
    except KeyError as e:
        raise ValueError(f"Unknown bldg_contract_town: {normalized!r}") from e
