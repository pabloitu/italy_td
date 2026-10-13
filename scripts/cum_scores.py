"""Cumulative daily log-scores and information gain against a reference model, from scores.csv files.

Combines runs/<run>/results/scores.csv of several runs (scripts/scores_td.py; copy them from the other
servers first), keeps the days within --start..--end and adds, per model, the cumulative sums of the
daily log-likelihood (ll and its parts ll_n, ll_s, ll_m) and the cumulative information gain
IG = sum(ll_model - ll_ref) over the days both have. The same model and day in two files must have the
same scores (a sequence run and the full run have different batch-1 forecasts: do not mix them).

Writes runs/<out>/results/cumulative/: cumulative.csv, cumulative.png (IG total, number, spatial,
magnitude) and one <model>.json per model in pyCSEP result format (test_distribution = days,
observed_statistic = cumulative IG; ll and parts in extra keys).

usage: python scripts/cum_scores.py OUT RUN [RUN ...] [--start 2012-05-01] [--end 2012-08-09] [--ref vetas]
   e.g. python scripts/cum_scores.py emilia_all emilia full_b2_2012 --start 2012-05-01 --end 2012-08-09
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("out")
p.add_argument("runs", nargs="+")
p.add_argument("--start")
p.add_argument("--end", help="exclusive")
p.add_argument("--ref", default="vetas")
a = p.parse_args()

dfs = []
for r in a.runs:
    f = root / "runs" / r / "results" / "scores.csv"
    if not f.exists():
        raise SystemExit(f"missing {f}")
    dfs.append(pd.read_csv(f).assign(src=r))
df = pd.concat(dfs)
if a.start:
    df = df[df.day >= a.start]
if a.end:
    df = df[df.day < a.end]
parts = ["ll", "ll_n", "ll_s", "ll_m"]
dup = df[df.duplicated(["model", "day"], keep=False)]
if len(dup):
    bad = dup.groupby(["model", "day"])[parts].agg(lambda x: x.max() - x.min()).max(axis=1) > 1e-6
    if bad.any():
        raise SystemExit(f"different scores for the same model and day, e.g.\n{dup.head(6)}")
    df = df.drop_duplicates(["model", "day"])
models = list(dict.fromkeys(df.model))
df = df.sort_values("day")
if a.ref not in models:
    raise SystemExit(f"reference {a.ref} not in {models}")
days = sorted(df.day.unique())

ref = df[df.model == a.ref].set_index("day")[parts]
out = []
for m in models:
    g = df[df.model == m].set_index("day")
    for c in parts:
        g[f"cum_{c}"] = g[c].cumsum()
    common = g.index.intersection(ref.index)
    ig = (g.loc[common, parts] - ref.loc[common]).cumsum()
    for c in parts:
        g[f"ig_{c}"] = ig[c].reindex(g.index).ffill()
    out.append(g.reset_index())
    miss = len(days) - len(g)
    print(f"{m:20s} days {len(g):5d}{f' (missing {miss})' if miss else '':16s} ll {g.ll.sum():10.1f}  "
          f"IG vs {a.ref} {ig.ll.iloc[-1] if len(ig) else np.nan:9.1f} (n {ig.ll_n.iloc[-1] if len(ig) else np.nan:8.1f}"
          f" s {ig.ll_s.iloc[-1] if len(ig) else np.nan:8.1f} m {ig.ll_m.iloc[-1] if len(ig) else np.nan:7.1f})"
          f"  floored {int(g.nfloor.sum())}")
res = pd.concat(out)

od = root / "runs" / a.out / "results" / "cumulative"
od.mkdir(parents=True, exist_ok=True)
res.drop(columns="src").to_csv(od / "cumulative.csv", index=False, float_format="%.6g")
for m, g in res.groupby("model", sort=False):
    js = {"name": "Cumulative information gain", "sim_name": m, "obs_name": a.ref, "obs_catalog_repr": None,
          "quantile": None, "observed_statistic": g.ig_ll.round(4).tolist(), "test_distribution": g.day.tolist(),
          "status": "normal", "min_mw": None, "type": "CumulativeInformationGain",
          "cum_ll": g.cum_ll.round(4).tolist(), "cum_ll_n": g.cum_ll_n.round(4).tolist(),
          "cum_ll_s": g.cum_ll_s.round(4).tolist(), "cum_ll_m": g.cum_ll_m.round(4).tolist(),
          "ig_ll_n": g.ig_ll_n.round(4).tolist(), "ig_ll_s": g.ig_ll_s.round(4).tolist(),
          "ig_ll_m": g.ig_ll_m.round(4).tolist(), "obs": g.obs.astype(int).tolist()}
    (od / f"{m}.json").write_text(json.dumps(js).replace("NaN", "null"))

# figure
fig, ax = plt.subplots(4, 1, figsize=(10, 11), sharex=True)
for m, g in res.groupby("model", sort=False):
    t = pd.to_datetime(g.day)
    for i, (c, lab) in enumerate(zip(parts, ["total", "number", "spatial", "magnitude"])):
        ax[i].plot(t, g[f"ig_{c}"], lw=1.2, label=m)
        ax[i].set_ylabel(f"IG {lab}")
obs = res[res.model == a.ref]
for i in range(4):
    ax[i].axhline(0, c="k", lw=0.5)
    for t in pd.to_datetime(obs.day[obs.obs >= 5]):
        ax[i].axvline(t, c="0.85", lw=0.6, zorder=0)
ax[0].legend(fontsize=8, ncol=4)
ax[0].set_title(f"{a.out}: cumulative log-likelihood gain vs {a.ref} (grey: days with >= 5 events)")
fig.tight_layout()
fig.savefig(od / "cumulative.png", dpi=130)
print(f"-> {od}")
