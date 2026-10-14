#!/usr/bin/env bash
# Runtime of one model vs number of catalogs and vs parallel containers, on fixed days.
# Each case is its own run (runs/timing_*) and model folder (models_timing/*), so nothing is reused.
# Only `floatcsep run` is timed (staging excluded). Writes runs/timing.csv: case,n_sims,workers,seconds,files
#
# usage: scripts/timing.sh [MODEL] [START] [END]      default vetas 2016-08-24 2016-09-03 (10 days)
#   NSIMS="1000 2000 ..." (workers = number of days)   WORKERS="1 2 5 10" (at NPAR catalogs, default 20000)
cd "$(dirname "$0")/.."
ENV=${ENV-testing_italy_td}
if [ -n "$ENV" ] && [ "$CONDA_DEFAULT_ENV" != "$ENV" ]; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$ENV" || exit 1
fi
export TZ=UTC PYTHONUNBUFFERED=1
m=${1:-vetas}; t0=${2:-2016-08-24}; t1=${3:-2016-09-03}
ndays=$(( ($(date -ud "$t1" +%s) - $(date -ud "$t0" +%s)) / 86400 ))
nsims=${NSIMS:-1000 2000 5000 10000 20000 50000 100000}
workers=${WORKERS:-1 2 5 10}
npar=${NPAR:-20000}
out=runs/timing.csv
[ -f $out ] || echo "case,n_sims,workers,seconds,files" > $out

one() {
    local run=$1 n=$2 w=$3
    python scripts/prepare_runs.py $run --start $t0 --end $t1 --models $m --nsims $n --workers $w \
        --models-dir models_timing/${run#timing_} > /dev/null || return
    (cd runs/$run && floatcsep stage config.yml > stage.log 2>&1)
    local s=$(date +%s.%N)
    (cd runs/$run && floatcsep run config.yml > run.log 2>&1)
    local e=$(date +%s.%N)
    local f=$(ls models_timing/${run#timing_}/$m/forecasts/*.csv 2>/dev/null | wc -l)
    echo "$4,$n,$w,$(echo "$e - $s" | bc),$f" | tee -a $out
}

for n in $nsims; do one timing_n$n $n $ndays nsims; done
for w in $workers; do one timing_w$w $npar $w workers; done
msg="italy_td timing on $(hostname) finished $(date -u +%FT%TZ)"
echo "$msg"; wall "$msg" 2>/dev/null || true
