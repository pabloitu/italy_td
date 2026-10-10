#!/usr/bin/env bash
# Copy forecast files from a server (or another checkout) into this repo's models/<name>/forecasts/.
# Only *.csv under forecasts/ are copied; existing local files are never overwritten.
#
# usage: scripts/collect_forecasts.sh USER@HOST:/path/to/italy_td [MODEL ...]
#        scripts/collect_forecasts.sh /other/local/italy_td vetas
set -euo pipefail
cd "$(dirname "$0")/.."
src=${1%/}; shift
models=${*:-$(python -c "import yaml;print(' '.join(next(iter(m)) for m in yaml.safe_load(open('models.yml'))))")}
for m in $models; do
    mkdir -p "models/$m/forecasts"
    echo "== $m"
    rsync -av --ignore-existing --include='*.csv' --exclude='*' "$src/models/$m/forecasts/" "models/$m/forecasts/"
done
