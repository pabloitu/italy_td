"""Quick N-test of a forecast run: forecast number distribution vs observed count, per day and model.

Reads runs/<run>/config.yml and models.yml, counts the events of every catalog in each forecast file
(M >= region_config mag_min) and the observed events of the day in the test region (region_config:
italy_csep_region, mag_min, depth_min..depth_max, catalog of the config). Same quantiles as the
catalog-based N-test: d1 = P(N >= obs), d2 = P(N <= obs); a day fails if d1 or d2 < 0.025.
Only reads files, no floatCSEP; missing forecast files are skipped.

Writes runs/<run>/results/ntest_quick.csv (one row per model and day) and prints a summary per model
and the days with M >= 4 events or a failed test.

usage: python scripts/ntest_quick.py emilia [--models vetas etas] [--all]
"""
import argparse
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from csep.core import regions

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("run")
p.add_argument("--models", nargs="+")
p.add_argument("--all", action="store_true", help="print every day, not only active or failed days")
a = p.parse_args()

d = root / "runs" / a.run
cfg = yaml.safe_load((d / "config.yml").read_text())
ms = yaml.safe_load((d / cfg["model_config"]).read_text())
tc, rc = cfg["time_config"], cfg["region_config"]
if tc.get("time_windows"):
    wins = [(w[0], w[1]) for w in tc["time_windows"]]
else:
    wins, t = [], tc["start_date"]
    while t < tc["end_date"]:
        wins.append((t, t + timedelta(days=1)))
        t += timedelta(days=1)
mmin = rc["mag_min"] - 1e-6

# observed events per day in the test region
reg = getattr(regions, rc["region"])()
cat = pd.read_csv((d / cfg["catalog"]).resolve())
cat["t"] = pd.to_datetime(cat["time_string"], format="ISO8601")
cat = cat[(cat["mag"] >= mmin) & (cat["depth"] >= rc.get("depth_min", 0)) & (cat["depth"] < rc.get("depth_max", 1e9))]
cat = cat[~reg.get_masked(cat["lon"].to_numpy(), cat["lat"].to_numpy())]
obs = {f"{s:%Y-%m-%d}": int(((cat["t"] >= s) & (cat["t"] < e)).sum()) for s, e in wins}

rows = []
for m in ms:
    name = next(iter(m)); v = m[name]
    if a.models and name not in a.models:
        continue
    pre = v.get("prefix", name)
    n = v["func_kwargs"]["n_sims"]
    fd = (d / v["path"] / "forecasts").resolve()
    for s, e in wins:
        f = fd / f"{pre}_{s:%Y-%m-%d}_{e:%Y-%m-%d}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, usecols=["mag", "catalog_id"])
        ids = df.loc[df["mag"] >= mmin, "catalog_id"].to_numpy().astype(int)
        cnt = np.bincount(ids, minlength=n)[:n]
        k = obs[f"{s:%Y-%m-%d}"]
        rows.append({"model": name, "day": f"{s:%Y-%m-%d}", "obs": k, "mean": cnt.mean(),
                     "q025": np.quantile(cnt, 0.025), "q975": np.quantile(cnt, 0.975), "max": cnt.max(),
                     "p_zero": (cnt == 0).mean(), "d1": (cnt >= k).mean(), "d2": (cnt <= k).mean()})

res = pd.DataFrame(rows)
if res.empty:
    raise SystemExit("no forecast files found")
res["pass"] = (res["d1"] >= 0.025) & (res["d2"] >= 0.025)
out = d / "results" / "ntest_quick.csv"
out.parent.mkdir(exist_ok=True)
res.to_csv(out, index=False, float_format="%.4g")

nobs = sum(obs.values())
print(f"== {a.run}: {len(wins)} days, {nobs} observed M>={rc['mag_min']} events in {rc['region']}")
print(f"{'model':18s} {'days':>5s} {'pass':>5s} {'sum fcst mean':>14s} {'sum obs':>8s} {'ratio':>6s}")
for name, g in res.groupby("model", sort=False):
    so = g["obs"].sum()
    print(f"{name:18s} {len(g):5d} {g['pass'].sum():5d} {g['mean'].sum():14.1f} {so:8d} "
          f"{g['mean'].sum() / so if so else float('nan'):6.2f}")

show = res if a.all else res[(res["obs"] > 0) | ~res["pass"]]
if len(show):
    print("\nday         obs  " + "  ".join(f"{n[:12]:>24s}" for n in res["model"].unique()))
    piv = {n: g.set_index("day") for n, g in res.groupby("model", sort=False)}
    for day in sorted(show["day"].unique()):
        cells = []
        for n, g in piv.items():
            if day in g.index:
                r = g.loc[day]
                cells.append(f"{r['mean']:7.2f} [{r['q025']:.0f}-{r['q975']:.0f}]{'' if r['pass'] else ' X':2s}")
            else:
                cells.append(f"{'-':>24s}")
        print(f"{day}  {obs[day]:>3}  " + "  ".join(f"{c:>24s}" for c in cells))
print(f"\nmean [2.5%-97.5%] of the forecast number per day; X = N-test fails (d1 or d2 < 0.025). Table: {out}")
