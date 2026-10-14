"""Long-term (stationary) rate of each ETAS-type model, for display: fit once on a long catalog and
simulate one long window, written as a normal forecast run (runs/<run>/, models in models_bg/).

The catalog (e.g. HORUS 1960-2020, column M) is converted to data/<stem>_csep.csv (column mag) and
cut at --end (default 2005-04-16, start of ISIDe). One window from --end to --end + --years, n_sims
catalogs (default 100 x 100 years = 10,000 years). The models fit on the catalog before --end:
vetas/fletas/petai from --fit-start (auxiliary from the catalog start), simpletas2 with fit_years
and aux_years over the same span, etes has no fit; inversion completeness mc = --mc for all.
The forecasts continue the real history: scripts/fast_export.py --bg skips the first --skip years.
Forecast and test results of the experiment are not touched (own folders, own run).

usage: python scripts/prepare_bg.py data/horus.csv [--models vetas fletas ...] [--run bg_horus]
       [--years 100] [--nsims 100] [--mc 3.5] [--fit-start 1970-01-01] [--threads 8]
then:  scripts/run_forecasts.sh bg_horus
"""
import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("catalog")
p.add_argument("--models", nargs="+", default=["vetas", "fletas", "petai", "simpletas2_hom", "simpletas2_nonhom", "etes"])
p.add_argument("--run", default="bg_horus")
p.add_argument("--end", default="2005-04-16")
p.add_argument("--years", type=int, default=100)
p.add_argument("--nsims", type=int, default=100)
p.add_argument("--mc", type=float, default=3.5)
p.add_argument("--fit-start", default="1970-01-01")
p.add_argument("--workers", type=int, default=8)
p.add_argument("--threads", type=int, default=8, help="n_jobs / n_cores per model (output independent of it)")
a = p.parse_args()

# catalog in CSEP format, before --end
src = Path(a.catalog)
c = pd.read_csv(src).rename(columns={"M": "mag"})
t = pd.to_datetime(c.time_string, format="ISO8601")
c = c[t < pd.Timestamp(a.end)].copy()
c["event_id"] = c["event_id"].fillna(pd.Series(range(len(c)), index=c.index)).astype(str)
c["catalog_id"] = -1
cat = root / "data" / f"{src.stem}_csep.csv"
c[["lon", "lat", "mag", "time_string", "depth", "catalog_id", "event_id"]].to_csv(cat, index=False)
t0 = pd.to_datetime(c.time_string, format="ISO8601").min()
print(f"{cat}: {len(c)} events {t0:%Y-%m-%d} .. {a.end}")

cfg0 = yaml.safe_load((root / "config.yml").read_text())
models0 = {next(iter(m)): m[next(iter(m))] for m in yaml.safe_load((root / "models.yml").read_text())}
start = datetime.fromisoformat(a.end)
end = start.replace(year=start.year + a.years)
span = (start - datetime.fromisoformat(a.fit_start)).days / 365.25
ms = []
for name in a.models:
    if name not in models0:
        print(f"skip {name}: not in models.yml")
        continue
    e = dict(models0[name])
    e["path"] = str(Path("../..") / "models_bg" / Path(e["path"]).name)
    kw = dict(e.get("func_kwargs") or {})
    kw.update({"n_sims": a.nsims, "mc": a.mc})
    for k in ("n_jobs", "n_cores"):
        if k in kw:
            kw[k] = a.threads
    if name in ("vetas", "fletas", "petai"):
        kw["timewindow_start"] = f"{a.fit_start} 00:00:00"
        kw["auxiliary_start"] = f"{t0:%Y-%m-%d} 00:00:00"
    if name.startswith("simpletas2"):
        kw["fit_years"] = round(span, 2)
        kw["aux_years"] = round((datetime.fromisoformat(a.fit_start) - t0.to_pydatetime()).days / 365.25, 2)
    e["func_kwargs"] = kw
    ms.append({name: e})

cfg = {
    "name": f"Long-term rates ({src.stem}, {a.years} yr x {a.nsims})",
    "time_config": {"horizon": "1days", "exp_class": "td", "time_windows": [[start, end]],
                    "concurrent_tasks": a.workers},
    "region_config": cfg0["region_config"],
    "input_config": cfg0["input_config"],
    "catalog": str(Path("../..") / cat.relative_to(root)),
    "model_config": "models.yml",
    "run_dir": "results",
    "force_rerun": False,
    "run_mode": "parallel",
    "postprocess": {"plot_catalog": False, "plot_forecasts": False},
}
d = root / "runs" / a.run
d.mkdir(parents=True, exist_ok=True)
(d / "config.yml").write_text(yaml.safe_dump(cfg, sort_keys=False))
(d / "models.yml").write_text(yaml.safe_dump(ms, sort_keys=False))
print(f"runs/{a.run}: window {start:%Y-%m-%d} .. {end:%Y-%m-%d}, {a.nsims} catalogs, mc {a.mc}, "
      f"models {[next(iter(m)) for m in ms]} in models_bg/")
print(f"run:  scripts/run_forecasts.sh {a.run}")
