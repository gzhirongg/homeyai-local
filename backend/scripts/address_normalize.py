"""Lightweight street normalisation shared by OneMap geocoding and HDB ingest.

Kept standalone so ingest/backfill utilities do not import ``engineer_postal_codes``
(which pulls Prefect / OneMap and optional PDF stack transitively).
"""

from __future__ import annotations

import re


def normalize_street(street: str) -> str:
    """Expand common HDB street shorthands to improve OneMap search and match results."""
    street_u = street.upper()
    street_u = re.sub(r"\bST\.", "SAINT ", street_u)

    replacements = {
        r"\bKG\b": "KAMPONG",
        r"\bTG\b": "TANJONG",
        r"\bUPP\b": "UPPER",
        r"\bST\b": "STREET",
        r"\bC'WEALTH\b": "COMMONWEALTH",
        r"\bRD\b": "ROAD",
        r"\bAVE\b": "AVENUE",
        r"\bCL\b": "CLOSE",
        r"\bDR\b": "DRIVE",
        r"\bBT\b": "BUKIT",
        r"\bJLN\b": "JALAN",
        r"\bLOR\b": "LORONG",
        r"\bCRES\b": "CRESCENT",
        r"\bGDNS\b": "GARDENS",
        r"\bPK\b": "PARK",
        r"\bPL\b": "PLACE",
        r"\bHTS\b": "HEIGHTS",
        r"\bCTRL\b": "CENTRAL",
        r"\bTER\b": "TERRACE",
        r"\bNTH\b": "NORTH",
        r"\bSTH\b": "SOUTH",
        r"\bEST\b": "ESTATE",
    }
    for pattern, rep in replacements.items():
        street_u = re.sub(pattern, rep, street_u)

    street_u = re.sub(r"\s+", " ", street_u)
    return street_u.strip()


# Backwards-compatible alias used across scripts
_normalize_street = normalize_street
