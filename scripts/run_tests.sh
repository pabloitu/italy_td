#!/usr/bin/env bash
# Test forecast runs with floatCSEP, split into one test run per month, K months side by side.
# Each month becomes runs/<run>_t<YYYYMM>/ (scripts/prepare_tests.py --days ...), floatCSEP finds the
# forecasts on disk and only evaluates. Months already finished (results/DONE) are skipped.
#
# usage: scripts/run_tests.sh K RUN [RUN ...]          e.g. scripts/run_tests.sh 60 full_2016 full_2018
#   TESTS=tests_td.yml  test config;  ENV=name conda env (default testing_italy_td), ENV= current env
cd "$(dirname "$0")/.."
ENV=${ENV-testing_italy_td}
if [ -n "$ENV" ] && [ "$CONDA_DEFAULT_ENV" != "$ENV" ]; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$ENV" || exit 1
fi
export TZ=UTC PYTHONUNBUFFERED=1
k=$1; shift
tests=${TESTS:-tests_td.yml}
dirs=()
for run in "$@"; do
    while read -r ym days; do
        out=${run}_t$ym
        if [ ! -f runs/$out/results/DONE ]; then
            python scripts/prepare_tests.py "$run" --tests "$tests" --days $days --out "$out" --workers 4 > /dev/null || exit 1
            dirs+=("$out")
        fi
    done < <(python - "$run" <<'P'
import sys, yaml
from datetime import timedelta
tc = yaml.safe_load(open(f"runs/{sys.argv[1]}/config.yml"))["time_config"]
if tc.get("time_windows"):
    days = [w[0] for w in tc["time_windows"]]
else:
    days, t = [], tc["start_date"]
    while t < tc["end_date"]:
        days.append(t)
        t += timedelta(days=1)
mon = {}
for d in days:
    mon.setdefault(f"{d:%Y%m}", []).append(f"{d:%Y-%m-%d}")
for m, ds in mon.items():
    print(m, " ".join(ds))
P
)
done
echo "== $(date -u +%FT%TZ) $(hostname): ${#dirs[@]} monthly test runs, $k at once" | tee -a runs/TESTS.log
printf '%s\n' "${dirs[@]}" | xargs -P "$k" -I{} bash -c \
    'cd runs/{} && floatcsep run config.yml > floatcsep.log 2>&1; n=$(ls results/*/evaluations/*.json 2>/dev/null | wc -l); touch results/DONE; echo "$(date -u +%T) {} $n results" | tee -a ../TESTS.log'
msg="italy_td tests on $(hostname) finished $(date -u +%FT%TZ): $*"
echo "$msg" | tee -a runs/TESTS.log; wall "$msg" 2>/dev/null || true
