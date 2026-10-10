#!/usr/bin/env bash
# One model, one window: build, run through floatcsep, validate the forecast.
# usage: [TESTS=tests_n.yml] scripts/smoke_test.sh MODEL [START=2016-08-24] [N_SIMS=100] [CATALOG]
set -euo pipefail
cd "$(dirname "$0")/.."

name=$1
start=${2:-2016-08-24}
nsims=${3:-100}
cat=${4:-}
tag=smoke_$name

mkdir -p results
python scripts/make_config.py --model "$name" --start "$start" --days 1 --nsims "$nsims" \
    --run-dir "results/$tag" ${cat:+--catalog "$cat"} ${TESTS:+--tests "$TESTS"} --rerun --out ".$tag" > ".$tag.info"
read -r path prefix nsims end < ".$tag.info"

# build the model environment and stage the source
floatcsep stage ".${tag}_config.yml" -d 2>&1 | tee "results/$tag.stage.log"

# one window
floatcsep run ".${tag}_config.yml" -d 2>&1 | tee "results/$tag.run.log"

awk -F, 'NR>1{if(m==""||$3<m)m=$3} END{print "input catalog: " NR-1 " events, min mag " m}' "$path/input/catalog.csv"

fc="$path/forecasts/${prefix}_${start}_${end}.csv"
if [ ! -f "$fc" ]; then
    echo "missing forecast $fc"
    ls "$path/forecasts" || true
    exit 1
fi
python scripts/check_forecast.py "$fc" --n-sims "$nsims" --mag-min 4.0 --prefix "$prefix"
