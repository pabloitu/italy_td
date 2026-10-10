"""Filter a CSEP ascii catalog to the Italy testing region, depth < 30 km and mag >= --mag-min."""
import argparse

import pandas as pd
from csep.core import regions
from csep.utils.calc import bin1d_vec

a = argparse.ArgumentParser(description=__doc__)
a.add_argument("src")
a.add_argument("dst")
a.add_argument("--mag-min", type=float, default=2.5)
a.add_argument("--depth-max", type=float, default=30.0)
a.add_argument("--region", default="italy_csep_region")
a = a.parse_args()

d = pd.read_csv(a.src)
r = getattr(regions, a.region)()
ix = bin1d_vec(d["lon"].to_numpy(), r.xs)
iy = bin1d_vec(d["lat"].to_numpy(), r.ys)
ok = (ix >= 0) & (iy >= 0)
ok[ok] = r.bbox_mask[iy[ok], ix[ok]] == 0
keep = ok & (d["depth"] < a.depth_max) & (d["mag"] >= a.mag_min)
d[keep].to_csv(a.dst, index=False)
print(f"{len(d)} events in, {keep.sum()} out; outside region {(~ok).sum()}, "
      f"depth >= {a.depth_max}: {(d['depth'] >= a.depth_max).sum()}, "
      f"mag < {a.mag_min}: {(d['mag'] < a.mag_min).sum()}")
