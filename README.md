# Bristow-Hall Occupation Monitor

Monthly U.S. jobs by occupation and by state, built from the Current Population Survey public-use files.

Anthony Hall and Duke Bristow, USC Marshall School of Business.

## How it updates

A GitHub Actions job (`.github/workflows/update.yml`) runs once a day. It checks the Census Bureau's survey folder for a
monthly file it has not processed. When one appears it downloads the file, adds that month to `data/`, rebuilds the
files in `docs/`, and commits. GitHub Pages serves `docs/`. No other computer is involved.

The job can also be started by hand from the Actions tab ("Run workflow").

## Layout

| path | holds |
|---|---|
| `update.py` | National, state and occupation updater. Python standard library only. |
| `counties.py` | County updater: jobs, employers and pay (BLS QCEW, quarterly), population (Census estimates), labor force, income, occupations and commuting (Census ACS 5-year). |
| `data/county/` | Compact county source tables. |
| `data/monthly/` | Jobs by month, occupation code and age group. |
| `data/monthly_state/` | Jobs by month, state and occupation group. |
| `data/code_to_occupation.csv` | Census occupation code to tracked occupation. |
| `data/occupations.csv` | The occupations shown, with their AI exposure scores. |
| `docs/` | The site and its data files. `docs/counties/` holds one file per state. |

## Method

All figures are 12-month averages of the survey's weighted counts. Monthly totals match the published
not-seasonally-adjusted employment level. Occupations with fewer than 100 survey respondents a month are pooled into
one "Other" row per occupation group, so the rows add up to all U.S. employment. State cells with fewer than 30
respondents a month are left blank. County jobs are four-quarter averages of the QCEW count of jobs covered by unemployment insurance, so they are a count of jobs by place of work and do not add up to the survey totals. Connecticut is reported by planning region since 2024 and its counties show no data. AI exposure is the Eloundou et al. (2023) score, split into fifths of 2022 employment.
