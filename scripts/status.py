"""One-screen status of the forecast runs on this machine (read-only, safe while runs are going).

Per run: screen, what is running now (checking / staging / running / stopped), forecasts per model,
failed windows that are still missing (with the error), quarantined files, inlabru MAP warnings,
the last check. Then containers per model image, disk, and the last finished runs (runs/DONE.log).

usage: scripts/status.sh [RUN ...]        (default: every runs/<name> with a config.yml)
"""
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
names = sys.argv[1:] or sorted(p.parent.name for p in (root / "runs").glob("*/config.yml"))
ts = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
fail = re.compile(r"\[(\S+)\] Container \w+ for task name (\S+) exited with code (\d+)")


def sh(c):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


def windows(tc):
    if tc.get("time_windows"):
        return [(w[0].date(), w[1].date()) for w in tc["time_windows"]]
    out, t = [], tc["start_date"]
    while t < tc["end_date"]:
        out.append((t.date(), (t + timedelta(days=1)).date()))
        t += timedelta(days=1)
    return out


def reason(lines, i, code):
    j = i + 1
    while j < len(lines) and ts.match(lines[j]) and "Last logs" in lines[j]:
        j += 1
    blk = []
    while j < len(lines) and not ts.match(lines[j]) and len(blk) < 2000:
        blk.append(lines[j].strip())
        j += 1
    for k, x in enumerate(blk):
        if x.startswith("Error") or re.match(r"^\w*(Error|Exception)\b.*:", x):
            nxt = blk[k + 1] if x.endswith(":") and k + 1 < len(blk) else ""
            return f"{x} {nxt}".strip()[:160]
    return f"exit {code}" + (" (killed: out of memory or stopped by hand)" if code == "137" else "")


procs = []
for p in Path("/proc").glob("[0-9]*"):
    try:
        cmd = " ".join(c.decode(errors="ignore") for c in (p / "cmdline").read_bytes().split(b"\0") if c)
        cwd = os.path.realpath(p / "cwd")
    except Exception:
        continue
    if "check_run.py" in cmd and "--quarantine" in cmd:
        procs.append(("checking existing forecasts (minutes, silent)", cwd))
    elif re.search(r"floatcsep stage\b", cmd):
        procs.append(("staging: clone / build images", cwd))
    elif re.search(r"floatcsep run\b", cmd):
        procs.append(("running forecasts", cwd))
    elif "check_run.py" in cmd:
        procs.append(("final check", cwd))

scr = sh("screen -ls")
print(f"#### {socket.gethostname()}  {sh('date -u +%FT%TZ').strip()}  ({root})")
for run in names:
    d = root / "runs" / run
    if not (d / "config.yml").exists():
        print(f"\n== {run}: no runs/{run}/config.yml")
        continue
    cfg = yaml.safe_load((d / "config.yml").read_text())
    ms = yaml.safe_load((d / cfg["model_config"]).read_text())
    wins = windows(cfg["time_config"])
    log = d / "results" / "run.log"
    txt = log.read_text(errors="ignore") if log.exists() else ""
    lines = txt.splitlines()
    ph = [x for x, c in procs if os.path.realpath(d) == c]
    on = re.search(rf"\d+\.{re.escape(run)}\s", scr)
    last = [x for x in lines if x.startswith("== ")][-1:] or ["never started"]
    print(f"\n== {run}: {wins[0][0]} to {wins[-1][1]}, {len(wins)} windows | screen: {'yes' if on else 'no'}"
          f" | now: {ph[0] if ph else 'nothing running'}")
    print(f"   last: {last[0].lstrip('= ')}")

    lost = {}
    for i, x in enumerate(lines):
        m = fail.search(x)
        if m and ts.match(x):
            lost[m.group(2)] = (m.group(1), m.group(3), i)
    row, errs = [], []
    for e in ms:
        name = next(iter(e)); v = e[name]
        pre = v.get("prefix", name)
        fd = (d / v["path"] / "forecasts").resolve()
        have = sum((fd / f"{pre}_{s}_{t}.csv").exists() for s, t in wins)
        bad = fd.parent / "forecasts_bad"
        nb = len(list(bad.glob(f"{pre}_*.csv"))) if bad.exists() else 0
        row.append(f"{name} {have}/{len(wins)}" + (f" (bad {nb})" if nb else ""))
        for task, (mn, code, i) in lost.items():
            if mn != name:
                continue
            win = task[len(name) + 1:]
            if not (fd / f"{pre}_{win}.csv").exists():
                errs.append(f"{name} {win[:10]}: {reason(lines, i, code)}")
    print("   " + "  ".join(row))
    if errs:
        print(f"   failed and still missing: {len(errs)}")
        for x in errs[:8]:
            print(f"     {x}")
        if len(errs) > 8:
            print(f"     ... {len(errs) - 8} more")
    nmap = sum(f.read_text(errors="ignore").count("MAP at a bound") for f in (d / "results").glob("*.log"))
    if nmap:
        print(f"   inlabru 'MAP at a bound' warnings: {nmap}")
    chk = d / "results" / "check.log"
    if chk.exists():
        tot = [x for x in chk.read_text(errors="ignore").splitlines() if "total:" in x]
        if tot:
            print(f"   last check ({sh(f'date -u -r {chk} +%FT%TZ').strip()}): {tot[-1].lstrip('= ')}")

imgs = sh("docker ps --format '{{.Image}}'").split()
cnt = {i: imgs.count(i) for i in sorted(set(imgs))}
print(f"\ncontainers: {len(imgs)}" + (" (" + ", ".join(f"{k} {v}" for k, v in cnt.items()) + ")" if cnt else ""))
du = shutil.disk_usage(root)
print(f"disk: {du.free / 1e9:.0f} GB free of {du.total / 1e9:.0f} GB")
done = root / "runs" / "DONE.log"
if done.exists():
    print("finished runs (runs/DONE.log):")
    for x in done.read_text().splitlines()[-4:]:
        print(f"  {x}")
