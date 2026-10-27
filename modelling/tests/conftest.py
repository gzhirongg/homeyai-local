"""Ensure modelling tests resolve the package from the repo root (never add ``modelling/`` to sys.path)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
s = str(_REPO_ROOT)
if s not in sys.path:
    sys.path.insert(0, s)
