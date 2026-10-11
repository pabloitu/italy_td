"""Archive the forecasts of a finished run, read-only, with a manifest of what produced each file.

Copies every window file of every model of runs/<run> to <dest>/<run>/<model>/, then the run's
config, models, logs and inlabru audit files to <dest>/<run>/meta/, writes <dest>/<run>/manifest.csv
and makes everything read-only. Never overwrites: refuses if <dest>/<run> exists. The live
models/<name>/forecasts are not touched.

manifest.csv, one row per file: model, window, file, size, md5, model_commit (git HEAD of
models/<name>, or "no-git"), code_md5 (all files of models/<name> except forecasts*, input, .git),
image_id, catalog_md5, n_sims, seed, fit args, host, archived_utc.

usage: python scripts/archive_run.py RUN [--dest ~/italy_archive] [--link] [--partial]
  --link     hard links instead of copies (no extra disk; the live files become read-only too)
  --partial  archive even if windows are missing
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("run")
p.add_argument("--dest", default="~/italy_archive")
p.add_argument("--link", action="store_true")
p.add_argument("--partial", action="store_true")
a = p.parse_args()

d = root / "runs" / a.run
out = Path(a.dest).expanduser() / a.run
if out.exists():
    sys.exit(f"{out} exists: nothing done (archives are never overwritten)")
cfg = yaml.safe_load((d / "config.yml").read_text())
ms = yaml.safe_load((d / cfg["model_config"]).read_text())
tc = cfg["time_config"]
if tc.get("time_windows"):
    wins = [(w[0].date(), w[1].date()) for w in tc["time_windows"]]
else:
    wins, t = [], tc["start_date"]
    while t < tc["end_date"]:
        wins.append((t.date(), (t + timedelta(days=1)).date()))
        t += timedelta(days=1)


def md5(f):
    h = hashlib.md5()
    with open(f, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def sh(c):
    r = subprocess.run(c, shell=True, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


# files to archive
todo, miss = [], []
for e in ms:
    name = next(iter(e)); v = e[name]
    mdir = (d / v["path"]).resolve()
    for s, t in wins:
        f = mdir / "forecasts" / f"{v.get('prefix', name)}_{s}_{t}.csv"
        (todo if f.exists() else miss).append((name, v, mdir, f"{s}_{t}", f))
if miss:
    print(f"{len(miss)} missing windows, e.g. " + ", ".join(f"{m[0]} {m[3]}" for m in miss[:5]))
    if not a.partial:
        sys.exit("nothing done; finish the run or use --partial")
size = sum(x[4].stat().st_size for x in todo)
out.parent.mkdir(parents=True, exist_ok=True)
free = shutil.disk_usage(out.parent).free
print(f"{len(todo)} files, {size / 1e9:.1f} GB -> {out} ({'hard links' if a.link else 'copies'}; "
      f"{free / 1e9:.0f} GB free)")
if not a.link and size > 0.9 * free:
    sys.exit("not enough disk: free space or use --link")

# provenance per model
cat_md5 = md5((d / cfg["catalog"]).resolve())
prov = {}
for e in ms:
    name = next(iter(e)); v = e[name]
    mdir = (d / v["path"]).resolve()
    h = hashlib.md5()
    for f in sorted(mdir.rglob("*")):
        rel = f.relative_to(mdir).parts
        if f.is_file() and rel[0] not in (".git", "input") and not rel[0].startswith("forecasts"):
            h.update("/".join(rel).encode()); h.update(md5(f).encode())
    kw = dict(v.get("func_kwargs") or {})
    fit = {k: kw[k] for k in kw if "start" in k or "years" in k}
    prov[name] = {
        "model_commit": sh(f"git -C {mdir} rev-parse HEAD") or "no-git",
        "code_md5": h.hexdigest(),
        "image_id": sh(f"docker image inspect --format '{{{{.Id}}}}' {name}_image")[7:19],
        "n_sims": kw.get("n_sims"), "seed": kw.get("seed"), "fit": json.dumps(fit),
    }

host = socket.gethostname()
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
rows = []
for name, v, mdir, win, f in todo:
    dst = out / name / f.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.link(f, dst) if a.link else shutil.copy2(f, dst)
    rows.append({"model": name, "window": win, "file": f"{name}/{f.name}", "size": f.stat().st_size,
                 "md5": md5(dst), **prov[name], "catalog_md5": cat_md5, "host": host, "archived_utc": now})

meta = out / "meta"
meta.mkdir()
for f in [d / "config.yml", d / cfg["model_config"], *sorted((d / "results").glob("*.log")),
          *sorted((root / "results").glob(f"inlabru_map_audit_{wins[0][0]}*.txt"))]:
    if f.exists():
        shutil.copy2(f, meta / f.name)
with open(out / "manifest.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["model"])
    w.writeheader()
    w.writerows(rows)

for f in sorted(out.rglob("*"), reverse=True):
    m = f.stat().st_mode
    f.chmod(m & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
out.chmod(out.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
for name in prov:
    n = sum(r["model"] == name for r in rows)
    print(f"  {name}: {n} files, commit {prov[name]['model_commit'][:8]}, code {prov[name]['code_md5'][:8]}, "
          f"image {prov[name]['image_id'] or '?'}")
print(f"done: {out} (read-only). To remove it later: chmod -R u+w {out}")
