"""Check every forecast a run (runs/<name>) should have produced.

For each model and window: missing, FAIL (check_forecast.py), suspicious, or ok. Suspicious means
the file may be truncated (container killed mid-write): floatCSEP's results/run.log has no
completed create_forecast task for that window, or a busy day (>= 1000 events) has no event in the
last 2% of catalog ids. --quarantine moves FAIL and suspicious files to <model>/forecasts_bad/, so
the next floatcsep run regenerates them.

usage: python scripts/check_run.py runs/amatrice [--models vetas] [--quarantine] [--full]
"""
import argparse
import re
import shutil
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_forecast import check  # noqa: E402

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("folder", help="folder with config.yml and models.yml")
p.add_argument("--models", nargs="+")
p.add_argument("--quarantine", action="store_true")
p.add_argument("--full", action="store_true", help="print every window, not only problems")
a = p.parse_args()

d = Path(a.folder)
cfg = yaml.safe_load((d / "config.yml").read_text())
ms = yaml.safe_load((d / cfg["model_config"]).read_text())
tc = cfg["time_config"]
if tc.get("time_windows"):
    wins = [(w[0].date(), w[1].date()) for w in tc["time_windows"]]
else:
    wins = []
    t = tc["start_date"]
    while t < tc["end_date"]:
        wins.append((t.date(), (t + timedelta(days=1)).date()))
        t += timedelta(days=1)
mag_min = cfg["region_config"]["mag_min"]

# windows with a completed create_forecast task, per model, from floatCSEP's logs
done = {}
pat = re.compile(r"\[Engine\] Done\s*\n\s*Class: \w+\n\s*Name: (\S+)\n\s*Method: create_forecast\n\s*tstring: (\S+)")
for log in (d / "results").glob("*.log"):
    for name, win in pat.findall(log.read_text(errors="ignore")):
        done.setdefault(name, set()).add(win)

tot = {"ok": 0, "missing": 0, "FAIL": 0, "suspicious": 0}
for m in ms:
    name = next(iter(m)); e = m[name]
    if a.models and name not in a.models:
        continue
    pre = e.get("prefix", name)
    nsims = e["func_kwargs"]["n_sims"]
    fdir = (d / e["path"] / "forecasts").resolve()
    bad = fdir.parent / "forecasts_bad"
    cnt = {"ok": 0, "missing": 0, "FAIL": 0, "suspicious": 0}
    print(f"\n== {name}: {len(wins)} windows, n_sims {nsims}, {fdir}")
    for s, en in wins:
        f = fdir / f"{pre}_{s}_{en}.csv"
        if not f.exists():
            st, msg = "missing", ""
        else:
            res = check(f, nsims, mag_min=mag_min, prefix=pre)
            fails = [f"{n}: {x}" for k, n, x in res if k == "FAIL"]
            if fails:
                st, msg = "FAIL", "; ".join(fails)
            else:
                df = pd.read_csv(f, usecols=["catalog_id"])
                top = df["catalog_id"].max() if len(df) else -1
                win = f"{s}_{en}"
                if done and win not in done.get(name, ()):
                    st, msg = "suspicious", f"no completed run in results/*.log, {len(df)} events"
                elif len(df) >= 1000 and top < 0.98 * nsims - 1:
                    st, msg = "suspicious", f"max catalog_id {top} of {nsims - 1}, {len(df)} events"
                else:
                    st, msg = "ok", f"{len(df)} events, {df['catalog_id'].nunique() if len(df) else 0} catalogs"
        cnt[st] += 1
        if st != "ok" or a.full:
            print(f"  {st:10s} {s}  {msg}")
        if a.quarantine and st in ("FAIL", "suspicious"):
            bad.mkdir(exist_ok=True)
            shutil.move(f, bad / f.name)
            print(f"             moved to {bad.name}/")
    print(f"  {cnt['ok']} ok, {cnt['missing']} missing, {cnt['FAIL']} fail, {cnt['suspicious']} suspicious")
    for k in tot:
        tot[k] += cnt[k]

print(f"\n== total: {tot['ok']} ok, {tot['missing']} missing, {tot['FAIL']} fail, {tot['suspicious']} suspicious")
sys.exit(0 if tot["missing"] + tot["FAIL"] + tot["suspicious"] == 0 else 1)
