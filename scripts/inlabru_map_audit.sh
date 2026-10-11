#!/bin/bash
# Which days of a run had a broken inlabru_td MAP (see inlabru_map_audit.R). Runs in the inlabru_td image.
# usage: bash scripts/inlabru_map_audit.sh START NDAYS [CORES]     e.g. amatrice: 2016-08-01 184 64
cd "$(dirname "$0")/.."
out=results/inlabru_map_audit_$1.txt; mkdir -p results
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/data:/chk_data:ro" -v "$PWD/scripts:/chk:ro" inlabru_td_image \
    Rscript /chk/inlabru_map_audit.R /chk_data/iside_ml.csv "$1" "$2" "${3:-32}" 2>/dev/null | tee "$out"
echo "saved $out"
