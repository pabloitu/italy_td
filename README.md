# testing_italy_td

Italy time-dependent forecasting experiment (daily horizon, catalog-based forecasts) run with
floatCSEP. The floatCSEP code comes from the `italy_td` branch; each model is cloned from its own
repository through `giturl` + `repo_hash` in `models.yml`.

Rules for every model: `claude/italy_experiment_spec.md` in the floatcsep Project.
Per-model status: `claude/italy_models_status.md`.

## Layout

```
config.yml            experiment: Italy region, mag_min 4.0, depth 0-30, 1 day horizon, window from 2016-08-24
models.yml            one entry per model (TODO fields are filled after each model check)
tests.yml             catalog N, S, M, L tests
environment.yml       conda env with floatcsep@italy_td and pycsep 0.8.0
data/                 ISIDe catalog (data/iside_ml.csv, CSEP ascii format)
scripts/              check_forecast.py, make_config.py, smoke_test.sh
models/               cloned/built models (ignored by git)
results/              floatcsep output (ignored by git)
```

## Install

```bash
conda env create -f environment.yml
conda activate testing_italy_td
floatcsep --help
```

Pin floatcsep to a commit once `italy_td` is frozen: replace `@italy_td` in `environment.yml`.

## Catalog

`data/iside_ml.csv` must be in CSEP ascii format, header included, ML magnitudes:

```
lon,lat,mag,time_string,depth,catalog_id,event_id
```

## Run

```bash
floatcsep stage config.yml     # clone and build models, prepare catalogs
floatcsep run config.yml       # forecasts, tests, plots for the whole window
floatcsep plot config.yml
```

Window length: edit `end_date` in `config.yml`, or derive a config:

```bash
python scripts/make_config.py --start 2016-08-24 --days 30 --out .win30   # writes .win30_config.yml
floatcsep run .win30_config.yml
```

## Smoke test (one model, one window)

```bash
scripts/smoke_test.sh etas                    # start 2016-08-24, n_sims 100
scripts/smoke_test.sh etas 2016-08-24 1000
```

It writes a one-model config, builds the model (`floatcsep stage`), runs one window into
`results/smoke_<model>/`, then validates the forecast. Logs: `results/smoke_<model>.{stage,run}.log`.

## Validate a forecast

```bash
python scripts/check_forecast.py models/etas/forecasts/etas_2016-08-24_2016-08-25.csv --n-sims 1000 --prefix etas
```

Checks: file name, 7 columns, no NaN, time format, window, catalog_id integer in 0..n_sims-1,
mag >= mag_min, depth < 30, inside `italy_csep_region`. Exit code 1 on any FAIL.

## First check: mock model, one day

```bash
curl -L https://raw.githubusercontent.com/cseptesting/floatcsep/main/tutorials/case_h/catalog.csv -o data/tutorial_h.csv
python scripts/prep_catalog.py data/tutorial_h.csv data/iside_ml.csv --mag-min 2.5
TESTS=tests_n.yml scripts/smoke_test.sh mock 2016-08-24 100
```

`data/tutorial_h.csv` is the Italy ISIDe catalog of floatCSEP tutorial H (2005-2021), only for this check.
`prep_catalog.py` keeps the events inside `italy_csep_region` with depth < 30 km and M >= 2.5.
floatcsep then writes each model's input from `input_config.catalog` (M >= 2.5) and tests against
`region_config` (M >= 4.0). `TESTS=tests_n.yml` runs the N-test only; leave it out for N, S, M, L.

## Scenario tests (pymock)

```bash
python scripts/scenarios.py                 # all scenarios, n_sims 100, build docker
python scripts/scenarios.py multi parallel  # a subset
python scripts/scenarios.py --nsims 1000
```

Runs mock and mock_nb (pymock, negative binomial counts) through: 5 consecutive windows, a rerun
that must recompute nothing, `floatcsep reproduce`, a run killed after 2 forecasts and restarted,
the busiest day (2016-10-30), a day with no M >= 4 events, two models in one config,
`run_mode: parallel`, and the same window twice to check the seed. Each forecast goes through
`check_forecast.py`, each N-test result must use n_sims catalogs, and the parallel run must give
the same mock forecasts as the sequential one. Logs are in `results/scenarios/`, outputs in
`results/scen_<name>/`. Takes a few minutes at n_sims 100.

Requirements: floatcsep with the n_sims and task-order fixes, Docker usable by your user
(`docker run hello-world` without sudo), and the pymock branch with the Dockerfile as
`repo_hash` of mock and mock_nb in models.yml.

## Docker models

All models run with `build: docker`. floatCSEP builds the image from the model folder
(`<name>_image`), then for each window runs the image CMD (not `func`, which must still be set)
as your user, with the window input folder mounted at `/app/input` (args.txt, catalog.csv and
any other files from the model's input/) and the forecasts folder at `/app/forecasts`. The
image must read `/app/input/args.txt` and write `/app/forecasts/{prefix}_{start}_{end}.csv`.
After changing a Dockerfile, remove the image (`docker rmi <name>_image`) so it is rebuilt.

## Forecast runs (sequences and full 2010-2021)

See `runs/README.md`. `scripts/prepare_runs.py` writes forecast-only runs from the root config and
models (presets amatrice, aquila, emilia, pilot, full_2010 .. full_2021), `scripts/run_forecasts.sh` runs them
in a `screen`, `scripts/check_run.py` verifies or quarantines, `scripts/collect_forecasts.sh` pulls
forecasts from another machine, `scripts/estimate.py` turns pilot timings into days per run.
Models not integrated yet are in `models_todo.yml`.
