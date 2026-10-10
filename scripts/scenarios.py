"""Run the experiment through a set of scenarios with the pymock models and check the outputs.

Scenarios
---------
multi      5 consecutive windows from 2016-08-24, one forecast and one N-test per window
rerun      same config again with force_rerun False: nothing recomputed
reproduce  floatcsep reproduce on the multi run (evaluations only, forecasts are reused)
restart    kill a 5-window run after 2 forecasts, start again: finishes, no broken files
busy       one window on 2016-10-30 (Norcia M6.5): runtime and sizes on the busiest day
quiet      one window without M >= mag_min events: N-test with an empty test catalog
two        mock and mock_nb in one config: same input, both evaluated, joint plot
parallel   run_mode parallel, 2 models x 3 windows: per-window inputs used by the models, and
           the same mock forecasts as the sequential multi run (no look-ahead in either mode)
seed       same window twice with force_rerun: identical forecast files

All scenarios share models/<name>/forecasts, so they use separate windows and run in this order.
Every N-test result must use n_sims catalogs.

usage: python scripts/scenarios.py [SCENARIO ...] [--nsims 100] [--build docker]
"""
import argparse
import hashlib
import json
import shutil
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "scripts"))
from check_forecast import check  # noqa: E402

ALL = ["multi", "rerun", "reproduce", "restart", "busy", "quiet", "two", "parallel", "seed"]
TEST = "Catalog_N-test"


# config
def windows(start, days):
    t0 = date.fromisoformat(start)
    return [f"{t0 + timedelta(i)}_{t0 + timedelta(i + 1)}" for i in range(days)]


def write_cfg(name, models, start, days, nsims, build, rerun=True, mode="sequential"):
    """Write .scen_{name}_config.yml and .scen_{name}_models.yml at the repo root."""
    cfg = yaml.safe_load((root / "config.yml").read_text())
    allm = yaml.safe_load((root / "models.yml").read_text())
    ms = []
    for m in models:
        e = next(i for i in allm if m in i)
        e[m]["func_kwargs"]["n_sims"] = nsims
        e[m]["build"] = build
        ms.append(e)
    t0 = date.fromisoformat(start)
    cfg["time_config"]["start_date"] = datetime(t0.year, t0.month, t0.day)
    cfg["time_config"]["end_date"] = cfg["time_config"]["start_date"] + timedelta(days)
    cfg.update(
        model_config=f".scen_{name}_models.yml",
        test_config="tests_n.yml",
        run_dir=f"results/scen_{name}",
        force_rerun=rerun,
        run_mode=mode,
        stage_dir=f"results/scen_{name}",
        postprocess={"plot_catalog": False, "plot_forecasts": False},
    )
    (root / f".scen_{name}_models.yml").write_text(yaml.safe_dump(ms, sort_keys=False))
    f = root / f".scen_{name}_config.yml"
    f.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return f


def model_info(name):
    m = next(i for i in yaml.safe_load((root / "models.yml").read_text()) if name in i)[name]
    return root / m["path"], m.get("prefix", name)


# run
def floatcsep(cmd, cfg, log, kill_after=None):
    """Run floatcsep, logging to file. kill_after=(path, n): SIGINT once n files match."""
    exe = shutil.which("floatcsep") or str(Path(sys.executable).parent / "floatcsep")
    t = time.time()
    with open(log, "a") as f:
        p = subprocess.Popen([exe, cmd, str(cfg), "-d"], cwd=root, stdout=f, stderr=subprocess.STDOUT)
        killed = False
        while p.poll() is None:
            if kill_after and len(list(kill_after[0].glob(kill_after[1]))) >= kill_after[2]:
                p.send_signal(signal.SIGINT)
                killed = True
                break
            time.sleep(0.5)
        try:
            p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            p.kill()
    return p.returncode, time.time() - t, killed


def runs(log, model):
    return Path(log).read_text().count(f"[Model] Running {model} ")


