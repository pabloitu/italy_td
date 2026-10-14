"""Convergence of forecast metrics with the number of catalogs, from existing forecast files.

For each n in --nsims and each block of n catalogs (catalog ids b*n .. (b+1)*n - 1, at most --blocks
disjoint blocks out of the n_sims in the file), on the days --start..--end of a run: the expected
number of M >= mag_min events (mean count per catalog), the N-test quantiles, the daily log-score
ll = ll_n + ll_s + ll_m as in scripts/scores_td.py (zero counts floored at one catalog / event) and the
fraction of cells with no simulated event. Sums over the days are written per (n, block).

Writes runs/<run>/results/convergence_<model>.csv (one row per n, block and day).

usage: python scripts/convergence.py amatrice vetas [--start 2016-08-24] [--end 2016-09-03]
       [--nsims 100 200 500 1000 2000 5000 10000 20000 50000 100000] [--blocks 10]
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from csep.core import regions

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("run")
p.add_argument("model")
p.add_argument("--start", default="2016-08-24")
p.add_argument("--end", default="2016-09-03")
p.add_argument("--nsims", type=int, nargs="+", default=[100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000])
p.add_argument("--blocks", type=int, default=10)
a = p.parse_args()

d = root / "runs" / a.run
cfg = yaml.safe_load((d / "config.yml").read_text())
v = next(m[a.model] for m in yaml.safe_load((d / cfg["model_config"]).read_text()) if a.model in m)
rc = cfg["region_config"]
mmin = rc["mag_min"] - 1e-6
dm = rc.get("mag_bin", 0.1)
nb = int(round((rc["mag_max"] - rc["mag_min"]) / dm)) + 1
reg = getattr(regions, rc["region"])()
ntot = v["func_kwargs"]["n_sims"]
fd = (d / v["path"] / "forecasts").resolve()
pre = v.get("prefix", a.model)


def mbin(m):
    return np.clip(np.floor((np.asarray(m) - rc["mag_min"]) / dm + 1e-6).astype(int), 0, nb - 1)


cat = pd.read_csv((d / cfg["catalog"]).resolve())
cat = cat[(cat.mag >= mmin) & (cat.depth >= rc.get("depth_min", 0)) & (cat.depth < rc.get("depth_max", 1e9))]
cat = cat[~reg.get_masked(cat.lon.to_numpy(), cat.lat.to_numpy())]
cat["day"] = cat.time_string.str[:10]

rows = []
t = datetime.fromisoformat(a.start)
while t < datetime.fromisoformat(a.end):
    s, e = t, t + timedelta(days=1)
    t = e
    f = fd / f"{pre}_{s:%Y-%m-%d}_{e:%Y-%m-%d}.csv"
    if not f.exists():
        print(f"missing {f.name}")
        continue
    df = pd.read_csv(f, usecols=["lon", "lat", "mag", "catalog_id"])
    df = df[(df.mag >= mmin) & ~reg.get_masked(df.lon.to_numpy(), df.lat.to_numpy())]
    cid = df.catalog_id.to_numpy().astype(int)
    cell = reg.get_index_of(df.lon.to_numpy(), df.lat.to_numpy())
    mb = mbin(df.mag)
    o = cat[cat.day == f"{s:%Y-%m-%d}"]
    oc = reg.get_index_of(o.lon.to_numpy(), o.lat.to_numpy()) if len(o) else np.zeros(0, int)
    om = mbin(o.mag) if len(o) else np.zeros(0, int)
    k = len(oc)
    for n in a.nsims:
        for b in range(min(a.blocks, ntot // n)):
            sel = (cid >= b * n) & (cid < (b + 1) * n)
            cnt = np.bincount(cid[sel] - b * n, minlength=n)[:n]
            tot = sel.sum()
            hit = (cnt == k).sum()
            ll_n = np.log(max(hit, 1) / n)
            sc = np.bincount(cell[sel], minlength=reg.num_nodes)
            if k and tot:
                ll_s = np.log(np.maximum(sc[oc], 1) / tot).sum()
                ll_m = np.log(np.maximum(np.bincount(mb[sel], minlength=nb)[om], 1) / tot).sum()
            else:
                ll_s, ll_m = -k * np.log(reg.num_nodes), -k * np.log(nb)
            rows.append({"n": n, "block": b, "day": f"{s:%Y-%m-%d}", "obs": k, "mean": cnt.mean(),
                         "d1": (cnt >= k).mean(), "d2": (cnt <= k).mean(), "ll_n": ll_n, "ll_s": ll_s,
                         "ll_m": ll_m, "ll": ll_n + ll_s + ll_m, "empty_cells": (sc == 0).mean(),
                         "floored_obs": int((sc[oc] == 0).sum()) if k else 0})
    print(f"{s:%Y-%m-%d}: {k} observed, {len(df)} simulated events")

res = pd.DataFrame(rows)
out = d / "results" / f"convergence_{a.model}.csv"
res.to_csv(out, index=False, float_format="%.6g")
g = res.groupby(["n", "block"])[["mean", "ll", "floored_obs"]].sum().groupby("n").agg(["mean", "std"])
print(g.round(3).to_string())
print(f"-> {out}")
