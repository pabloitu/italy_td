"""Inventory of everything on this machine: forecast files per model folder, and per run the windows,
forecasts found, floatCSEP results per test and scores. Read-only.

Forecasts: every models*/<model>/forecasts/ folder: number of files, first and last day, gaps (days
between first and last without a file), size, quarantined files (forecasts_bad). Runs: every
runs/*/config.yml (also runs/<sub>/<run>, e.g. copies from other servers): window, forecasts found per
model, result JSONs per test, scores.csv rows per model, DONE marker.

usage: python scripts/inventory.py > ~/inv_$(hostname).txt
"""
import hashlib
import re
import shutil
import socket
import subprocess
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
fn = re.compile(r"^(.*)_(\d{4}-\d\d-\d\d)_(\d{4}-\d\d-\d\d)\.csv$")

print(f"#### {socket.gethostname()} {sh('date -u +%FT%TZ')} italy_td {sh('git rev-parse --short HEAD')} "
      f"floatcsep {sh('pip show floatcsep 2>/dev/null | grep -i ^version')}")
cat = root / "data" / "iside_ml.csv"
if cat.exists():
    print(f"catalog md5 {hashlib.md5(cat.read_bytes()).hexdigest()}")
du = shutil.disk_usage(root)
print(f"disk {du.free / 1e9:.0f} GB free of {du.total / 1e9:.0f}")

print("\n## forecast folders (files, first day, last day, gaps, GB, bad)")
for fd in sorted(root.glob("models*/*/forecasts")):
    days, size, pre = [], 0, Counter()
    for f in fd.glob("*.csv"):
        m = fn.match(f.name)
        if not m:
            continue
        pre[m.group(1)] += 1
        days.append(date.fromisoformat(m.group(2)))
        size += f.stat().st_size
    bad = fd.parent / "forecasts_bad"
    nb = len(list(bad.glob("*.csv"))) if bad.exists() else 0
    rel = fd.parent.relative_to(root)
    if not days:
        print(f"{str(rel):40s} 0 files" + (f" bad {nb}" if nb else ""))
        continue
    d0, d1 = min(days), max(days)
    have = set(days)
    gaps = [d0 + timedelta(i) for i in range((d1 - d0).days + 1) if d0 + timedelta(i) not in have]
    g = f"gaps {len(gaps)}" + (f" ({', '.join(str(x) for x in gaps[:5])}{' ...' if len(gaps) > 5 else ''})" if gaps else "")
    print(f"{str(rel):40s} {len(days):5d} {d0} {d1} {g} {size / 1e9:.1f} GB" + (f" bad {nb}" if nb else "")
          + (f" prefixes {dict(pre)}" if len(pre) > 1 else ""))

print("\n## runs (window, windows, forecasts found per model | results per test | scores rows | DONE)")
for c in sorted(root.glob("runs/**/config.yml")):
    d = c.parent
    try:
        cfg = yaml.safe_load(c.read_text())
        ms = yaml.safe_load((d / cfg["model_config"]).read_text())
    except Exception as e:
        print(f"{d.relative_to(root)}: unreadable ({e})")
        continue
    tc = cfg["time_config"]
    if tc.get("time_windows"):
        wins = [(w[0].date(), w[1].date()) for w in tc["time_windows"]]
    else:
        wins, t = [], tc["start_date"]
        while t < tc["end_date"]:
            wins.append((t.date(), (t + timedelta(days=1)).date()))
            t += timedelta(days=1)
    fc = []
    for e in ms:
        name = next(iter(e)); v = e[name]
        fd = (d / v["path"] / "forecasts").resolve()
        n = sum((fd / f"{v.get('prefix', name)}_{s}_{t}.csv").exists() for s, t in wins) if fd.exists() else 0
        fc.append(f"{name}={n}")
    res = Counter()
    for f in (d / "results").glob("*/evaluations/*.json"):
        res[f.name.split("-test_")[0].replace("Catalog_", "")] += 1
    sc = d / "results" / "scores.csv"
    rows = Counter(l.split(",")[0] for l in sc.read_text().splitlines()[1:]) if sc.exists() else {}
    done = (d / "results" / "DONE").exists()
    print(f"{str(d.relative_to(root / 'runs')):22s} {wins[0][0]}..{wins[-1][1]} {len(wins):4d}w "
          f"fc {' '.join(fc)} | res {dict(res) or '-'} | scores {dict(rows) or '-'}{' | DONE' if done else ''}")