def errors(log):
    txt = Path(log).read_text().splitlines()
    return [i for i in txt if "exited with code" in i or "[Engine] Fail" in i or "build error" in i]


# checks
def fc_path(model, win):
    path, prefix = model_info(model)
    return path / "forecasts" / f"{prefix}_{win}.csv"


def check_fc(model, win, nsims, out):
    f = fc_path(model, win)
    if not f.exists():
        out.append((False, f"{model} {win}: no forecast"))
        return
    res = check(f, nsims, prefix=model_info(model)[1])
    bad = [f"{n}: {m}" for s, n, m in res if s == "FAIL"]
    warn = [f"{n}: {m}" for s, n, m in res if s == "WARN"]
    info = [m for s, n, m in res if s == "INFO"]
    out.append((not bad, f"{model} {win}: " + ("; ".join(bad) or (info[0] if info else "ok"))))
    for w in warn:
        out.append((True, f"{model} {win}: warn {w}"))


def check_res(name, model, win, nsims, out):
    f = root / "results" / f"scen_{name}" / win / "evaluations" / f"{TEST}_{model}.json"
    if not f.exists():
        out.append((False, f"{model} {win}: no {TEST} result"))
        return None
    r = json.loads(f.read_text())
    n = len(r["test_distribution"])
    q = ", ".join(f"{i:.3f}" for i in r["quantile"])
    msg = f"{model} {win}: N obs {r['observed_statistic']}, quantiles ({q}), {n} catalogs"
    out.append((n == nsims, msg + ("" if n == nsims else f" (expected {nsims})")))
    return r


def input_cat(path):
    d = pd.read_csv(path)
    return len(d), (pd.to_datetime(d["time_string"], format="ISO8601").max() if len(d) else None)


def sha(f):
    return hashlib.sha256(Path(f).read_bytes()).hexdigest()


# scenarios
def sc_multi(a, out):
    ws = windows("2016-08-24", 5)
    cfg = write_cfg("multi", ["mock"], "2016-08-24", 5, a.nsims, a.build)
    rc, dt, _ = floatcsep("run", cfg, a.log)
    out.append((rc == 0, f"exit code {rc}, {dt:.0f} s, {dt / len(ws):.1f} s per window"))
    out.append((runs(a.log, "mock") == len(ws), f"model ran {runs(a.log, 'mock')} times"))
    for w in ws:
        check_fc("mock", w, a.nsims, out)
        check_res("multi", "mock", w, a.nsims, out)
    n, last = input_cat(model_info("mock")[0] / "input" / "catalog.csv")
    ok = last is not None and last < pd.Timestamp(ws[-1].split("_")[0])
    out.append((ok, f"last input catalog: {n} events, last event {last} (before {ws[-1][:10]})"))
    hs = {w: sha(fc_path("mock", w)) for w in ws if fc_path("mock", w).exists()}
    (root / "results" / "scenarios" / "multi_hashes.json").write_text(json.dumps(hs, indent=1))


def sc_rerun(a, out):
    ws = windows("2016-08-24", 5)
    t0 = {w: fc_path("mock", w).stat().st_mtime for w in ws if fc_path("mock", w).exists()}
    if len(t0) < len(ws):
        out.append((False, "run 'multi' first"))
        return
    cfg = write_cfg("multi", ["mock"], "2016-08-24", 5, a.nsims, a.build, rerun=False)
    rc, dt, _ = floatcsep("run", cfg, a.log)
    out.append((rc == 0, f"exit code {rc}, {dt:.0f} s"))
    out.append((runs(a.log, "mock") == 0, f"model ran {runs(a.log, 'mock')} times (expected 0)"))
    same = [w for w in ws if fc_path("mock", w).stat().st_mtime == t0[w]]
    out.append((len(same) == len(ws), f"{len(same)}/{len(ws)} forecasts untouched"))


