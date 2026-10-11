#!/usr/bin/env bash
# Status of the forecast runs on this machine (read-only). See scripts/status.py.
# usage: scripts/status.sh [RUN ...]       ENV=name conda env (default testing_italy_td), ENV= current env
cd "$(dirname "$0")/.."
ENV=${ENV-testing_italy_td}
if [ -n "$ENV" ] && [ "$CONDA_DEFAULT_ENV" != "$ENV" ]; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$ENV" || exit 1
fi
python scripts/status.py "$@"
