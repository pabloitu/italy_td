"""Write forecast-only runs (runs/<name>/config.yml + models.yml) from the root config.yml and models.yml.

A run creates forecasts only: no tests, no plots, run_mode parallel, force_rerun False. Sequence runs
point to the shared ../../models/<name>; full_* runs to ../../models_full/<name> (a separate clone,
same <name>_image), so the full run never reuses or overwrites a sequence forecast. Runs sharing a
folder skip windows another run already made. Region, input catalog, catalog
and model arguments come from the root files; only n_sims, the window and the threads are set here.

ETAS-type models (vetas, fletas, petai) fit on absolute dates in their args.json (timewindow_start,
auxiliary_start). For every run they are set relative to the run start: timewindow_start = start -
fit_years, auxiliary_start = timewindow_start - aux_years, both clipped at the catalog start
(2005-04-16). Same values for every window of the run.

Presets (daily UTC windows, end date exclusive):
  pilot     2016-06-15, 2016-08-25, 2016-10-30, 2016-10-31 (quiet, sequence, busiest days)
  aquila    2009-03-01 to 2009-06-09   L'Aquila (rules: 2009-03-01 + 100 days)
  emilia    2012-05-01 to 2012-08-09   Emilia
  amatrice  2016-08-01 to 2017-02-01   Amatrice-Visso-Norcia-Campotosto
  full_2010 .. full_2020   Jan 1 to Jan 1 of the next year   full run, one run per year
  full_2021                2021-01-01 to 2021-06-29          (catalog ends 2021-06-28 22:58)

usage: python scripts/prepare_runs.py amatrice --workers 64 [--threads 1] [--nsims 100000]
       python scripts/prepare_runs.py full_2016 full_2017 --workers 96
                                      [--models vetas inlabru_td] [--fit-years 4 --aux-years 2]
                                      [--start ... --end ...]
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

root = Path(__file__).resolve().parents[1]
PRESETS = {
    "pilot": ["2016-06-15", "2016-08-25", "2016-10-30", "2016-10-31"],
    "aquila": ("2009-03-01", "2009-06-09"),
    "emilia": ("2012-05-01", "2012-08-09"),
    "amatrice": ("2016-08-01", "2017-02-01"),
}
PRESETS.update({f"full_{y}": (f"{y}-01-01", f"{y + 1}-01-01") for y in range(2010, 2021)})
PRESETS["full_2021"] = ("2021-01-01", "2021-06-29")
THREAD_KEYS = ("n_jobs", "n_cores")
FIT_MODELS = ("vetas", "fletas", "petai")
CAT_START = datetime(2005, 4, 16)

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("runs", nargs="+", help=f"presets: {', '.join(PRESETS)}")
p.add_argument("--nsims", type=int, default=100000)
p.add_argument("--threads", type=int, default=1, help="n_jobs / n_cores per container (keys already in models.yml)")
p.add_argument("--workers", type=int, default=None, help="containers at once (default min(cores, 32))")
p.add_argument("--models", nargs="+", help="subset of the root models.yml (default: all with a giturl except mock*)")
p.add_argument("--fit-years", type=float, default=4, help="ETAS models: fit window before the run start")
p.add_argument("--aux-years", type=float, default=2, help="ETAS models: auxiliary window before the fit window")
p.add_argument("--start")
p.add_argument("--end")
a = p.parse_args()

cfg0 = yaml.safe_load((root / "config.yml").read_text())
models0 = yaml.safe_load((root / "models.yml").read_text())
cat = pd.read_csv(root / cfg0["catalog"], usecols=["time_string"])
cat_end = pd.to_datetime(cat["time_string"], format="ISO8601").max()

err = 0
for run in a.runs:
    if run not in PRESETS and not (a.start and a.end):
        sys.exit(f"unknown run {run}: use a preset or give --start and --end")
    pre = PRESETS.get(run, (a.start, a.end))
    tc = {"horizon": "1days", "exp_class": "td"}
    if isinstance(pre, list):
        days = [datetime.fromisoformat(i) for i in pre]
        tc["time_windows"] = [[d, d + timedelta(days=1)] for d in days]
        t0, t1 = days[0], days[-1] + timedelta(days=1)
    else:
        t0 = datetime.fromisoformat(a.start or pre[0])
        t1 = datetime.fromisoformat(a.end or pre[1])
        tc["start_date"], tc["end_date"] = t0, t1
    if a.workers:
        tc["concurrent_tasks"] = a.workers
    nwin = len(tc["time_windows"]) if "time_windows" in tc else (t1 - t0).days

    if cat_end < t1 - timedelta(days=1):
        print(f"ERROR {run}: catalog {cfg0['catalog']} ends {cat_end:%Y-%m-%d}, run ends {t1:%Y-%m-%d}")
        err += 1

    ms = []
    for m in models0:
        name = next(iter(m)); e = dict(m[name])
        if a.models and name not in a.models:
            continue
        if not a.models and (not e.get("giturl") or "TODO" in str(e.get("giturl")) or name.startswith("mock")):
            continue
        if e.get("build") != "docker":
            print(f"WARNING {run}/{name}: build is {e.get('build')}, parallel runs need docker")
        mdir = "models_full" if run.startswith("full_") else "models"
        e["path"] = str(Path("../..") / mdir / Path(e["path"]).name)
        kw = dict(e.get("func_kwargs") or {})
        kw["n_sims"] = a.nsims
        for k in THREAD_KEYS:
            if k in kw:
                kw[k] = a.threads
        if name in FIT_MODELS:
            fit0 = max(t0 - timedelta(days=365.25 * a.fit_years), CAT_START)
            aux0 = max(fit0 - timedelta(days=365.25 * a.aux_years), CAT_START)
            kw["timewindow_start"] = f"{fit0:%Y-%m-%d} 00:00:00"
            kw["auxiliary_start"] = f"{aux0:%Y-%m-%d} 00:00:00"
            yrs = (t0 - fit0).days / 365.25
            print(f"  {name}: fit {fit0:%Y-%m-%d} to run start ({yrs:.1f} yr), auxiliary from {aux0:%Y-%m-%d}"
                  + ("  WARNING: less than 1 year of fit data" if yrs < 1 else ""))
        e["func_kwargs"] = kw
        ms.append({name: e})
    if not ms:
        sys.exit("no models selected")

    cfg = {
        "name": f"Italy TD forecasts, {run}",
        "time_config": tc,
        "region_config": cfg0["region_config"],
        "input_config": cfg0["input_config"],
        "catalog": str(Path("../..") / cfg0["catalog"]),
        "model_config": "models.yml",
        "run_dir": "results",
        "force_rerun": False,
        "run_mode": "parallel",
        "postprocess": {"plot_catalog": False, "plot_forecasts": False},
    }
    d = root / "runs" / run
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    (d / "models.yml").write_text(yaml.safe_dump(ms, sort_keys=False))
    w = a.workers or min(os.cpu_count() or 1, 32)
    print(f"{run}: {nwin} windows {t0:%Y-%m-%d} to {t1:%Y-%m-%d}, models {[next(iter(m)) for m in ms]}, "
          f"n_sims {a.nsims}, {w} containers x {a.threads} threads, forecasts in "
          f"{'models_full' if run.startswith('full_') else 'models'}/ -> runs/{run}/")
sys.exit(1 if err else 0)
