# Forecast runs: batch 1 (vetas, fletas, petai, inlabru_td), 100k catalogs

| machine | screen | runs | forecasts in |
|---|---|---|---|
| rs1 (128 cores, 1 TB) | amatrice (done) | amatrice 2016-08-01..2017-02-01 | models/ |
| rs37 (24 cores, 125 GB) | aquila (done), emilia | aquila 2009-03-01..2009-06-09, emilia 2012-05-01..2012-08-09 | models/ |
| rs1 | full | full_2014 .. full_2021 (heaviest years first) | models_full/ |
| rs28 | full | full_2010 .. full_2013 | models_full/ |

Full run = 2010-01-01 to 2021-06-29, one run per year (`full_YYYY`), data/iside_ml.csv as is (ends
2021-06-28). It is a separate experiment: its forecasts go to models_full/<name> (own clone, same
<name>_image), never to models/<name>. Same model code and the same fit rule as the sequences: the
ETAS models fit from run start - 4 years (auxiliary 2 years earlier, clipped at 2005-04-16), so each
year has its own fit start; inlabru fits the year before each day.

Rules
- Never `rm -rf models/<name>` or `models_full/<name>`: the forecasts live inside.
- Do not update italy_td (tar, git pull) while a run is going: run_forecasts.sh is read while it runs.
- Workers: min(cores, RAM_GB / 6) (inlabru needs up to ~6 GB on busy days).

## Setup of a new machine (once)
```bash
cd ~ && git clone -b main https://github.com/pabloitu/italy_td.git italy_td && cd ~/italy_td
conda env create -f environment.yml && conda activate testing_italy_td
docker run --rm hello-world                     # docker without sudo
ssh -T git@git.gfz-potsdam.de                   # "Welcome to GitLab"
md5sum data/iside_ml.csv                        # 8fb1e218b038b96da4eb8fa2ce738700 on every machine
nproc; free -g; df -h ~
```

## Start
```bash
cd ~/italy_td && conda activate testing_italy_td
python scripts/prepare_runs.py full_2016 full_2017 full_2014 full_2015 full_2018 full_2019 full_2020 full_2021 --workers 96
screen -dmS full -L -Logfile ~/italy_td/screen_full.log scripts/run_forecasts.sh full_2016 full_2017 full_2014 full_2015 full_2018 full_2019 full_2020 full_2021
```
The first run clones the four models into models_full/ and builds the images that are missing
(rs28: all four, inlabru ~5 min; rs1: none). Then the years run one after the other.

## Watch
```bash
scripts/status.sh            # everything on this machine, read-only; paste this when asking
screen -r full               # Ctrl-A D detaches
```
At the end of each run a line is printed on your open terminals and added to runs/DONE.log.

## Stop, restart
```bash
screen -S full -X quit; docker ps -q | xargs -r docker kill
screen -dmS full -L -Logfile ~/italy_td/screen_full.log scripts/run_forecasts.sh <same runs>
```
A restart redoes only missing windows (the check of existing files at the start takes minutes).

## When a run is complete
```bash
python scripts/archive_run.py full_2016        # ~/italy_archive/full_2016/, read-only, manifest.csv
```
Tests (N, S, M, L) come later, on the archived forecasts.
