"""Static assets shared by valuation and training PDF templates (avoid importing WeasyPrint)."""

from __future__ import annotations

import base64
import os


def get_logo_base64() -> str:
    """Return the HomeyAI logo as a base64 PNG data URI, or ``\"\"`` if missing."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(script_dir, "..", "assets", "logo.png")

    if not os.path.exists(logo_path):
        return ""

    with open(logo_path, "rb") as logo_file:
        logo_data = base64.b64encode(logo_file.read()).decode("utf-8")

    return f"data:image/png;base64,{logo_data}"
