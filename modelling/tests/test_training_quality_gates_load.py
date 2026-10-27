from pathlib import Path

from modelling.data.quality import load_quality_gates


def test_load_quality_gates_default_and_yaml(tmp_path: Path, monkeypatch):
    root = tmp_path / "proj"
    (root / "modelling" / "config").mkdir(parents=True)
    yml = root / "modelling" / "config" / "training_quality_gates.yml"
    yml.write_text(
        "base:\n  enabled: false\nmrt:\n  snapshot_hit_rate_min: 0.9\n",
        encoding="utf-8",
    )
    g = load_quality_gates(root)
    assert g["base"]["enabled"] is False
    assert g["mrt"]["snapshot_hit_rate_min"] == 0.9

    monkeypatch.setenv("HOMEYAI_DQ_mrt__snapshot_hit_rate_min", "0.88")
    g2 = load_quality_gates(root)
    assert g2["mrt"]["snapshot_hit_rate_min"] == 0.88