def sc_restart(a, out):
    ws = windows("2016-09-01", 5)
    for w in ws:
        fc_path("mock", w).unlink(missing_ok=True)
    shutil.rmtree(root / "results" / "scen_restart", ignore_errors=True)
    cfg = write_cfg("restart", ["mock"], "2016-09-01", 5, a.nsims, a.build, rerun=False)
    fdir = model_info("mock")[0] / "forecasts"
    pat = f"{model_info('mock')[1]}_2016-09-0*.csv"
    rc, dt, killed = floatcsep("run", cfg, a.log, kill_after=(fdir, pat, 2))
    done = [w for w in ws if fc_path("mock", w).exists()]
    out.append((killed, f"first run interrupted after {dt:.0f} s with {len(done)} forecasts"))
    n0 = runs(a.log, "mock")
    rc, dt, _ = floatcsep("run", cfg, a.log)
    n = runs(a.log, "mock") - n0
    out.append((rc == 0, f"second run: exit code {rc}, {dt:.0f} s"))
    out.append((n == len(ws) - len(done), f"second run ran the model {n} times ({len(done)} kept)"))
    for w in ws:
        check_fc("mock", w, a.nsims, out)
        check_res("restart", "mock", w, a.nsims, out)


def sc_busy(a, out):
    w = windows("2016-10-30", 1)[0]
    cfg = write_cfg("busy", ["mock"], "2016-10-30", 1, a.nsims, a.build)
    rc, dt, _ = floatcsep("run", cfg, a.log)
    out.append((rc == 0, f"exit code {rc}, {dt:.0f} s for one window"))
    n, last = input_cat(model_info("mock")[0] / "input" / "catalog.csv")
    out.append((True, f"input catalog: {n} events, last {last}"))
    check_fc("mock", w, a.nsims, out)
    f = fc_path("mock", w)
    if f.exists():
        mb = f.stat().st_size / 1e6
        out.append((True, f"forecast {mb:.2f} MB at n_sims {a.nsims} (~{mb * 1000 / a.nsims:.1f} MB at 1000)"))
    check_res("busy", "mock", w, a.nsims, out)


def sc_quiet(a, out):
    cfg = yaml.safe_load((root / "config.yml").read_text())
    mmin = cfg["region_config"]["mag_min"]
    d = pd.read_csv(root / cfg["catalog"])
    days = set(pd.to_datetime(d.loc[d["mag"] >= mmin, "time_string"], format="ISO8601").dt.date)
    t = date(2016, 9, 6)
    while t in days:
        t += timedelta(1)
    w = windows(str(t), 1)[0]
    cfg = write_cfg("quiet", ["mock"], str(t), 1, a.nsims, a.build)
    rc, dt, _ = floatcsep("run", cfg, a.log)
    out.append((rc == 0, f"exit code {rc}, window {w} has no M >= {mmin} events"))
    check_fc("mock", w, a.nsims, out)
    r = check_res("quiet", "mock", w, a.nsims, out)
    if r:
        out.append((r["observed_statistic"] == 0, f"observed N = {r['observed_statistic']}"))


def sc_two(a, out):
    w = windows("2016-08-24", 1)[0]
    cfg = write_cfg("two", ["mock", "mock_nb"], "2016-08-24", 1, a.nsims, a.build)
    rc, dt, _ = floatcsep("run", cfg, a.log)
    out.append((rc == 0, f"exit code {rc}, {dt:.0f} s"))
    cats = [model_info(m)[0] / "input" / "catalog.csv" for m in ("mock", "mock_nb")]
    same = all(c.exists() for c in cats) and sha(cats[0]) == sha(cats[1])
    out.append((same, "both models got the same input catalog"))
    for m in ("mock", "mock_nb"):
        check_fc(m, w, a.nsims, out)
        check_res("two", m, w, a.nsims, out)
    fig = root / "results" / "scen_two" / w / "figures" / f"{TEST}.png"
    out.append((fig.exists(), f"joint figure {fig.relative_to(root)}"))


