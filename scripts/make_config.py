"""Derive a config (and optionally a one-model models file) from config.yml.

Prints "path prefix n_sims end_date" of the selected model when --model is given.
"""
import argparse
import re
from datetime import date, timedelta
from pathlib import Path

import yaml


def setkey(txt, k, v):
    if re.search(rf"^{k}:", txt, flags=re.M):
        return re.sub(rf"^{k}:.*$", f"{k}: {v}", txt, flags=re.M)
    return txt.rstrip("\n") + f"\n{k}: {v}\n"


a = argparse.ArgumentParser(description=__doc__)
a.add_argument("--config", default="config.yml")
a.add_argument("--models", default="models.yml")
a.add_argument("--start", help="YYYY-MM-DD, with --days sets start_date and end_date")
a.add_argument("--days", type=int, default=1)
a.add_argument("--model")
a.add_argument("--nsims", type=int)
a.add_argument("--run-dir")
a.add_argument("--catalog")
a.add_argument("--tests")
a.add_argument("--rerun", action="store_true")
a.add_argument("--out", required=True, help="output prefix, writes {out}_config.yml")
a = a.parse_args()

txt = Path(a.config).read_text()
end = None
if a.start:
    end = date.fromisoformat(a.start) + timedelta(days=a.days)
    txt = re.sub(r"(start_date:\s*)\S+", rf"\g<1>{a.start}T00:00:00", txt, count=1)
    txt = re.sub(r"(end_date:\s*)\S+", rf"\g<1>{end}T00:00:00", txt, count=1)

if a.model:
    ms = [m for m in yaml.safe_load(Path(a.models).read_text()) if a.model in m]
    if not ms:
        raise SystemExit(f"model '{a.model}' not in {a.models}")
    kw = ms[0][a.model].setdefault("func_kwargs", {})
    if a.nsims:
        kw["n_sims"] = a.nsims
    mf = f"{a.out}_models.yml"
    Path(mf).write_text(yaml.safe_dump(ms, sort_keys=False))
    txt = setkey(txt, "model_config", mf)
    print(ms[0][a.model]["path"], ms[0][a.model].get("prefix", a.model), kw.get("n_sims"), end)

if a.run_dir:
    txt = setkey(txt, "run_dir", a.run_dir)
if a.catalog:
    txt = setkey(txt, "catalog", a.catalog)
if a.tests:
    txt = setkey(txt, "test_config", a.tests)
if a.rerun:
    txt = setkey(txt, "force_rerun", "True")
Path(f"{a.out}_config.yml").write_text(txt)
