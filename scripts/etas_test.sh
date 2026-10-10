#!/usr/bin/env bash
# Integration test of vetas, fletas and petai on a server, before any production run.
#   1. access: git ls-remote of the three GFZ repos (stops with a warning if one fails)
#   2. per model, scripts/server_test.sh: fresh clone, image build, one window, 4 windows
#      sequential (all cores) vs parallel (n_jobs 1), identical forecasts, memory
#   3. the three models in one parallel experiment around Norcia (4 windows, N-test)
#   4. N_BIG catalogs for one day, each model alone with all cores (time, memory, N-test)
#   5. counts report: forecast numbers vs observed for every window, mainshock days marked
# Test forecasts are moved out of models/<name>/forecasts at the end, so production runs
# (force_rerun False) start from empty folders.
#
# usage: bash scripts/etas_test.sh [N_SMALL=2000] [N_BIG=100000] [BIG_DAY=2016-08-25]
# run inside screen:  screen -S itd-etas ; conda activate testing_italy_td ; bash scripts/etas_test.sh
set -uo pipefail
cd "$(dirname "$0")/.."
export TZ=UTC
# never wait for a password, passphrase or host-key prompt
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=20"

nsmall=${1:-2000}
nbig=${2:-100000}
bigday=${3:-2016-08-25}
models="vetas fletas petai"
out=results/etas_test
stamp=$(date -u +%Y%m%dT%H%M)
[ -d "$out" ] && mv "$out" "${out}_old_$stamp"
mkdir -p "$out"
exec > >(tee "$out/console.log") 2>&1

t0=$(date +%s)
declare -a summary
step() { echo; echo "== [$(date -u +%H:%M:%S)] $*"; }
ok() { echo "  OK   $*"; summary+=("OK   $*"); }
bad() { echo "  FAIL $*"; summary+=("FAIL $*"); }
mins() { local s=$(( $(date +%s) - $1 )); printf '%d:%02d' $((s / 60)) $((s % 60)); }
finish() {
    {
        echo "================ ETAS INTEGRATION SUMMARY (paste this back) ================"
        echo "host $(hostname), $(nproc) cores, $(free -g | awk '/Mem:/{print $2}') GB RAM, italy_td $(git log -1 --format=%h 2>/dev/null)"
        echo "n_small $nsmall, n_big $nbig on $bigday, total $(mins $t0), finished $(date -u '+%F %H:%M') UTC"
        printf '%s\n' "${summary[@]}"
        [ -f "$out/runs.csv" ] && { echo; echo "-- runs"; column -s, -t < "$out/runs.csv"; }
        [ -f "$out/counts.txt" ] && cat "$out/counts.txt"
        echo
        echo "logs: $out/ (console.log, etas_*.log), results/server_test/<model>/"
        echo "============================================================================"
    } > "$out/report.txt"
    echo; cat "$out/report.txt"
    exit "${1:-0}"
}

entry() {  # giturl repo_hash path prefix of a model
    python - "$1" <<'EOF'
import sys, yaml
m = next(i for i in yaml.safe_load(open("models.yml")) if sys.argv[1] in i)[sys.argv[1]]
print(m.get("giturl", "-"), m.get("repo_hash", "-"), m["path"], m.get("prefix", sys.argv[1]))
EOF
}

# 1. access
step "access to the model repositories"
python -c "import floatcsep" 2>/dev/null || { bad "floatcsep not importable (conda activate testing_italy_td)"; finish 1; }
denied=0
for m in $models; do
    read -r url hash path pfx < <(entry "$m")
    if timeout 90 git ls-remote --exit-code "$url" "$hash" > "$out/ls-remote_$m.txt" 2>&1; then
        ok "$m: $url $hash ($(cut -c1-8 "$out/ls-remote_$m.txt" | head -1))"
    else
        bad "$m: cannot read $url branch $hash"
        sed 's/^/       /' "$out/ls-remote_$m.txt" | tail -5
        denied=1
    fi
