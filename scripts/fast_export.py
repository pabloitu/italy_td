"""Static dashboard of a run (floatcsep export) with the forecast maps computed in parallel.

Same output as `floatcsep export runs/<run>/config.yml -o DIR`: floatCSEP writes the manifest, the
catalog, the results and the front-end files; the forecast maps (expected rate per cell and
magnitude bin, forecasts/mX_wY.json) are computed here from the forecast csv files with pandas,
W processes at once, instead of floatCSEP's one-catalog-at-a-time reader (~30 s per map). The test
catalogs of the windows (results/<window>/catalog/) are written first if missing (merged runs).
Files in dashboard_patch/ of the repo (patched front-end files) are copied over the export.

usage: python scripts/fast_export.py aquila_all -o ~/dash_aquila [--workers 40] [--no-forecasts]
"""
import argparse
import base64
import json
import logging
import shutil
from datetime import timedelta
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from csep.utils.calc import bin1d_vec
from floatcsep.experiment import Experiment
from floatcsep.postprocess.web.export import export_experiment
from floatcsep.utils.helpers import timewindow2str

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("run")
p.add_argument("-o", "--out", required=True)
p.add_argument("--workers", type=int, default=16)
p.add_argument("--no-forecasts", action="store_true")
a = p.parse_args()
logging.getLogger("floatLogger").setLevel(logging.WARNING)

d = root / "runs" / a.run
out = Path(a.out).expanduser()
exp = Experiment.from_yml(config_yml=str(d / "config.yml"))
exp.stage_models()
exp.set_tree()
repo = exp.catalog_repo
wins = [timewindow2str(w) for w in exp.time_windows]
for w in wins:
    if not Path(exp.registry.get_test_catalog_key(w)).exists():
        repo.set_test_cats(w)
print(f"{a.run}: {len(wins)} windows, {len(exp.models)} models")
export_experiment(exp, out_dir=str(out), forecasts=False)
print(f"manifest, catalog, results and front-end written to {out}")

# forecast maps
reg = exp.region
mags = np.asarray(exp.magnitudes, dtype=float)
nm, nc = len(mags), reg.num_nodes
ms = yaml.safe_load((d / "models.yml").read_text())
cfg = {next(iter(m)): m[next(iter(m))] for m in ms}


def encode(rates):
    cum = np.cumsum(rates[:, ::-1], axis=1)[:, ::-1]
    pos = cum > 0
    tot = np.round(cum.sum(axis=0), 4).tolist()
    if not pos.any():
        return {"vmin": 0.0, "vmax": 1.0, "totals": tot, "data": ""}
    with np.errstate(divide="ignore"):
        lg = np.where(pos, np.log10(np.where(pos, cum, 1.0)), np.nan)
    vmin, vmax = float(np.nanmin(lg)), float(np.nanmax(lg))
    if vmax <= vmin:
        vmax = vmin + 1.0
    q = np.zeros(lg.shape, dtype=np.uint16)
    q[pos] = np.round((lg[pos] - vmin) / (vmax - vmin) * 65534).astype(np.uint16) + 1
    return {"vmin": vmin, "vmax": vmax, "totals": tot,
            "data": base64.b64encode(q.astype("<u2").tobytes()).decode("ascii")}


def job(args):
    mid, wid, f, n, rel = args
    if not f.exists():
        return None
    df = pd.read_csv(f, usecols=["lon", "lat", "mag"])
    df = df[~reg.get_masked(df.lon.to_numpy(), df.lat.to_numpy())]
    k = bin1d_vec(df.mag.to_numpy(), mags, right_continuous=True)
    df = df[k >= 0]; k = k[k >= 0]
    i = reg.get_index_of(df.lon.to_numpy(), df.lat.to_numpy())
    rates = np.bincount(i * nm + k, minlength=nc * nm).reshape(nc, nm) / n
    rec = {"model": mid, "window": wid, "mags": np.round(mags, 3).tolist(), "n_cells": nc,
           **encode(rates), "grid": "region"}
    (out / rel).parent.mkdir(parents=True, exist_ok=True)
    with open(out / rel, "w") as fh:
        json.dump(rec, fh, separators=(",", ":"))
    return mid, wid, rel


man = json.loads((out / "manifest.json").read_text())
if not a.no_forecasts:
    jobs = []
    for mrec, model in zip(man["models"], exp.models):
        v = cfg[model.name]
        fd = (d / v["path"] / "forecasts").resolve()
        pre = v.get("prefix", model.name)
        n = v["func_kwargs"]["n_sims"]
        for wrec, w in zip(man["time_windows"], exp.time_windows):
            f = fd / f"{pre}_{w[0]:%Y-%m-%d}_{w[1]:%Y-%m-%d}.csv"
            jobs.append((mrec["id"], wrec["id"], f, n, f"forecasts/{mrec['id']}_{wrec['id']}.json"))
    done = 0
    with get_context("fork").Pool(a.workers) as pool:
        for r in pool.imap_unordered(job, jobs, chunksize=2):
            if r:
                mid, wid, rel = r
                next(m for m in man["models"] if m["id"] == mid)["forecasts"][wid] = rel
                done += 1
                if done % 200 == 0:
                    print(f"  {done}/{len(jobs)} forecast maps")
    print(f"forecast maps: {done} of {len(jobs)}")

# patched front-end files
patch = root / "dashboard_patch"
if patch.exists():
    for f in patch.rglob("*"):
        if f.is_file():
            dst = out / f.relative_to(patch)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
    print(f"front-end patch applied from {patch}")
with open(out / "manifest.json", "w") as fh:
    json.dump(man, fh, separators=(",", ":"))
print(f"done: {out}   (view: cd {out} && python -m http.server 8000)")
