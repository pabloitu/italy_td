#!/usr/bin/env bash
# Integration test of one Docker model on a server: environment checks, clone, base image,
# smoke test (one window), sequential vs parallel (scripts/modes.py), summary to paste back.
# usage: bash scripts/server_test.sh MODEL [N_SIMS=2000] [DAYS=4] [START=2016-08-24]
# run inside screen:  screen -S itd-test ; conda activate testing_italy_td ; bash scripts/server_test.sh inlabru_td
set -uo pipefail
cd "$(dirname "$0")/.."
export TZ=UTC

name=${1:?usage: server_test.sh MODEL [N_SIMS] [DAYS] [START]}
nsims=${2:-2000}
days=${3:-4}
start=${4:-2016-08-24}
smoke_day=$(date -u -d "$start +1 day" +%F)
out=results/server_test/$name
mkdir -p "$out"
log=$out/console.log
exec > >(tee "$log") 2>&1

declare -a summary
t0=$(date +%s)
step() { echo; echo "== [$(date -u +%H:%M:%S)] $*"; }
ok() { echo "  OK   $*"; summary+=("OK   $*"); }
bad() { echo "  FAIL $*"; summary+=("FAIL $*"); }
info() { echo "  .... $*"; }
mins() { local s=$(( $(date +%s) - $1 )); printf '%d:%02d' $((s / 60)) $((s % 60)); }
finish() {
    echo; echo "================ SUMMARY (paste this back) ================"
    echo "host $(hostname), $(nproc) cores, $(free -g | awk '/Mem:/{print $2}') GB RAM, model $name, n_sims $nsims, total $(mins $t0)"
    printf '%s\n' "${summary[@]}"
    echo "logs: $out/"
    echo "==========================================================="
    exit "${1:-0}"
}

# environment
step "environment"
info "host $(hostname), $(nproc) cores, $(free -g | awk '/Mem:/{print $2" GB RAM, "$7" GB free"}'), disk free $(df -h . | awk 'NR==2{print $4}')"
info "system time zone $(cat /etc/timezone 2>/dev/null || date +%Z); this script runs with TZ=UTC"
py=$(command -v python)
info "python $py ($(python --version 2>&1)), conda env ${CONDA_DEFAULT_ENV:-none}"
fv=$(python -c "import floatcsep, csep; print(floatcsep.__version__, csep.__version__)" 2>/dev/null) \
    && ok "floatcsep / pycsep: $fv" || { bad "floatcsep not importable (conda activate testing_italy_td)"; finish 1; }
n=$(python -c "import inspect, floatcsep.infrastructure.repositories as r; print(inspect.getsource(r).count('datetime_to_utc_epoch('))")
[ "$n" -ge 6 ] && ok "floatcsep UTC time filter fix present" || bad "floatcsep without the UTC fix (count $n, expected 6)"
docker info > /dev/null 2>&1 && ok "docker usable by $(whoami) ($(docker version --format '{{.Server.Version}}'))" \
    || { bad "docker not usable without sudo (add $(whoami) to the docker group)"; finish 1; }
last=$(python -c "import pandas as p, yaml; c = yaml.safe_load(open('config.yml'))['catalog']; print(p.read_csv(c)['time_string'].max())")
info "catalog $(python -c "import yaml; print(yaml.safe_load(open('config.yml'))['catalog'])"), last event $last"

# model entry
step "model entry in models.yml"
read -r giturl hash path pfx kw < <(python - "$name" <<'EOF'
import sys, yaml, json
m = next((i for i in yaml.safe_load(open("models.yml")) if sys.argv[1] in i), None)
if m is None:
    print("MISSING - - - -"); sys.exit()
m = m[sys.argv[1]]
print(m.get("giturl", "-"), m.get("repo_hash", "-"), m["path"], m.get("prefix", sys.argv[1]),
      json.dumps(m.get("func_kwargs", {}), separators=(",", ":")))
EOF
)
[ "$giturl" = MISSING ] && { bad "$name not in models.yml"; finish 1; }
info "giturl $giturl, repo_hash $hash, path $path, prefix $pfx"
info "func_kwargs $kw"
if [ ! -d "$path" ] || [ -z "$(ls -A "$path" 2>/dev/null)" ]; then
    case "$giturl" in TODO*|-) bad "giturl not set and $path empty"; finish 1;; esac
    git ls-remote --exit-code "$giturl" "$hash" > /dev/null 2>&1 \
        && ok "remote has $hash" || { bad "git ls-remote $giturl $hash failed (URL, branch or credentials)"; finish 1; }
    git clone -q --depth 1 --branch "$hash" "$giturl" "$path" && ok "cloned $hash into $path" \
        || { bad "git clone failed"; finish 1; }
