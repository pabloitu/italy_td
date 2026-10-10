"""Estimate the wall time of each run from the pilot's per-forecast timings.

Reads the "[Engine] Forecasts / <model>" lines of runs/pilot/results/run.log (mean and max time of
one forecast per model, measured with the same threads and n_sims as the real runs), and prints
days per run = windows x mean time / containers, per model and summed. Busy sequence days take
longer than the mean of the 4 pilot days, so the sequence estimates use the max instead.

usage: python scripts/estimate.py --workers 32 [--log runs/pilot/results/run.log]
"""
import argparse
import re
from datetime import date
from pathlib import Path

RUNS = {
    "aquila": (date(2009, 3, 1), date(2009, 6, 9), "max"),
    "emilia": (date(2012, 5, 1), date(2012, 8, 9), "max"),
    "amatrice": (date(2016, 8, 1), date(2017, 2, 1), "max"),
    "full_a": (date(2010, 1, 1), date(2016, 1, 1), "mean"),
    "full_b": (date(2016, 1, 1), date(2021, 1, 1), "mean"),
    "full_c": (date(2021, 1, 1), date(2026, 10, 1), "mean"),
}

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--workers", type=int, required=True, help="containers at once on the target server")
p.add_argument("--log", default="runs/pilot/results/run.log")
a = p.parse_args()


def sec(x):
    return float(x[:-2]) / 1000 if x.endswith("ms") else float(x[:-1])


pat = re.compile(r"\[Engine\] Forecasts / (\S+): \S+ \| (\d+)x \| (\S+) \| (\S+) \| (\S+)")
t = {}
for m in pat.finditer(Path(a.log).read_text(errors="ignore")):
    t[m.group(1)] = (sec(m.group(3)), sec(m.group(4)), int(m.group(2)))
if not t:
    raise SystemExit(f"no forecast timings in {a.log} (did the pilot run with -d?)")

print("per forecast (pilot):")
for k, (mean, mx, n) in t.items():
    print(f"  {k:12s} mean {mean / 60:6.1f} min  max {mx / 60:6.1f} min  ({n} forecasts)")
print(f"\nestimate with {a.workers} containers at once:")
for run, (t0, t1, stat) in RUNS.items():
    n = (t1 - t0).days
    per = {k: (v[0] if stat == "mean" else v[1]) * n / a.workers / 86400 for k, v in t.items()}
    parts = ", ".join(f"{k} {d:.1f}" for k, d in per.items())
    print(f"  {run:9s} {n:5d} windows  {sum(per.values()):6.1f} days  ({parts})")
