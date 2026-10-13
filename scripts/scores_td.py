"""Daily log-scores of a forecast run, computed from the forecast catalogs, split into number, spatial
and magnitude parts.

For each model and daily window, with S catalogs (n_sims), simulated events restricted to the test
region and M >= mag_min, and the observed events of the day (region, magnitude and depth of
region_config):
  ll_n  log P(N = n_obs): fraction of catalogs with exactly n_obs events
  ll_s  sum over observed events of log(n_c / n_tot), n_c simulated events in the event's cell
  ll_m  sum over observed events of log(n_b / n_tot), n_b simulated events in the event's magnitude bin
  ll    ll_n + ll_s + ll_m, log-likelihood of the observed day under the catalog forecast
Zero counts are floored at one simulated catalog or event (probability 1/S, 1/n_tot); with no simulated
event at all the spatial and magnitude parts are uniform. nfloor counts the floored terms.
Also writes the N-test numbers of ntest_quick.py (mean, q025, q975, p_zero, d1, d2).

Run where the forecasts are; every forecast file is read once. Missing files are skipped.
Writes runs/<run>/results/scores.csv; combine runs with scripts/cum_scores.py.

usage: python scripts/scores_td.py full_2016 [--models vetas petai] [--workers 16]
"""
import argparse
from datetime import timedelta
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from csep.core import regions

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("run")
p.add_argument("--models", nargs="+")
p.add_argument("--workers", type=int, default=8)
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
dm = rc.get("mag_bin", 0.1)
nb = int(round((rc["mag_max"] - rc["mag_min"]) / dm)) + 1
reg = getattr(regions, rc["region"])()


def mbin(m):
    return np.clip(np.floor((np.asarray(m) - rc["mag_min"]) / dm + 1e-6).astype(int), 0, nb - 1)


# observed events per day: cell and magnitude bin
cat = pd.read_csv((d / cfg["catalog"]).resolve())
cat = cat[(cat.mag >= mmin) & (cat.depth >= rc.get("depth_min", 0)) & (cat.depth < rc.get("depth_max", 1e9))]
cat = cat[~reg.get_masked(cat.lon.to_numpy(), cat.lat.to_numpy())]
cat["day"] = cat.time_string.str[:10]
obs = {day: (reg.get_index_of(g.lon.to_numpy(), g.lat.to_numpy()), mbin(g.mag)) for day, g in cat.groupby("day")}
none = (np.zeros(0, int), np.zeros(0, int))


def score(job):
    name, f, day, n = job
    if not f.exists():
        return None
    df = pd.read_csv(f, usecols=["lon", "lat", "mag", "catalog_id"])
    df = df[df.mag >= mmin]
    df = df[~reg.get_masked(df.lon.to_numpy(), df.lat.to_numpy())]
    cnt = np.bincount(df.catalog_id.to_numpy().astype(int), minlength=n)[:n]
    oc, om = obs.get(day, none)
    k = len(oc)
    nf = 0
    hit = (cnt == k).sum()
    nf += hit == 0
    ll_n = np.log(max(hit, 1) / n)
    tot = len(df)
    if k and tot:
        sc = np.bincount(reg.get_index_of(df.lon.to_numpy(), df.lat.to_numpy()), minlength=reg.num_nodes)[oc]
        sm = np.bincount(mbin(df.mag), minlength=nb)[om]
        nf += (sc == 0).sum() + (sm == 0).sum()
        ll_s = np.log(np.maximum(sc, 1) / tot).sum()
        ll_m = np.log(np.maximum(sm, 1) / tot).sum()
    else:
        nf += 2 * k
        ll_s, ll_m = -k * np.log(reg.num_nodes), -k * np.log(nb)
    return {"model": name, "day": day, "obs": k, "mean": cnt.mean(), "q025": np.quantile(cnt, 0.025),
            "q975": np.quantile(cnt, 0.975), "p_zero": (cnt == 0).mean(), "d1": (cnt >= k).mean(),
            "d2": (cnt <= k).mean(), "ll_n": ll_n, "ll_s": ll_s, "ll_m": ll_m, "ll": ll_n + ll_s + ll_m,
            "nfloor": int(nf), "n_sims": n}


jobs = []
for m in ms:
    name = next(iter(m)); v = m[name]
    if a.models and name not in a.models:
        continue
    fd = (d / v["path"] / "forecasts").resolve()
    for s, e in wins:
        jobs.append((name, fd / f"{v.get('prefix', name)}_{s:%Y-%m-%d}_{e:%Y-%m-%d}.csv", f"{s:%Y-%m-%d}",
                     v["func_kwargs"]["n_sims"]))

with Pool(a.workers) as pool:
    rows = [r for r in pool.imap(score, jobs, chunksize=4) if r]
if not rows:
    raise SystemExit("no forecast files found")
res = pd.DataFrame(rows)
out = d / "results" / "scores.csv"
out.parent.mkdir(exist_ok=True)
res.to_csv(out, index=False, float_format="%.6g")

print(f"== {a.run}: {len(wins)} days, {sum(len(v[0]) for k, v in obs.items() if k in set(res.day))} observed events")
print(f"{'model':20s} {'days':>5s} {'missing':>7s} {'ll':>10s} {'ll_n':>9s} {'ll_s':>9s} {'ll_m':>9s} {'floored':>7s}")
for name, g in res.groupby("model", sort=False):
    print(f"{name:20s} {len(g):5d} {len(wins) - len(g):7d} {g.ll.sum():10.1f} {g.ll_n.sum():9.1f} "
          f"{g.ll_s.sum():9.1f} {g.ll_m.sum():9.1f} {g.nfloor.sum():7d}")
print(f"-> {out}")
