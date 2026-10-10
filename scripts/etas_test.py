"""Integration runs and report for the ETAS family (vetas, fletas, petai), used by etas_test.sh.

usage:
  python scripts/etas_test.py run NAME --models vetas fletas petai --start 2016-10-28 --days 4
                              --nsims 2000 --mode parallel [--all-cores]
  python scripts/etas_test.py report [--out results/etas_test]

run: one floatCSEP config with the given models and windows (N-test only, no plots), forecasts
checked and copied to OUT/fc_<nsims>/, per-model wall time and docker memory peak to OUT/runs.csv.
--all-cores drops n_jobs (each container uses every core); otherwise models.yml's n_jobs is kept.

report: for every copied forecast, the M >= 4 counts per catalog against the observed number in
the testing region (same filters as config.yml region_config), and the N-test result if present.
A window is flagged when the observed number is outside the central 98% of the forecast
(P(N >= obs) < 0.01 or P(N <= obs) < 0.01), unless it contains an M >= 5.3 event (mainshock day).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "scripts"))
from scenarios import check_fc, errors, fc_path, floatcsep, windows, write_cfg  # noqa: E402

TEST = "Catalog_N-test"
BIG_M = 5.3


class Mem(threading.Thread):
    """Peak memory of running containers, sampled with docker stats."""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak, self.stop = 0.0, False

    def run(self):
        u = {"KiB": 1 / 1024 ** 2, "MiB": 1 / 1024, "GiB": 1, "B": 1 / 1024 ** 3}
        while not self.stop:
            try:
                s = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}"],
                                   capture_output=True, text=True, timeout=30).stdout
                for m in re.finditer(r"([\d.]+)(GiB|MiB|KiB|B) /", s):
                    self.peak = max(self.peak, float(m[1]) * u[m[2]])
            except Exception:
                pass
            time.sleep(5)


def run(a):
    out = root / a.out
    (out / f"fc_{a.nsims}").mkdir(parents=True, exist_ok=True)
    tag = f"etas_{a.name}"
    cfg = write_cfg(tag, a.models, a.start, a.days, a.nsims, "docker", mode=a.mode)
    mf = root / f".scen_{tag}_models.yml"
    ms = yaml.safe_load(mf.read_text())
    for e in ms:
        kw = next(iter(e.values()))["func_kwargs"]
        if a.all_cores:
            kw.pop("n_jobs", None)
    mf.write_text(yaml.safe_dump(ms, sort_keys=False))
    ws = windows(a.start, a.days)
    for m in a.models:
        for w in ws:
            fc_path(m, w).unlink(missing_ok=True)

    log = out / f"{tag}.log"
    log.write_text("")
    mem = Mem()
    mem.start()
    rc, dt, _ = floatcsep("run", cfg, log)
    mem.stop = True

    print(f"== {a.name}: {', '.join(a.models)}, {len(ws)} windows from {a.start}, {a.nsims} catalogs, "
          f"{a.mode}{' all cores' if a.all_cores else ''}: exit {rc}, {dt / 60:.1f} min, "
          f"docker memory peak {mem.peak:.2f} GB")
    for e in errors(log)[:10]:
        print(f"  ERROR {e.strip()[:200]}")
    bad = 0
    for m in a.models:
        chk = []
        for w in ws:
            check_fc(m, w, a.nsims, chk)
            if fc_path(m, w).exists():
                shutil.copy(fc_path(m, w), out / f"fc_{a.nsims}")
        for ok, msg in chk:
            print(f"  {'ok  ' if ok else 'FAIL'} {msg}")
            bad += not ok
    row = pd.DataFrame([{"run": a.name, "models": " ".join(a.models), "start": a.start, "days": a.days,
                         "nsims": a.nsims, "mode": a.mode, "all_cores": a.all_cores, "exit": rc,
                         "minutes": round(dt / 60, 2), "mem_peak_gb": round(mem.peak, 2),
                         "checks_failed": bad}])
    f = out / "runs.csv"
    row.to_csv(f, mode="a", header=not f.exists(), index=False)
    sys.exit(1 if (rc or bad) else 0)


def observed(cfg):
    """Test catalog of config.yml: region_config magnitudes, depths and region."""
    from csep.core import regions
    from csep.utils.calc import bin1d_vec
    c = pd.read_csv(root / cfg["catalog"])
    rc = cfg["region_config"]
    c = c[(c.mag >= rc["mag_min"] - 1e-9) & (c.depth >= rc["depth_min"]) & (c.depth < rc["depth_max"])]
    r = getattr(regions, rc["region"])()
    ix, iy = bin1d_vec(c.lon.to_numpy(), r.xs), bin1d_vec(c.lat.to_numpy(), r.ys)
    ok = (ix >= 0) & (iy >= 0)
    ok[ok] = r.bbox_mask[iy[ok], ix[ok]] == 0
    c = c[ok].copy()
    c["t"] = pd.to_datetime(c.time_string, format="ISO8601")
    return c


def ntest(model, w, n):
    for f in (root / "results").glob(f"scen_etas_*/{w}/evaluations/{TEST}_{model}.json"):
        r = json.loads(f.read_text())
        if len(r["test_distribution"]) == n:
            return r["observed_statistic"], r["quantile"]
    return None, None


def report(a):
    out = root / a.out
    cfg = yaml.safe_load((root / "config.yml").read_text())
    obs = observed(cfg)
    models = {}
    for e in yaml.safe_load((root / "models.yml").read_text()):
        n, v = next(iter(e.items()))
        models[v.get("prefix", n)] = n
    rows = []
    for d in sorted(out.glob("fc_*"), key=lambda p: int(p.name[3:])):
        n = int(d.name[3:])
        for f in sorted(d.glob("*.csv")):
            m = re.match(r"(.+)_(\d{4}-\d\d-\d\d)_(\d{4}-\d\d-\d\d)\.csv$", f.name)
            if not m:
                continue
            name = models.get(m[1], m[1])
            t0, t1 = pd.Timestamp(m[2]), pd.Timestamp(m[3])
            o = obs[(obs.t >= t0) & (obs.t < t1)]
            k = len(o)
            df = pd.read_csv(f, usecols=["mag", "catalog_id"])
            df = df[df.mag >= cfg["region_config"]["mag_min"] - 1e-9]
            c = np.bincount(df.catalog_id.to_numpy(int), minlength=n)[:n]
            pge, ple = (c >= k).mean(), (c <= k).mean()
            big = o.mag.max() >= BIG_M if k else False
            if big:
                flag = f"mainshock day (M{o.mag.max():.1f}), not judged"
            elif min(pge, ple) < 0.01:
                flag = "OUT (obs outside central 98%)"
            else:
                flag = "ok"
            no, nq = ntest(name, f"{m[2]}_{m[3]}", n)
            rows.append({"model": name, "window": m[2], "n_sims": n, "obs": k, "mean": c.mean(),
                         "median": np.median(c), "q01": np.quantile(c, 0.01), "q99": np.quantile(c, 0.99),
                         "max": c.max(), "P(N>0)": (c > 0).mean(), "P(N>=obs)": pge, "P(N<=obs)": ple,
                         "ntest_obs": no, "ntest_q": None if nq is None else "/".join(f"{q:.3f}" for q in nq),
                         "flag": flag})
    r = pd.DataFrame(rows)
    r.to_csv(out / "counts.csv", index=False)
    with open(out / "counts.txt", "w") as fo:
        if r.empty:
            fo.write("no forecasts found\n")
        else:
            for n, g in r.groupby("n_sims"):
                fo.write(f"\n-- {n} catalogs: M>={cfg['region_config']['mag_min']} events in the testing region\n")
                s = g.drop(columns="n_sims").sort_values(["window", "model"])
                fo.write(s.to_string(index=False, float_format=lambda x: f"{x:.3f}") + "\n")
            mism = r[r.ntest_obs.notna() & (r.ntest_obs != r.obs)]
            if len(mism):
                fo.write(f"\nWARN observed count differs from the N-test in {len(mism)} rows "
                         f"(time zone or catalog filters?)\n")
            nout = (r.flag.str.startswith("OUT")).sum()
            fo.write(f"\n{len(r)} forecasts, {nout} outside the central 98% (mainshock days not judged)\n")
    print((out / "counts.txt").read_text())


p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sp = p.add_subparsers(dest="cmd", required=True)
r = sp.add_parser("run")
r.add_argument("name")
r.add_argument("--models", nargs="+", required=True)
r.add_argument("--start", required=True)
r.add_argument("--days", type=int, default=1)
r.add_argument("--nsims", type=int, default=2000)
r.add_argument("--mode", default="parallel", choices=["parallel", "sequential"])
r.add_argument("--all-cores", action="store_true")
r.add_argument("--out", default="results/etas_test")
q = sp.add_parser("report")
q.add_argument("--out", default="results/etas_test")
a = p.parse_args()
run(a) if a.cmd == "run" else report(a)
