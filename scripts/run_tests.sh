#!/usr/bin/env bash
# Test forecast runs with floatCSEP, split into one test run per month, K months side by side.
# Each month becomes runs/<run>_t<YYYYMM>/ (scripts/prepare_tests.py --days ...), floatCSEP finds the
# forecasts on disk and only evaluates. Months already finished (results/DONE) are skipped.
# With ACTIVE=1 only the days with observed events (M >= mag_min in the test region) are tested, in
# runs/<run>_e<YYYYMM>/, with tests_td_slm.yml (S, M, L, MLL) by default.
#
# usage: scripts/run_tests.sh K RUN [RUN ...]          e.g. scripts/run_tests.sh 60 full_2016 full_2018
#        ACTIVE=1 scripts/run_tests.sh K RUN [RUN ...]
#   TESTS=file.yml  test config;  ENV=name conda env (default testing_italy_td), ENV= current env
cd "$(dirname "$0")/.."
ENV=${ENV-testing_italy_td}
if [ -n "$ENV" ] && [ "$CONDA_DEFAULT_ENV" != "$ENV" ]; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$ENV" || exit 1
fi
export TZ=UTC PYTHONUNBUFFERED=1 ACTIVE
k=$1; shift
if [ -n "$ACTIVE" ]; then
    tests=${TESTS:-tests_td_slm.yml}; tag=e
else
    tests=${TESTS:-tests_td.yml}; tag=t
fi
dirs=()
for run in "$@"; do
    while read -r ym days; do
        out=${run}_$tag$ym
        if [ ! -f runs/$out/results/DONE ]; then
            python scripts/prepare_tests.py "$run" --tests "$tests" --days $days --out "$out" --workers 4 > /dev/null || exit 1
            dirs+=("$out")
        fi
    done < <(python - "$run" <<'P'
import os, sys
from datetime import timedelta
from pathlib import Path
import pandas as pd
import yaml
d = Path("runs") / sys.argv[1]
cfg = yaml.safe_load((d / "config.yml").read_text())
tc = cfg["time_config"]
if tc.get("time_windows"):
    days = [w[0] for w in tc["time_windows"]]
else:
    days, t = [], tc["start_date"]
    while t < tc["end_date"]:
        days.append(t)
        t += timedelta(days=1)
if os.environ.get("ACTIVE"):
    from csep.core import regions
    rc = cfg["region_config"]
    c = pd.read_csv((d / cfg["catalog"]).resolve())
    c = c[(c.mag >= rc["mag_min"] - 1e-6) & (c.depth >= rc.get("depth_min", 0)) & (c.depth < rc.get("depth_max", 1e9))]
    c = c[~getattr(regions, rc["region"])().get_masked(c.lon.to_numpy(), c.lat.to_numpy())]
    on = set(c.time_string.str[:10])
    days = [x for x in days if f"{x:%Y-%m-%d}" in on]
mon = {}
for x in days:
    mon.setdefault(f"{x:%Y%m}", []).append(f"{x:%Y-%m-%d}")
for m, ds in mon.items():
    print(m, " ".join(ds))
P
)
done
echo "== $(date -u +%FT%TZ) $(hostname): ${#dirs[@]} monthly test runs ($tests), $k at once" | tee -a runs/TESTS.log
printf '%s\n' "${dirs[@]}" | xargs -P "$k" -I{} bash -c \
    'cd runs/{} && floatcsep run config.yml > floatcsep.log 2>&1; n=$(ls results/*/evaluations/*.json 2>/dev/null | wc -l); touch results/DONE; echo "$(date -u +%T) {} $n results" | tee -a ../TESTS.log'
msg="italy_td tests ($tests) on $(hostname) finished $(date -u +%FT%TZ): $*"
echo "$msg" | tee -a runs/TESTS.log; wall "$msg" 2>/dev/null || true
