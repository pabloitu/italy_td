"""Extend data/iside_ml.csv up to today: download the events after its last event from the INGV FDSN
event web service (text format, one query per year), filter them like scripts/prep_catalog.py (Italy
CSEP region, depth < 30 km, M >= 2.5, earthquakes only) and append them. The old file is never
changed; the result is a new file.

usage: python scripts/extend_catalog.py data/iside_ml_2026.csv [--src data/iside_ml.csv] [--end 2026-10-13]
"""
import argparse
import hashlib
import io
import urllib.request
from datetime import datetime, timedelta, timezone

import pandas as pd
from csep.core import regions
from csep.utils.calc import bin1d_vec

url = "https://webservices.ingv.it/fdsnws/event/1/query"
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("dst")
p.add_argument("--src", default="data/iside_ml.csv")
p.add_argument("--end", default=f"{datetime.now(timezone.utc):%Y-%m-%d}")
p.add_argument("--mag-min", type=float, default=2.5)
p.add_argument("--depth-max", type=float, default=30.0)
a = p.parse_args()
if a.dst == a.src:
    raise SystemExit("write to a new file, the old catalog stays as it is")

old = pd.read_csv(a.src)
last = pd.to_datetime(old.time_string, format="ISO8601").max()
t0 = last + timedelta(seconds=1)
t1 = pd.Timestamp(a.end)
print(f"{a.src}: {len(old)} events, last {last}; downloading {t0:%Y-%m-%dT%H:%M:%S} .. {t1:%Y-%m-%d}")

r = regions.italy_csep_region()
bb = r.get_bbox()
parts, s = [], t0
while s < t1:
    e = min(pd.Timestamp(f"{s.year + 1}-01-01"), t1)
    q = (f"{url}?starttime={s:%Y-%m-%dT%H:%M:%S}&endtime={e:%Y-%m-%dT%H:%M:%S}&minmag={a.mag_min}"
         f"&minlon={bb[0]}&maxlon={bb[1]}&minlat={bb[2]}&maxlat={bb[3]}&format=text")
    with urllib.request.urlopen(q, timeout=300) as f:
        txt = f.read().decode()
    n = 0
    if txt.strip():
        d = pd.read_csv(io.StringIO(txt), sep="|")
        d.columns = [c.strip("#").strip() for c in d.columns]
        parts.append(d)
        n = len(d)
    print(f"  {s:%Y-%m-%d} .. {e:%Y-%m-%d}: {n} events")
    s = e
if not parts:
    raise SystemExit("nothing downloaded")
raw = pd.concat(parts, ignore_index=True)
rawf = a.dst.replace(".csv", "_raw_download.csv")
raw.to_csv(rawf, index=False)
print(f"raw download: {len(raw)} events -> {rawf}")
print("event types:", raw["EventType"].value_counts().to_dict())
print("magnitude types:", raw["MagType"].value_counts().to_dict())

new = pd.DataFrame({"lon": raw["Longitude"], "lat": raw["Latitude"], "mag": raw["Magnitude"],
                    "time_string": pd.to_datetime(raw["Time"], format="ISO8601").dt.strftime("%Y-%m-%dT%H:%M:%S.%f"),
                    "depth": raw["Depth/Km"], "catalog_id": -1, "event_id": raw["EventID"]})
ix = bin1d_vec(new.lon.to_numpy(), r.xs)
iy = bin1d_vec(new.lat.to_numpy(), r.ys)
ok = (ix >= 0) & (iy >= 0)
ok[ok] = r.bbox_mask[iy[ok], ix[ok]] == 0
eq = raw["EventType"].astype(str).str.contains("earthquake")
tn = pd.to_datetime(new.time_string, format="ISO8601")
new = new[ok & eq.to_numpy() & (new.depth < a.depth_max) & (new.mag >= a.mag_min) & (tn > last)]
new = new.drop_duplicates("event_id").sort_values("time_string")
out = pd.concat([old, new[old.columns]], ignore_index=True)
out.to_csv(a.dst, index=False)

tn = pd.to_datetime(new.time_string, format="ISO8601")
print(f"added {len(new)} events ({tn.min()} .. {tn.max()})")
print("added events per year:", tn.dt.year.value_counts().sort_index().to_dict())
print("M>=4 per year:", tn[new.mag >= 4].dt.year.value_counts().sort_index().to_dict())
print("largest added events:")
for _, x in new.nlargest(8, "mag").iterrows():
    print(f"  {x.time_string}  M{x.mag:.1f}  {x.lon:.2f} {x.lat:.2f}  {x.depth:.0f} km")
print(f"-> {a.dst}: {len(out)} events, md5 {hashlib.md5(open(a.dst, 'rb').read()).hexdigest()}")