done
if [ $denied -eq 1 ]; then
    echo
    echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "  WARNING: this server cannot clone at least one model repository. Nothing was run."
    echo "  Check as this user:  ssh -T git@git.gfz-potsdam.de   (key loaded? host key known?)"
    echo "  then:  git ls-remote <giturl> italy_v1"
    echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    finish 2
fi

# 2. per model: clone, build, smoke, sequential vs parallel
ready=""
for m in $models; do
    read -r url hash path pfx < <(entry "$m")
    step "$m: server_test.sh ($nsmall catalogs, 4 windows from 2016-08-24)"
    if [ -d "$path" ]; then
        mkdir -p "models/_old_$stamp"
        mv "$path" "models/_old_$stamp/" && echo "  .... previous $path moved to models/_old_$stamp/ (fresh clone)"
    fi
    docker rmi "${m}_image" > /dev/null 2>&1 && echo "  .... removed old ${m}_image (fresh build)"
    tm=$(date +%s)
    bash scripts/server_test.sh "$m" "$nsmall" 4 2016-08-24 > /dev/null 2>&1
    rc=$?
    sed -n '/= SUMMARY/,/^====/p' "results/server_test/$m/console.log" | sed '1d;$d' | sed 's/^/  /'
    if [ $rc -eq 0 ] && ! grep -q "^FAIL" <(sed -n '/= SUMMARY/,/^====/p' "results/server_test/$m/console.log"); then
        ok "$m server_test in $(mins $tm)"
    else
        bad "$m server_test exit $rc in $(mins $tm) (results/server_test/$m/console.log)"
    fi
    mkdir -p "$out/fc_$nsmall"
    cp "$path"/forecasts/"${pfx}"_2016-08-2[4-7]_*.csv "$out/fc_$nsmall/" 2>/dev/null
    [ -f "$path/forecasts/${pfx}_2016-08-25_2016-08-26.csv" ] && docker image inspect "${m}_image" > /dev/null 2>&1 \
        && ready="$ready $m"
done
ready=${ready# }
[ -z "$ready" ] && { bad "no model produced forecasts, stopping"; finish 1; }
[ "$ready" != "$models" ] && echo "  .... continuing with: $ready"

# 3. all models in one parallel experiment
step "$ready together, run_mode parallel, n_jobs 1, 2016-10-28..2016-10-31 (Norcia), $nsmall catalogs"
tm=$(date +%s)
python scripts/etas_test.py run all --models $ready --start 2016-10-28 --days 4 --nsims "$nsmall" \
    --mode parallel --out "$out" | sed 's/^/  /'
[ "${PIPESTATUS[0]}" -eq 0 ] && ok "joint parallel run in $(mins $tm)" || bad "joint parallel run (see $out/etas_all.log)"

# 4. big run, one model at a time, all cores
for m in $ready; do
    step "$m: $nbig catalogs on $bigday, all cores"
    tm=$(date +%s)
    python scripts/etas_test.py run "big_$m" --models "$m" --start "$bigday" --days 1 --nsims "$nbig" \
        --mode sequential --all-cores --out "$out" | sed 's/^/  /'
    [ "${PIPESTATUS[0]}" -eq 0 ] && ok "$m $nbig catalogs in $(mins $tm)" || bad "$m $nbig catalogs (see $out/etas_big_$m.log)"
done

# 5. counts
step "counts report"
python scripts/etas_test.py report --out "$out" > /dev/null 2>&1 \
    && ok "counts in $out/counts.txt / counts.csv" || bad "counts report failed"

# test forecasts out of the production folders
for m in $models; do
    read -r url hash path pfx < <(entry "$m")
    if ls "$path"/forecasts/*.csv > /dev/null 2>&1; then
        mkdir -p "$out/model_forecasts/$m"
        mv "$path"/forecasts/*.csv "$out/model_forecasts/$m/"
    fi
done
echo "  .... test forecasts moved to $out/model_forecasts/ (models/<name>/forecasts is empty again)"
finish 0
