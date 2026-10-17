# GridCast: electricity demand forecasting

Local hourly demand and weather imports for an AWS forecasting platform.

## Setup (PowerShell)

Requires Python 3.11 or newer. From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:EIA_API_KEY = "your-eia-key"
gridcast-import --start 2025-01-01 --end 2025-01-07
```

Register for a [free EIA API key](https://www.eia.gov/opendata/register.php).
Keys are read from the environment; `.env` files are not loaded automatically.
Default scope is Duke Energy Carolinas (`DUK`) with Charlotte weather
(35.2271, -80.8431). This single point is a starting proxy, not a regional average.
Override using `--region`, `--latitude`, and `--longitude`.

```powershell
# Weather needs no key:
gridcast-import --source weather --start 2025-01-01 --end 2025-01-07
# Historical backfill:
gridcast-import --start 2021-01-01 --end 2025-12-31
# Refetch corrected or recently published source records:
gridcast-import --start 2025-01-01 --end 2025-01-07 --refresh
```

Dates are inclusive UTC dates. Monthly requests, EIA pagination, transient-error retries,
and cached successful pages support restartable backfills.

## Outputs

Outputs are ignored by Git; change the root with `--output`:

- `data/raw/eia/<region>/`: source responses, excluding credential-bearing request metadata.
- `data/raw/weather/<latitude>_<longitude>/`: source responses and units.
- `data/processed/demand/<region>/`: CSV with `timestamp_utc`, `region`, `demand_mw`.
- `data/processed/weather/<latitude>_<longitude>/`: CSV with UTC timestamps, coordinates,
  source, temperature (°C), humidity (%), precipitation (mm), and wind (m/s).
- `data/reports/`: requested scope, import time, row counts, missing hours, null counts.

CSV files use requested start/end dates in their names. The same request replaces its
processed file atomically; overlapping requests create separate files. Deduplicate keys
before concatenating overlapping ranges. Join demand and weather on `timestamp_utc`.
Missing hours/nulls are reported without filling. Duplicate/out-of-range timestamps and
unexpected units fail imports. Review reports and raw anomalies before training.
EIA energy in megawatthours over one-hour intervals is numerically equal to average MW.

## Data sources and limits

[EIA API v2](https://www.eia.gov/opendata/documentation.php) supplies actual demand (`D`).
[Open-Meteo historical weather](https://open-meteo.com/en/docs/historical-weather-api)
supplies ERA5 gridded reanalysis, explicitly selected for consistency.
Weather attribution: Open-Meteo / Copernicus ERA5. Consult provider documentation for
licensing, attribution, rate limits, and commercial-use terms.

Historical reanalysis is suitable for exploration, but is **not forecast-time weather**.
Do not use future reanalysis values as known inputs in realistic forecasting backtests.
Historical weather forecasts, NOAA station imports and multi-point weather aggregation
remain future steps. Parquet and the AWS data lake are implemented below.

## Tests

```powershell
python -m pip install -e ".[model,analytics]"
python -m unittest discover -s tests -v
```

Offline tests cover UTC alignment, date windows, duplicate rejection, missing-hour
reporting, credential-safe caching and pagination. Live demand imports require an EIA key.

## Baseline forecasting

Reinstall with `python -m pip install -e .` to register `gridcast-baseline`.
Four demand-only baselines produce hourly forecasts for the next 24 hours:
persistence, daily seasonal naive, weekly seasonal naive, and their daily/weekly mean.
No training dependencies or weather inputs are required.

```powershell
gridcast-baseline evaluate --start 2025-01-08T00:00:00Z --end 2025-01-31T00:00:00Z
gridcast-baseline forecast --issue 2025-02-01T00:00:00Z
# Sensitivity to delayed observations, with separate results:
gridcast-baseline evaluate --start 2025-01-09T00:00:00Z --end 2025-01-31T00:00:00Z --availability-delay-hours 24 --output data/models/baselines-delay24
```

Use `--input` for a demand CSV or directory, `--region` for the balancing authority,
and `--output` for results. Directory inputs combine CSVs, deduplicate identical records,
and reject conflicting overlaps. Defaults read `data/processed/demand/DUK`.

Evaluation issues forecasts at midnight UTC each day, with 24 targets beginning at
that midnight. Issue bounds are inclusive. Horizons 1–24 label the first through last
target hour. Observations must be strictly before issue time minus the configured
availability delay. Seasonal lags repeat backward until before that cutoff; missing
source hours are never replaced with future observations. Persistence uses the hour
immediately before the cutoff. These baselines use UTC seasons, not local-time seasons.

All four models are evaluated on identical complete daily windows. Incomplete days
are excluded and counted. `metrics.json` reports MAE, RMSE, WAPE, and MAE at each day's
actual peak hour. WAPE is null when total actual demand is zero. Per-hour issued forecasts
and actuals are saved in `backtest_predictions.csv`. Future forecasts use separate CSVs
named by region and issue time. Evaluation outputs overwrite prior results in the same
output directory; use separate directories for experiments.

The default zero-hour delay is an optimistic assumption. Historical EIA values can be
revised; this is a retrospective comparison, not a reconstruction of data publication.
Use delay sensitivity runs and verify actual source availability before scheduling forecasts.
At least seven days of prior history are needed, plus the evaluation interval (more with delay).

Initial DUK comparison: January 8–31, 2025, 576 hours across 24 complete days:

| Model | MAE (MW) | RMSE (MW) | WAPE |
| --- | ---: | ---: | ---: |
| Persistence | 1,476.82 | 1,849.44 | 9.71% |
| Daily naive | 1,306.77 | 1,704.88 | 8.59% |
| Weekly naive | 3,142.86 | 3,725.60 | 20.67% |
| Daily/weekly mean | 1,872.95 | 2,251.81 | 12.32% |

This single winter month verifies the workflow; it is not evidence of year-round performance.

## When to set up AWS

Continue locally until a multi-season backfill passes data-quality review and baseline
evaluation runs reproducibly. Then set up the AWS account/project environment and budget
alert before deploying the first storage and scheduled-ingestion milestone. Model evaluation
does not require AWS. Infrastructure provisioning, account configuration, and deployment
are not part of the baseline implementation.

## Historical backfill and gradient boosting

The five-year backfill and 2024–2025 evaluation are complete. See
[historical evaluation](reports/historical_evaluation.md) for coverage, seasonal results,
assumptions and limitations. With an assumed 24-hour reporting delay, the 2025 model
achieved 8.28% WAPE versus 10.03% for the strongest baseline.

```powershell
python -m pip install -e ".[model]"
# Optional: reproduce the experiment's exact dependency versions (Python 3.12):
python -m pip install -r requirements-model-lock.txt
# Official EIA bulk demand plus monthly historical weather (no API key needed):
python -m gridcast.backfill
# Monthly expanding refits, shared baseline comparison, seasonal metrics:
python -m gridcast.research
# Demonstrate future inference from the final trained artifact:
python -m gridcast.forecast_model --issue 2026-01-01T00:00:00Z
```

The EIA bulk download is approximately 697 MB, cached under `data/raw/eia/`.
Only the requested DUK series is extracted; reruns reuse its cached JSON. To obtain a
fresh snapshot, archive the cached series and ZIP elsewhere before rerunning.
Backfill uses fixed DUK/Charlotte geography and 2021–2025 dates. The model experiment
uses 2021–2023 initial history, 2024 validation and 2025 chronological evaluation;
model parameters are fixed. Historical data may be revised after the initial download.

`data/models/research/` contains per-hour evaluation predictions, metrics, the final
`model.joblib`, and issued forecasts. Only load trusted model artifacts. The final model
is separately refit after evaluation using labels before 2025-12-31 UTC. It cannot be
used for earlier issue dates; the forecast command checks the training cutoff. The sample
January 2026 forecast is a workflow demonstration, not a forecast for today's date.
For current forecasts, extend demand ingestion through the required availability cutoff.

Compact results are tracked in `reports/`; raw data, CSV predictions and model binaries
remain ignored. The backfill found one missing demand hour; affected evaluation days
are excluded, never interpolated. Forecast-time weather is still a separate future task.

AWS storage, scheduled ingestion and the analytics layer are now deployed. Model
training can continue locally until the container deployment milestone.

## AWS data lake

The first AWS milestone is deployed with Terraform infrastructure and Lambda ingestion code.
See the [deployment status](reports/aws_deployment.md) for verified checks.
See [infrastructure instructions](infrastructure/README.md) for deployment, secure EIA
key setup, cloud smoke tests, scheduling, alerts and cost controls. Infrastructure targets
`us-east-2` with the `default` profile. The schedule defaults to disabled until a successful
manual run verifies both sources; the deployed schedule is now enabled.

## Parquet, Glue and Athena

The `gridcast` Glue database contains three hourly Parquet tables and region/calendar
dimensions. The `gridcast-analytics` Athena workgroup has five reporting views and saved
queries for daily peaks, seasonality, weather relationships and completeness.

The 2021–2025 history contains 43,823 demand/joined hours and 43,824 weather hours.
The known missing demand hour remains visible in the completeness report. Seven days
of cloud-imported October 2026 data are also queryable. The daily pipeline updates monthly
Parquet partitions without discarding prior hours. Live Athena queries and a seven-day
workflow run verified row counts, uniqueness, null checks and incremental preservation.

See [SQL analytics instructions](sql/README.md) and
[analytics validation](reports/analytics_deployment.md) for schemas, commands and evidence.
