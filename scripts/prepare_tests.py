"""Write a floatCSEP test run (runs/<run>_tests/) on the forecasts of an existing forecast run.

Same models, paths, region, catalogs and n_sims as runs/<run>/, plus a test config, so floatCSEP
finds every forecast on disk (force_rerun False) and only evaluates and plots. Results go to
runs/<run>_tests/results/<window>/{evaluations,figures}/. With --days only those windows are tested.

usage: python scripts/prepare_tests.py emilia [--tests tests_n.yml] [--days 2012-05-20 2012-05-29]
                                       [--workers 20] [--plots] [--out emilia_nslm]
then:  cd runs/emilia_tests && TZ=UTC floatcsep run config.yml
--plots also maps the observed catalog and every forecast (expected rates per cell) per window.
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("run")
p.add_argument("--tests", default="tests_n.yml", help="test config in the repo top folder")
p.add_argument("--days", nargs="+", help="test only these daily windows (YYYY-MM-DD)")
p.add_argument("--workers", type=int)
p.add_argument("--plots", action="store_true", help="plot catalog and forecast maps per window")
p.add_argument("--out", help="name of the test run folder (default <run>_tests)")
a = p.parse_args()

src = root / "runs" / a.run
cfg = yaml.safe_load((src / "config.yml").read_text())
ms = yaml.safe_load((src / cfg["model_config"]).read_text())
tc = cfg["time_config"]
if a.days:
    days = [datetime.fromisoformat(d) for d in a.days]
    tc = {"horizon": tc["horizon"], "exp_class": tc["exp_class"],
          "time_windows": [[d, d + timedelta(days=1)] for d in days]}
tc.pop("concurrent_tasks", None)
if a.workers:
    tc["concurrent_tasks"] = a.workers
cfg.update({
    "name": f"{cfg['name']} - tests",
    "time_config": tc,
    "test_config": f"../../{a.tests}",
    "run_mode": "parallel",
    "force_rerun": False,
    "postprocess": {"plot_catalog": a.plots, "plot_forecasts": a.plots},
})
name = a.out or f"{a.run}_tests"
d = root / "runs" / name
d.mkdir(parents=True, exist_ok=True)
(d / "config.yml").write_text(yaml.safe_dump(cfg, sort_keys=False))
(d / "models.yml").write_text(yaml.safe_dump(ms, sort_keys=False))
n = len(tc["time_windows"]) if "time_windows" in tc else (tc["end_date"] - tc["start_date"]).days
print(f"runs/{name}/: {n} windows, models {[next(iter(m)) for m in ms]}, tests {a.tests}")
print(f"run:  cd runs/{name} && TZ=UTC floatcsep run config.yml")
