"""Run one model over N windows sequentially and in parallel, with different threads per container.

Each run starts from an empty forecasts folder; prints wall time, per-window check and the
forecast hashes, and whether the forecasts are identical across runs.

usage: python scripts/modes.py MODEL [--start 2016-08-24] [--days 4] [--nsims 1000]
                               [--runs sequential:0 parallel:1 parallel:0]

A run is MODE:THREADS, with THREADS = 0 for the model default (all cores of the host in each
container). THREADS sets n_jobs if the model has that key in models.yml, else n_cores.
parallel runs use floatCSEP's worker count, min(host cores, 32).
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "scripts"))
from scenarios import check_fc, fc_path, floatcsep, model_info, runs, sha, windows, write_cfg  # noqa: E402

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("model")
p.add_argument("--start", default="2016-08-24")
p.add_argument("--days", type=int, default=4)
p.add_argument("--nsims", type=int, default=1000)
p.add_argument("--runs", nargs="+", default=["sequential:0", "parallel:1", "parallel:0"])
a = p.parse_args()

ws = windows(a.start, a.days)
fdir = model_info(a.model)[0] / "forecasts"
out = root / "results" / "modes"
out.mkdir(parents=True, exist_ok=True)
print(f"host cores {os.cpu_count()}, floatCSEP parallel workers {min(os.cpu_count() or 4, 32)}")

res = {}
for r in a.runs:
    mode, nc = r.split(":")
    tag = f"modes_{mode}_{nc}"
    cfg = write_cfg(tag, [a.model], a.start, a.days, a.nsims, "docker", mode=mode)
    mf = root / f".scen_{tag}_models.yml"
    ms = yaml.safe_load(mf.read_text())
    kw = ms[0][a.model]["func_kwargs"]
    key = "n_jobs" if "n_jobs" in kw else "n_cores"
    kw.pop(key, None)
    if int(nc):
        kw[key] = int(nc)
    mf.write_text(yaml.safe_dump(ms, sort_keys=False))
    for w in ws:
        fc_path(a.model, w).unlink(missing_ok=True)
    log = out / f"{tag}.log"
    log.write_text("")
    rc, dt, _ = floatcsep("run", cfg, log)
    chk = []
    for w in ws:
        check_fc(a.model, w, a.nsims, chk)
    hs = {w: sha(fc_path(a.model, w))[:12] if fc_path(a.model, w).exists() else None for w in ws}
    keep = out / tag
    shutil.rmtree(keep, ignore_errors=True)
    keep.mkdir()
    for w in ws:
        if fc_path(a.model, w).exists():
            shutil.copy(fc_path(a.model, w), keep)
    res[r] = hs
    print(f"\n== {r}  exit {rc}, {dt:.0f} s total, {dt / len(ws):.0f} s per window, "
          f"model ran {runs(log, a.model)} times")
    for ok, msg in chk:
        print(f"  {'ok  ' if ok else 'FAIL'} {msg}")
    print("  hashes: " + " ".join(f"{w[:10]}={h}" for w, h in hs.items()))

print("\n== identical to the first run")
first = a.runs[0]
for r in a.runs[1:]:
    same = sum(res[r][w] is not None and res[r][w] == res[first][w] for w in ws)
    print(f"  {r}: {same}/{len(ws)} windows")
print(f"forecast copies: {out.relative_to(root)}/modes_<mode>_<threads>/")
