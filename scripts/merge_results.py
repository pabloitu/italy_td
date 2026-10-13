"""Merge the floatCSEP results of several test runs into one experiment folder.

Copies results/<window>/evaluations/*.json of every source run (runs/<src>, glob patterns allowed) into
runs/<out>/results/<window>/evaluations/, for the windows within --start..--end. Identical files are
skipped; a file that already exists with different content is never overwritten and is reported.
Writes runs/<out>/config.yml (time window start..end, --tests) and models.yml (union of the source
models, first seen wins) if they do not exist yet. Bring the source folders from the other servers
first (they hold only configs and results, the forecasts stay where they are).

usage: python scripts/merge_results.py OUT SRC [SRC ...] [--start D] [--end D] [--tests tests_td.yml]
   e.g. python scripts/merge_results.py full 'full_20??_[te]*' 'full_b2_*_[te]*' --start 2010-01-01 --end 2021-06-29
"""
import argparse
import filecmp
import shutil
from datetime import datetime
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("out")
p.add_argument("src", nargs="+")
p.add_argument("--start")
p.add_argument("--end", help="exclusive")
p.add_argument("--tests", default="tests_td.yml")
a = p.parse_args()

srcs = sorted({x for s in a.src for x in (root / "runs").glob(s) if (x / "config.yml").exists()})
if not srcs:
    raise SystemExit("no source runs found")
od = root / "runs" / a.out
new = same = 0
bad, wins, models = [], set(), {}
for s in srcs:
    for e in yaml.safe_load((s / "models.yml").read_text()):
        models.setdefault(next(iter(e)), e)
    for f in sorted((s / "results").glob("*/evaluations/*.json")):
        w = f.parts[-3]
        if (a.start and w[:10] < a.start) or (a.end and w[:10] >= a.end):
            continue
        wins.add(w)
        dst = od / "results" / w / "evaluations" / f.name
        if dst.exists():
            if filecmp.cmp(f, dst, shallow=False):
                same += 1
            else:
                bad.append(f"{s.name}/{w}/{f.name}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        new += 1

if not (od / "config.yml").exists() and wins:
    cfg = yaml.safe_load((srcs[0] / "config.yml").read_text())
    tc = cfg["time_config"]
    cfg["name"] = a.out
    cfg["time_config"] = {"start_date": datetime.fromisoformat(a.start or min(wins)[:10]),
                          "end_date": datetime.fromisoformat(a.end or max(wins)[11:21]),
                          "horizon": tc["horizon"], "exp_class": tc["exp_class"]}
    cfg["test_config"] = f"../../{a.tests}"
    (od / "config.yml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    (od / "models.yml").write_text(yaml.safe_dump(list(models.values()), sort_keys=False))

print(f"{len(srcs)} source runs, {len(wins)} windows -> runs/{a.out}/results: {new} copied, {same} identical")
print(f"models: {', '.join(models)}")
if bad:
    print(f"{len(bad)} conflicts (kept the existing file):")
    for x in bad[:10]:
        print(f"  {x}")
