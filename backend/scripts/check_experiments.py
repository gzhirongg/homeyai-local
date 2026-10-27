import json
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent.parent
exp_dir = repo_root / "modelling" / "experiments"

runs = []
for p in exp_dir.iterdir():
    if not p.is_dir(): continue
    try:
        conf = p / "config.json"
        metrics = p / "metrics.json"
        params = p / "best_params.json"
        run_data = {"id": p.name}
        if conf.exists(): run_data["config"] = json.loads(conf.read_text())
        if metrics.exists(): run_data["metrics"] = json.loads(metrics.read_text())
        if params.exists(): run_data["best_params"] = json.loads(params.read_text())
        runs.append(run_data)
    except Exception as e:
        print(e)
print(json.dumps(runs, indent=2))
