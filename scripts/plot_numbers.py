"""Number of M >= mag_min events per day: forecast mean and 95% range per model, observed counts.

Reads runs/<run>/results/ntest_quick.csv (scripts/ntest_quick.py). If runs/<run>_tests/results
exists (floatCSEP N-test, scripts/prepare_tests.py), its quantiles are compared with ntest_quick and
the days tested by floatCSEP are marked. Writes runs/<run>/results/numbers.png.

usage: python scripts/plot_numbers.py emilia [--linear]
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("run")
p.add_argument("--linear", action="store_true", help="linear y axis (default symlog)")
a = p.parse_args()

d = root / "runs" / a.run / "results"
res = pd.read_csv(d / "ntest_quick.csv", parse_dates=["day"])
models = list(res["model"].unique())

# floatCSEP N-test results, if any
fc = []
for f in (root / "runs" / f"{a.run}_tests" / "results").glob("*/evaluations/Catalog_N-test_*.json"):
    r = json.loads(f.read_text())
    q = r.get("quantile")
    fc.append({"model": f.stem.replace("Catalog_N-test_", ""), "day": pd.Timestamp(f.parts[-3][:10]),
               "fc_obs": r.get("observed_statistic"), "fc_d1": q[0] if q else None, "fc_d2": q[1] if q else None})
if fc:
    cmp = pd.DataFrame(fc).merge(res, on=["model", "day"], how="left")
    cmp["same"] = ((cmp["fc_obs"] == cmp["obs"]) & ((cmp["fc_d1"] - cmp["d1"]).abs() < 1e-3)
                   & ((cmp["fc_d2"] - cmp["d2"]).abs() < 1e-3))
    print("floatCSEP N-test vs ntest_quick (observed count, d1, d2):")
    print(cmp.sort_values(["day", "model"])[["day", "model", "fc_obs", "obs", "fc_d1", "d1", "fc_d2", "d2", "same"]]
          .to_string(index=False, float_format=lambda x: f"{x:.4f}"))

fig, axs = plt.subplots(len(models), 1, figsize=(11, 2.4 * len(models)), sharex=True, sharey=True, squeeze=False)
for ax, m in zip(axs[:, 0], models):
    g = res[res["model"] == m].sort_values("day")
    ax.fill_between(g["day"], g["q025"], g["q975"], step="mid", color="tab:blue", alpha=0.25, lw=0, label="95% range")
    ax.step(g["day"], g["mean"], where="mid", color="tab:blue", lw=1.2, label="forecast mean")
    ax.plot(g["day"], g["obs"], "o", ms=3.5, color="k", label="observed")
    bad = g[~g["pass"]]
    ax.plot(bad["day"], bad["obs"], "o", ms=7, mfc="none", mec="tab:red", label="N-test fails")
    if fc:
        t = cmp[cmp["model"] == m]
        ax.plot(t["day"], t["obs"], "s", ms=8, mfc="none", mec="tab:green", label="tested in floatCSEP")
    ax.set_title(f"{m}: {g['pass'].sum()}/{len(g)} days pass, total forecast {g['mean'].sum():.1f} vs observed {g['obs'].sum()}",
                 fontsize=9, loc="left")
    ax.set_ylabel("N (M>=4)")
    if not a.linear:
        ax.set_yscale("symlog", linthresh=1)
    ax.grid(alpha=0.3)
axs[0, 0].legend(fontsize=7, ncol=5, loc="upper right")
fig.suptitle(f"{a.run}: daily number of M>=4 events, forecast vs observed", fontsize=11)
fig.tight_layout()
out = d / "numbers.png"
fig.savefig(out, dpi=150)
print(f"figure: {out}")
