# Weather-vintage training

Weather-aware models append temperature (°C), relative humidity (%), precipitation
(mm), wind speed (m/s), and heating/cooling degrees relative to 18°C to the existing
13 demand/calendar features. Both training and inference share this feature function.
Demand-only artifacts remain usable. Weather artifacts record a versioned feature
schema, model identity, availability policy, input hashes and training cutoff.

## Timing and source

Use the [Open-Meteo Single Runs API](https://open-meteo.com/en/docs/single-runs-api),
explicitly requesting GFS Seamless to match live collection. Its GFS run archive starts
April 2, 2026. Earlier ERA5 data cannot be substituted for forecast vintages.
The backfill requests the preceding day's 12 UTC run for each daily 00 UTC origin
and retains the next 24 target hours. It caches complete raw responses for resumption.

Initialization is not publication time. Historical availability is **assumed** to be
initialization plus 12 hours, a conservative delay; it is not a measured release time.
Selection takes the latest eligible run for a target, excluding later runs even if they
were downloaded together. The manifest distinguishes current retrieval time from the
assumed historical availability. These results are a retrospective simulation with an
availability assumption, not a fully observed point-in-time trading backtest.
Historical demand also remains revised observations with an assumed 24-hour delay.

## Backfill, compare and train

The commands below use the extended official EIA published-demand CSV already downloaded
locally. Datasets, raw responses and trained artifacts stay under ignored `data/`.

```powershell
python -m gridcast.vintages --start 2026-04-03T00:00:00Z --end 2026-10-17T00:00:00Z

python -m gridcast.weather_evaluation `
  --input data/processed/demand/DUK/2026-01-01_2026-10-16.csv `
  --weather-vintages data/weather-vintages/weather_vintages.csv `
  --start 2026-07-01T00:00:00Z --end 2026-10-17T00:00:00Z

docker build -t gridcast-model:local .
$dataDir = (Resolve-Path data).Path
docker run --rm --network none --mount "type=bind,source=$dataDir,target=/app/data" gridcast-model:local train `
  --input data/processed/demand/DUK/2026-01-01_2026-10-16.csv `
  --weather-vintages data/weather-vintages/weather_vintages.csv `
  --cutoff 2026-10-16T00:00:00Z --output data/models/weather/model.joblib

docker run --rm --network none --mount "type=bind,source=$dataDir,target=/app/data" gridcast-model:local forecast `
  --model data/models/weather/model.joblib --snapshot data/operational/latest.json `
  --output data/forecasts/weather
```

Evaluation holds parameters fixed and refits monthly using only targets strictly before
the month minus 24 hours. Both estimators use identical training and evaluation samples;
only weather features differ. Reports include monthly errors and skipped complete days.
April–June supply initial training; July–October 16 supply the expanding evaluation.
No winter performance is established. One Charlotte point represents the DUK footprint.
This paired comparison is separate from the earlier 2025 demand-only evaluation.

Live forecasts verify snapshot and weather retrieval precede issuance, match the model
source/schema and mark `weather_used_by_model=true`. Current live origins can occur at
any hour; the measured backtest uses daily midnight origins and older fixed-run weather.
Its accuracy does not establish hourly live-origin performance. Missing weather fails
inference or excludes training/evaluation samples; no future weather or reanalysis fills
those gaps. No AWS resources are required for this training step.
