"""Static dashboard of a run (floatcsep export) with the forecast maps computed in parallel.

Same output as `floatcsep export runs/<run>/config.yml -o DIR`: floatCSEP writes the manifest, the
catalog, the results and the front-end files; the forecast maps (expected rate per cell and
magnitude bin, forecasts/mX_wY.json) are computed here from the forecast csv files with pandas,
W processes at once, instead of floatCSEP's one-catalog-at-a-time reader (~30 s per map). The test
catalogs of the windows (results/<window>/catalog/) are written first if missing (merged runs).
Files in dashboard_patch/ of the repo (patched front-end files) are copied over the export.

--prior CATALOG (display only, the forecasts and test results are not changed): cells where a model
simulated no event at all are shown with a long-term background rate instead of being empty. The
background is the same for every model: the catalog (e.g. HORUS, column M or mag) before --prior-end
(default 2005-04-16, start of ISIDe), in the test region, depth < 30 km, M >= --prior-mag, declustered with Gardner-Knopoff windows, smoothed
with Helmstetter et al. (2007) adaptive power-law kernels (bandwidth = distance to the --nn-th
neighbour, at least 0.5 km), scaled to events per day (declustered count / catalog length) and
extrapolated to the forecast magnitude bins with Gutenberg-Richter b = 1. Cells with simulated events
keep the simulated rates.

--bg RUN (display only): instead, each model's own long-term rate from a long simulation
(scripts/prepare_bg.py, runs/RUN), skipping the first --skip years; models without one fall back to
the --prior background if given, else stay empty.

usage: python scripts/fast_export.py aquila_all -o ~/dash_aquila [--workers 40] [--no-forecasts]
       python scripts/fast_export.py aquila_all -o ~/dash_aquila_bg --prior data/horus.csv [--prior-mag 3.5]
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
p.add_argument("--prior", help="catalog for the display-only background (csv, CSEP columns)")
p.add_argument("--prior-mag", type=float, default=3.5)
p.add_argument("--prior-end", default="2005-04-16", help="use the background catalog before this date")
p.add_argument("--nn", type=int, default=5, help="neighbour order of the adaptive bandwidth")
p.add_argument("--bg", help="run with the long simulations of scripts/prepare_bg.py")
p.add_argument("--skip", type=float, default=10, help="years skipped at the start of the long simulations")
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


# long-term background (display only)
bg = None
if a.prior:
    c = pd.read_csv(Path(a.prior).expanduser()).rename(columns={"M": "mag"})
    c = c[(c.mag >= a.prior_mag) & (c.depth < 30) & ~reg.get_masked(c.lon.to_numpy(), c.lat.to_numpy())]
    c = c[pd.to_datetime(c.time_string, format="ISO8601") < pd.Timestamp(a.prior_end)]
    t = pd.to_datetime(c.time_string, format="ISO8601")
    yrs = (pd.Timestamp(a.prior_end) - t.min()).days / 365.25
    lon, lat, mg = c.lon.to_numpy(), c.lat.to_numpy(), c.mag.to_numpy()
    td = (t - t.min()).dt.total_seconds().to_numpy() / 86400

    def km(x0, y0, x1, y1):
        p0, p1 = np.radians(y0), np.radians(y1)
        h = np.sin((p1 - p0) / 2) ** 2 + np.cos(p0) * np.cos(p1) * np.sin(np.radians(x1 - x0) / 2) ** 2
        return 12742 * np.arcsin(np.sqrt(h))

    # Gardner-Knopoff declustering, largest events first
    keep = np.ones(len(c), bool)
    for i in np.argsort(-mg):
        if not keep[i]:
            continue
        dw = 10 ** (0.1238 * mg[i] + 0.983)
        tw = 10 ** (0.032 * mg[i] + 2.7389) if mg[i] >= 6.5 else 10 ** (0.5409 * mg[i] - 0.547)
        near = (np.abs(td - td[i]) <= tw) & (km(lon[i], lat[i], lon, lat) <= dw) & (mg <= mg[i])
        near[i] = False
        keep[near] = False
    lon, lat = lon[keep], lat[keep]

    # Helmstetter adaptive kernels on the grid
    org = reg.origins() + reg.dh / 2
    dd = km(lon[:, None], lat[:, None], lon[None, :], lat[None, :])
    bw = np.maximum(np.sort(dd, axis=1)[:, min(a.nn, len(lon) - 1)], 0.5)
    dens = np.zeros(nc)
    for j in range(0, len(lon), 500):
        r = km(lon[j:j + 500, None], lat[j:j + 500, None], org[None, :, 0], org[None, :, 1])
        k = bw[j:j + 500, None] / (r ** 2 + bw[j:j + 500, None] ** 2) ** 1.5
        dens += (k / k.sum(axis=1, keepdims=True)).sum(axis=0)
    rate = keep.sum() / (yrs * 365.25)
    edges = np.append(mags, np.inf)
    gr = 10 ** (-(edges[:-1] - a.prior_mag)) - 10 ** (-(edges[1:] - a.prior_mag))
    bg = (dens / dens.sum() * rate)[:, None] * gr[None, :]
    print(f"background: {a.prior} {t.min():%Y-%m-%d}..{a.prior_end}, {len(c)} events M>={a.prior_mag} in {yrs:.0f} yr, {keep.sum()} after "
          f"declustering; M>={mags[0]} rate {bg.sum():.4f} per day")


# per-model long-term rates (display only)
mbg = {}
if a.bg:
    bd = root / "runs" / a.bg
    bcfg = yaml.safe_load((bd / "config.yml").read_text())
    s0, s1 = [pd.Timestamp(x) for x in bcfg["time_config"]["time_windows"][0]]
    t_skip = s0 + pd.DateOffset(years=int(a.skip))
    days = (s1 - t_skip).days
    for e in yaml.safe_load((bd / "models.yml").read_text()):
        name = next(iter(e)); v = e[name]
        f = (bd / v["path"] / "forecasts" / f"{v.get('prefix', name)}_{s0:%Y-%m-%d}_{s1:%Y-%m-%d}.csv").resolve()
        if not f.exists():
            print(f"  long-term {name}: no file {f.name}")
            continue
        df = pd.read_csv(f, usecols=["lon", "lat", "mag", "time_string"])
        df = df[pd.to_datetime(df.time_string, format="ISO8601") >= t_skip]
        df = df[~reg.get_masked(df.lon.to_numpy(), df.lat.to_numpy())]
        k = bin1d_vec(df.mag.to_numpy(), mags, right_continuous=True)
        df = df[k >= 0]; k = k[k >= 0]
        i = reg.get_index_of(df.lon.to_numpy(), df.lat.to_numpy())
        r = np.bincount(i * nm + k, minlength=nc * nm).reshape(nc, nm) / (v["func_kwargs"]["n_sims"] * days)
        mbg[name] = r
        print(f"  long-term {name}: {len(df)} events in {v['func_kwargs']['n_sims']} x {days / 365.25:.0f} yr, "
              f"M>={mags[0]} {r.sum():.4f}/day, {(r.sum(axis=1) > 0).sum()} cells")


def job(args):
    mid, wid, f, n, rel, name = args
    if not f.exists():
        return None
    df = pd.read_csv(f, usecols=["lon", "lat", "mag"])
    df = df[~reg.get_masked(df.lon.to_numpy(), df.lat.to_numpy())]
    k = bin1d_vec(df.mag.to_numpy(), mags, right_continuous=True)
    df = df[k >= 0]; k = k[k >= 0]
    i = reg.get_index_of(df.lon.to_numpy(), df.lat.to_numpy())
    rates = np.bincount(i * nm + k, minlength=nc * nm).reshape(nc, nm) / n
    fill = mbg.get(name, bg)
    if fill is not None:
        empty = rates.sum(axis=1) == 0
        rates[empty] = fill[empty]
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
            jobs.append((mrec["id"], wrec["id"], f, n, f"forecasts/{mrec['id']}_{wrec['id']}.json", model.name))
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
    for m in man["models"]:
        if m["name"] in mbg:
            m.setdefault("notes", []).append(
                f"Map display only: cells without simulated events show the model's long-term rate "
                f"(fit and long simulation in run {a.bg}); results unchanged")
        elif a.prior:
            m.setdefault("notes", []).append(
                f"Map display only: cells without simulated events show a long-term background rate "
                f"({Path(a.prior).name} before {a.prior_end}, M>={a.prior_mag}, declustered, adaptive kernel); results unchanged")

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
