#!/usr/bin/env bash
# Run prepared forecast runs one after the other (runs/<name>, see prepare_runs.py), then check each.
# A failing run does not stop the next one. Restartable: existing forecasts are kept.
#
# usage: scripts/run_forecasts.sh RUN [RUN ...]          e.g. amatrice full_b
#   ENV=name  conda env to activate (default testing_italy_td); ENV= keeps the current env
cd "$(dirname "$0")/.."
root=$PWD
ENV=${ENV-testing_italy_td}
if [ -n "$ENV" ]; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$ENV" || exit 1
fi
export TZ=UTC
export PYTHONUNBUFFERED=1

for run in "$@"; do
    d=runs/$run
    if [ ! -f "$d/config.yml" ]; then
        echo "no $d/config.yml, run scripts/prepare_runs.py $run first"
        continue
    fi
    cd "$root/$d"
    mkdir -p results
    echo "== $(date -u +%FT%TZ) start $run on $(hostname)" | tee -a results/run.log
    python "$root/scripts/check_run.py" . --quarantine > results/precheck.log 2>&1
    floatcsep stage config.yml -d >> results/stage.log 2>&1 || echo "stage exited $?" | tee -a results/run.log
    floatcsep run config.yml -d >> results/run.log 2>&1 || echo "floatcsep run exited $? (forecasts on disk are kept)" | tee -a results/run.log
    echo "== $(date -u +%FT%TZ) end $run" | tee -a results/run.log
    grep -h "\[Engine\] \(Calculation\|Forecasts /\)" results/run.log | tail -4
    python "$root/scripts/check_run.py" . 2>&1 | tee results/check.log | tail -6
    cd "$root"
done
