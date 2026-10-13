#!/usr/bin/env bash
# Daily log-scores (scripts/scores_td.py) of several runs one after the other, W workers each.
# usage: scripts/run_scores.sh W RUN [RUN ...]       ENV=name conda env (default testing_italy_td), ENV= current env
cd "$(dirname "$0")/.."
ENV=${ENV-testing_italy_td}
if [ -n "$ENV" ] && [ "$CONDA_DEFAULT_ENV" != "$ENV" ]; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$ENV" || exit 1
fi
export TZ=UTC PYTHONUNBUFFERED=1
w=$1; shift
for run in "$@"; do
    python scripts/scores_td.py "$run" --workers "$w" 2>&1 | tee -a runs/SCORES.log
done
msg="italy_td scores on $(hostname) finished $(date -u +%FT%TZ): $*"
echo "$msg" | tee -a runs/SCORES.log; wall "$msg" 2>/dev/null || true
