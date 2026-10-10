"""Validate one catalog forecast CSV against claude/italy_experiment_spec.md."""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from csep.core import regions
from csep.utils.calc import bin1d_vec

COLS = ["lon", "lat", "mag", "time_string", "depth", "catalog_id", "event_id"]
TIME = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,6})?"
DATE = r"\d{4}-\d\d-\d\d(T\d\d:\d\d:\d\d)?"
NAME = re.compile(rf"^(?P<pre>.+)_(?P<s>{DATE})_(?P<e>{DATE})(_C(?P<c0>\d+)_C(?P<c1>\d+))?\.csv$")


def check(path, n_sims, mag_min=4.0, depth_max=30.0, prefix=None, region="italy_csep_region"):
    """Run all spec checks on one forecast file.

    Parameters
    ----------
    path : str
        Forecast CSV.
    n_sims : int
        Number of catalogs the forecast must have (catalog_id in 0..n_sims-1).
    mag_min, depth_max : float
        Magnitude threshold (inclusive) and depth limit (exclusive, km).
    prefix : str, optional
        Expected file name prefix.
    region : str
        Name of a function in csep.core.regions.

    Returns
    -------
    list of (status, name, message), status in PASS, FAIL, WARN.
    """
    out = []

    def add(ok, name, msg="", warn=False):
        out.append(("PASS" if ok else ("WARN" if warn else "FAIL"), name, "" if ok else msg))

    # file name
    p = Path(path)
    m = NAME.match(p.name)
    add(m is not None, "filename", "expected {prefix}_{start}_{end}[_C{a}_C{b}].csv")
    if m and prefix:
        add(m["pre"] == prefix, "prefix", f"got '{m['pre']}', expected '{prefix}'")
    t0 = pd.Timestamp(m["s"]) if m else None
    t1 = pd.Timestamp(m["e"]) if m else None

    # columns
    df = pd.read_csv(p)
    add(list(df.columns) == COLS, "columns", f"got {list(df.columns)}")
    if list(df.columns) != COLS:
        return out
    add(len(df) > 0, "events", "file has no events", warn=True)
    if len(df) == 0:
        return out

    nan = df.isna().sum()
    nan = nan[nan > 0]
    add(nan.empty, "no_nan", ", ".join(f"{k}: {v}" for k, v in nan.items()))
    df = df.dropna()
    num = [c for c in COLS if c not in ("time_string", "event_id")]
    bad = [c for c in num if not pd.api.types.is_numeric_dtype(df[c])]
    add(not bad, "numeric", f"non-numeric columns: {bad}")
    if bad:
        return out

    # time
    ts = df["time_string"].astype(str)
    fmt = ts.str.fullmatch(TIME)
    add(fmt.all(), "time_format", f"{(~fmt).sum()} rows, first: {ts[~fmt].iloc[0] if (~fmt).any() else ''}")
    if fmt.all() and t0 is not None:
        t = pd.to_datetime(ts, format="ISO8601")
        inw = (t >= t0) & (t < t1)
        add(inw.all(), "time_window", f"{(~inw).sum()} events outside [{t0}, {t1})", warn=True)

    # catalog ids
    cid = df["catalog_id"]
    isint = pd.api.types.is_integer_dtype(cid)
    add(isint, "catalog_id_int", f"dtype {cid.dtype}")
    if isint:
        rng = (cid >= 0) & (cid < n_sims)
        add(rng.all(), "catalog_id_range", f"{(~rng).sum()} rows outside 0..{n_sims - 1}")

    # filters
    add((df["mag"] >= mag_min).all(), "mag_min", f"{(df['mag'] < mag_min).sum()} events below {mag_min}")
    add((df["depth"] < depth_max).all(), "depth", f"{(df['depth'] >= depth_max).sum()} events at depth >= {depth_max}")
    r = getattr(regions, region)()
    ix = bin1d_vec(df["lon"].to_numpy(), r.xs)
    iy = bin1d_vec(df["lat"].to_numpy(), r.ys)
    ok = (ix >= 0) & (iy >= 0)
    ok[ok] = r.bbox_mask[iy[ok], ix[ok]] == 0
    add(ok.all(), "region", f"{(~ok).sum()} of {len(df)} events outside {region}")

    if isint:
        out.append(("INFO", "catalogs", f"{cid.nunique()} of {n_sims} catalogs have events, {len(df)} events"))
    return out


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("path")
    a.add_argument("--n-sims", type=int, required=True)
    a.add_argument("--mag-min", type=float, default=4.0)
    a.add_argument("--depth-max", type=float, default=30.0)
    a.add_argument("--prefix", default=None)
    a.add_argument("--region", default="italy_csep_region")
    a = a.parse_args()

    res = check(a.path, a.n_sims, a.mag_min, a.depth_max, a.prefix, a.region)
    print(f"forecast: {a.path}")
    for s, n, msg in res:
        print(f"{s:5s} {n}" + (f": {msg}" if msg else ""))
    nf = sum(s == "FAIL" for s, _, _ in res)
    nw = sum(s == "WARN" for s, _, _ in res)
    print(f"result: {'FAIL' if nf else 'PASS'} ({nf} fail, {nw} warn)")
    sys.exit(1 if nf else 0)