def sc_parallel(a, out):
    ws = windows("2016-08-26", 3)
    for m in ("mock", "mock_nb"):
        for w in ws:
            fc_path(m, w).unlink(missing_ok=True)
    cfg = write_cfg("parallel", ["mock", "mock_nb"], "2016-08-26", 3, a.nsims, a.build, mode="parallel")
    rc, dt, _ = floatcsep("run", cfg, a.log)
    out.append((rc == 0, f"exit code {rc}, {dt:.0f} s"))
    prev = 0
    for w in ws:
        f = root / "results" / "scen_parallel" / w / "input" / "mock" / "catalog.csv"
        if not f.exists():
            out.append((False, f"{w}: no per-window input catalog"))
            continue
        n, last = input_cat(f)
        ok = n >= prev and last < pd.Timestamp(w[:10])
        out.append((ok, f"{w}: input {n} events, last {last}"))
        prev = n
    for m in ("mock", "mock_nb"):
        for w in ws:
            check_fc(m, w, a.nsims, out)
            check_res("parallel", m, w, a.nsims, out)
    f = root / "results" / "scenarios" / "multi_hashes.json"
    if f.exists():
        hs = json.loads(f.read_text())
        same = [w for w in ws if w in hs and fc_path("mock", w).exists() and sha(fc_path("mock", w)) == hs[w]]
        common = [w for w in ws if w in hs]
        out.append((len(same) == len(common), f"mock: {len(same)}/{len(common)} forecasts identical to the sequential multi run"))


def sc_seed(a, out):
    w = windows("2016-09-15", 1)[0]
    hs = []
    for i in range(2):
        cfg = write_cfg("seed", ["mock"], "2016-09-15", 1, a.nsims, a.build)
        rc, dt, _ = floatcsep("run", cfg, a.log)
        f = fc_path("mock", w)
        hs.append(sha(f) if f.exists() else None)
        out.append((rc == 0 and hs[-1] is not None, f"run {i + 1}: exit code {rc}, {dt:.0f} s"))
    out.append((hs[0] is not None and hs[0] == hs[1], "forecast identical in both runs"))


def sc_reproduce(a, out):
    cfg = root / "results" / "scen_multi" / "repr_config.yml"
    if not cfg.exists():
        out.append((False, "run 'multi' first"))
        return
    rc, dt, _ = floatcsep("reproduce", cfg, a.log)
    out.append((rc == 0, f"exit code {rc}, {dt:.0f} s"))
    rep = list((root / "results").rglob("reproducibility_report.md"))
    out.append((bool(rep), f"report: {rep[0].relative_to(root) if rep else 'missing'}"))
    if rep:
        txt = rep[0].read_text()
        out.append(("False" not in txt, "no mismatch reported" if "False" not in txt else "mismatch in report"))


# main
if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenarios", nargs="*", default=ALL, help=f"default: all ({', '.join(ALL)})")
    p.add_argument("--nsims", type=int, default=100)
    p.add_argument("--build", default="docker", help="docker (default), conda or venv")
    a = p.parse_args()
    bad = set(a.scenarios) - set(ALL)
    if bad:
        p.error(f"unknown scenarios {sorted(bad)}")

    (root / "results" / "scenarios").mkdir(parents=True, exist_ok=True)
    summary = []
    for s in a.scenarios:
        a.log = root / "results" / "scenarios" / f"{s}.log"
        a.log.write_text("")
        print(f"\n== {s}", flush=True)
        out = []
        try:
            globals()[f"sc_{s}"](a, out)
        except Exception as e:
            out.append((False, f"error: {type(e).__name__}: {e}"))
        for e in errors(a.log):
            out.append((False, e.split("] ", 1)[-1][:150]))
        for ok, msg in out:
            print(f"  {'ok  ' if ok else 'FAIL'} {msg}")
        summary.append((s, all(ok for ok, _ in out)))
        print(f"  log: {a.log.relative_to(root)}", flush=True)

    print("\n== summary")
    for s, ok in summary:
        print(f"  {'PASS' if ok else 'FAIL'} {s}")
    sys.exit(0 if all(ok for _, ok in summary) else 1)
