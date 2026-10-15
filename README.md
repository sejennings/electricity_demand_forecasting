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
Historical weather forecasts, NOAA station imports, multi-point aggregation, Parquet,
and AWS deployment are future steps.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Offline tests cover UTC alignment, date windows, duplicate rejection, missing-hour
reporting, credential-safe caching and pagination. Live demand imports require an EIA key.