else
    info "$path exists, not re-cloned (delete it to clone again)"
fi
[ -d "$path/.git" ] && info "model commit $(git -C "$path" log -1 --format='%h %ad %s' --date=short)"

# images
step "docker images"
img=$(echo "$name" | tr 'A-Z ' 'a-z_')_image
base=$(sed -n 's/^ARG BASE=//p' "$path/Dockerfile" 2>/dev/null | head -1)
if [ -n "$base" ]; then
    if docker image inspect "$base" > /dev/null 2>&1; then
        ok "base image $base present ($(docker image inspect -f '{{.Created}}' "$base" | cut -c1-16))"
    elif [ -f "$path/build_base.sh" ]; then
        info "building base image $base (once per machine; log $out/base_build.log)"
        tb=$(date +%s)
        if sh "$path/build_base.sh" "$base" > "$out/base_build.log" 2>&1; then
            ok "base image $base built in $(mins $tb)"
            grep -E "^(INLA|inlabru|sp|sf|raster|rgeos|sn) [0-9]" "$out/base_build.log" | tr '\n' ' ' | sed 's/^/  .... /'; echo
        else
            bad "base image build failed after $(mins $tb); last lines:"
            grep -vE "^\s*$" "$out/base_build.log" | tail -25 | sed 's/^/       /'
            finish 1
        fi
    else
        bad "base image $base missing and no build_base.sh"; finish 1
    fi
    docker rmi "$img" > /dev/null 2>&1 && info "removed old $img (rebuilt in seconds from the base)"
fi

# smoke test
step "smoke test: $smoke_day, $nsims catalogs"
ts=$(date +%s)
mon=$out/docker_stats.txt; : > "$mon"
( while true; do docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' >> "$mon" 2>/dev/null; sleep 5; done ) &
mpid=$!
TESTS=tests_n.yml bash scripts/smoke_test.sh "$name" "$smoke_day" "$nsims" > "$out/smoke.log" 2>&1
rc=$?
grep -E "Successfully built|build error" "$out/smoke.log" | sed 's/^.* - /  .... /' | tail -2
grep -E "^(input catalog|PASS|FAIL|WARN|INFO|result)" "$out/smoke.log" | sed 's/^/  /'
if [ $rc -eq 0 ]; then
    ok "smoke test $smoke_day $nsims catalogs in $(mins $ts): $(grep -m1 '^INFO' "$out/smoke.log" | cut -d' ' -f3-)"
else
    bad "smoke test exit $rc after $(mins $ts); errors and container log:"
    grep -E "ERROR|Error|error:" "$out/smoke.log" | grep -v "^\s*File" | tail -8 | sed 's/^/       /'
    grep -A40 "Last logs" "$out/smoke.log" | grep -vE "^\s*$|masked|Attaching|^    " | tail -30 | sed 's/^/       /'
    kill $mpid 2>/dev/null; finish 1
fi

# sequential vs parallel
step "modes.py: $days windows from $start, $nsims catalogs, sequential (all cores) vs parallel (1 thread per container)"
tm=$(date +%s)
python scripts/modes.py "$name" --start "$start" --days "$days" --nsims "$nsims" --runs sequential:0 parallel:1 \
    > "$out/modes.log" 2>&1
rc=$?
kill $mpid 2>/dev/null
grep -vE "^\s*$" "$out/modes.log" | sed 's/^/  /'
for r in sequential:0 parallel:1; do
    l=$(grep "^== $r" "$out/modes.log")
    [ -n "$l" ] && summary+=("$( [ "$(grep -A$((days + 1)) "^== $r" "$out/modes.log" | grep -c FAIL)" -eq 0 ] && echo 'OK  ' || echo 'FAIL') ${l#== }")
done
same=$(grep -A1 "identical to the first run" "$out/modes.log" | tail -1 | sed 's/^ *//')
[[ "$same" == *"$days/$days"* ]] && ok "parallel forecasts identical to sequential ($same)" || bad "parallel vs sequential: $same"
[ $rc -eq 0 ] || bad "modes.py exit $rc"

# memory
peak=$(python - "$mon" <<'EOF'
import re, sys
u = {"KiB": 1 / 1024 ** 2, "MiB": 1 / 1024, "GiB": 1, "B": 1 / 1024 ** 3}
best, n = 0.0, 0
for line in open(sys.argv[1]):
    m = re.search(r"([\d.]+)(GiB|MiB|KiB|B) /", line)
    if m:
        best = max(best, float(m[1]) * u[m[2]]); n += 1
print(f"{best:.2f} GB peak per container ({n} samples)")
EOF
)
info "memory: $peak"; summary+=("INFO memory $peak")
finish 0
