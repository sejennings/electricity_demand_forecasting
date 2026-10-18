# Live inputs and the model container

These commands collect information available now, train the evaluated demand/calendar
model, and issue a future 24-hour forecast. They do not publish a container to ECR or
create an ECS task. The separate [scheduled forecast deployment](scheduled-forecasts.md)
publishes the image and runs the weather-aware model daily on Fargate.

## Source timing

Live imports query EIA through the last completed UTC hour, including today. The source
may publish later than that bound. A 31-day rolling demand window provides lag history;
missing and null observations are reported, not filled. Model inference still requires
all of its specific lag/rolling inputs and retains the evaluated 24-hour assumed delay.
The API request uses a bounded reverse scan and filters timestamps locally. If that
request fails, the importer reads the official EIA published-hourly workbook and supplements
it with the API's latest observed record. It selects the reported Demand column, never
the workbook's imputed/adjusted columns. Source choice and any unfilled gaps are recorded.
Large original export workbooks expire from S3 after 30 days; normalized demand, forecast
weather snapshots and their manifests remain archived.

Open-Meteo's current forecast endpoint supplies four days of GFS Seamless weather for
the Charlotte point. Raw responses, normalized CSVs, source/model identifiers and response
availability times are archived together. The provider model initialization time is not
returned by this endpoint, so it is left unknown. Retrieval time is not mislabeled as
provider issuance. See the [forecast API](https://open-meteo.com/en/docs).

Snapshots are immutable and stored under `data/operational/snapshots/<id>/`. The portable
`data/operational/latest.json` pointer is written only after both inputs have been collected
and validated. Failed attempts cannot replace it. Optional S3 archival uses execution-specific
paths under `raw/operational/`, `processed/operational/` and `reports/operational/`.
Archived EIA request metadata is removed to avoid persisting its echoed API key.

```powershell
python -m pip install -e ".[model,aws]"
python -m gridcast.jobs import-live --profile default --bucket gridcast-lake-456112636403-us-east-2
```

The command uses `EIA_API_KEY` from the environment if present, otherwise Secrets Manager
`gridcast/eia-api-key` in us-east-2. Do not put key values in arguments or files. AWS
credentials come from your browser-authenticated profile locally or a service role on AWS.

The existing daily workflow now has an Operational stage after historical curation. It
collects the latest available demand and current forecast weather. Valid actual demand
also updates the existing hourly-demand Parquet table. ERA5 weather and joined research
tables retain their seven-day lag. Forecast-weather snapshots remain separate from
historical reanalysis and are not silently mixed with it. Recent calendar dates can
therefore show demand hours before reanalysis weather becomes available.

## Train and forecast with Docker

The image pins its Python base by digest and numerical/runtime dependencies by version.
It runs as UID 10001, contains no datasets, model artifacts or credentials, and exposes
separate commands for training, inference and imports. The tested platform is Linux/amd64.

```powershell
docker build -t gridcast-model:local .
$dataDir = (Resolve-Path data).Path

docker run --rm --mount "type=bind,source=$dataDir,target=/app/data" gridcast-model:local train `
  --input data/processed/demand/DUK/2021-01-01_2025-12-31.csv `
  --cutoff 2026-01-01T00:00:00Z --output data/models/container/model.joblib

docker run --rm --network none --mount "type=bind,source=$dataDir,target=/app/data" gridcast-model:local forecast `
  --model data/models/container/model.joblib --snapshot data/operational/latest.json `
  --output data/forecasts
```

Training cutoff is exclusive. The training job constructs its lag and rolling inputs
only from demand before each training issue cutoff, skips missing target/input windows,
and saves input hashes, parameters, row count and model metadata next to the artifact.
Use multiple `--input` CSV paths to include additional compatible historical data.
Conflicting overlapping observations are rejected for review. No network or AWS access
is needed to train or forecast from mounted files. The Docker import command can instead
use an AWS service role at deployment; no credentials are baked into the image.

Inference creates 24 target hours starting at the next whole UTC hour. `issue_time_utc`
records actual generation time, while `forecast_origin_utc` names that first target hour.
`horizon_hours` is the ordinal target 1–24, not fractional elapsed time from issuance.
Artifacts and inputs newer than their allowed cutoffs are rejected. Output filenames
include a unique issuance identifier, and a JSON sidecar records the snapshot and model hash.
Only load trusted joblib artifacts.

## Weather and performance boundaries

Demand-only artifacts include weather as context with `weather_used_by_model=false`.
Optional weather-aware artifacts use archived GFS runs and emit
`weather_used_by_model=true`. See [weather-vintage training](weather-vintage-training.md)
for the feature contract, historical availability assumption and paired evaluation.

The existing multi-season accuracy applies to midnight UTC retrospective evaluation with
revised observations and an assumed delay. Current-hour origins, fresh model artifacts
have not been given a measured accuracy score. A separate 2026 weather comparison uses
daily midnight origins and extended official published demand; it does not synthesize gaps.

## Checks

```powershell
python -m unittest discover -s tests -v
```

Tests cover bounded demand requests, snapshot availability, training cutoff guards,
relative snapshot pointers, missing-history rejection, and immunity to unavailable demand.
Container training and inference are separately checked on the actual data.
