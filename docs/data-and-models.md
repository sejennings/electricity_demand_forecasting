# Data and model experiments

The default region is Duke Energy Carolinas (`DUK`). Charlotte weather is a
single-point proxy for the region, not a regional average.

## Import a date range

Register for a [free EIA key](https://www.eia.gov/opendata/register.php) and set it
locally as `EIA_API_KEY`. Do not put it in Git or chat. `.env` files are not loaded
automatically.

```powershell
.venv/Scripts/python.exe -m gridcast.ingestion --start 2025-01-01 --end 2025-01-31
# Historical weather alone needs no EIA key:
.venv/Scripts/python.exe -m gridcast.ingestion --source weather --start 2025-01-01 --end 2025-01-31
```

Dates are inclusive and timestamps use UTC. Add `--refresh` to fetch corrected
records. Imports cache successful pages and report missing hours and null values.
They do not fill gaps. CSVs go to `data/processed/`; raw responses and reports stay
under `data/`. Review quality reports before training.

Sources: [EIA](https://www.eia.gov/opendata/documentation.php) and
[Open-Meteo / Copernicus ERA5](https://open-meteo.com/en/docs/historical-weather-api).
Historical reanalysis is useful for research; future reanalysis values must not
be treated as information available when a forecast was issued.

## Compare baselines

```powershell
.venv/Scripts/python.exe -m gridcast.baselines evaluate --start 2025-01-08T00:00:00Z --end 2025-01-31T00:00:00Z
.venv/Scripts/python.exe -m gridcast.baselines forecast --issue 2025-02-01T00:00:00Z
```

The baselines are persistence, daily naive, weekly naive and a daily/weekly mean.
Use `--availability-delay-hours 24` to test delayed demand reporting. All models
use the same complete daily windows. Keep experiment outputs in separate folders
with `--output` to avoid overwriting results.

## Reproduce the historical model

```powershell
.venv/Scripts/python.exe -m gridcast.backfill
.venv/Scripts/python.exe -m gridcast.research
.venv/Scripts/python.exe -m gridcast.forecast_model --issue 2026-01-01T00:00:00Z
```

The backfill covers 2021–2025. Its EIA bulk download is about 697 MB; weather is
cached month by month. The experiment uses 2021–2023 history, 2024 validation and
2025 evaluation. The January 2026 example is a historical demonstration, not a
forecast for today.

See [historical results](../reports/historical_evaluation.md) for seasonal metrics
and exclusions. The known missing hour remains a gap. Source data can be revised,
so this is a retrospective evaluation, not a replay of publication history.

For current inference and weather-vintage experiments, use the
[operational model guide](operational-model.md) and
[weather-vintage guide](weather-vintage-training.md). Only load trusted model files.
