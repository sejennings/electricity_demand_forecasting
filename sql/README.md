# GridCast Athena analytics

Selected Region: us-east-2. Catalog: AwsDataCatalog. Database: `gridcast`.
Workgroup: `gridcast-analytics`. Encrypted query output:
`s3://gridcast-lake-456112636403-us-east-2/athena-results/`.

## Tables

| Table | Grain | Purpose |
| --- | --- | --- |
| hourly_demand | One UTC hour / region | Measured demand in average MW |
| hourly_weather | One UTC hour / weather point | ERA5 temperature, humidity, precipitation, wind |
| hourly_demand_weather | One matched UTC hour / region | Demand plus historical reanalysis |
| dim_calendar | One UTC calendar date | ISO weekday (Monday=1), weekend, month, year |
| dim_region | One balancing authority | Region name, local timezone, representative weather point |

Hourly tables have string partition columns `region`, `year`, `month` and monthly Snappy
Parquet files. Payload column schemas are explicit; timestamps are microsecond UTC
instants stored as timestamp values without a timezone annotation. Latitude/longitude
identify the requested Charlotte point. Calendar attributes refer to UTC; local timezone
is metadata and does not change the 24-hour expected count during DST transitions.

Glue tables are defined by Terraform. Athena partition projection discovers monthly
paths for DUK, years 2021–2030 and months 01–12; no crawler or `MSCK REPAIR` is needed.
Extend the projection range before adding years outside it. Projection is Athena-specific:
other engines may need their own partition discovery. No Glue Spark job runs here.

The five views in `views/` provide daily load/energy/peak times, hourly/weekday seasonality,
weather relationships, completeness, and calendar-enriched hourly records. Daily energy
is the sum of observed one-hour demand intervals, not an imputed full-day total. Peak
ties choose the earliest UTC hour. Winter means January, February and December in the
same calendar year. Pearson correlation is descriptive, not causal. Heating/cooling
degrees use an 18°C reference, not a calibrated demand threshold.

Completeness uses calendar dates observed in either source. It detects absent demand
hours/days within that coverage, but cannot claim coverage for dates absent from both
source snapshots. The historical period is 2021–2025; current 2026 records are a rolling
sample, not a full-year backfill.

## Run

From the repository root, after AWS login:

```powershell
python -m pip install -e ".[aws,model,analytics]"
python scripts/build_arrow_layer.py
terraform -chdir=infrastructure/terraform plan -out=analytics.tfplan
terraform -chdir=infrastructure/terraform apply analytics.tfplan
python scripts/build_analytics.py
python scripts/athena_analytics.py
```

The final command creates/replaces the project-owned views, profiles five sample rows,
runs the saved report SQL through the Athena CLI, and checks historical row counts,
critical nulls, uniqueness and the known missing hour. Query IDs, runtime, bytes scanned
and returned rows are saved in `reports/athena_validation.json`.

Report SQL in `reports/` is also saved as named queries in the workgroup. For example:

```sql
SELECT * FROM gridcast.v_daily_load
WHERE region='DUK' AND year='2025' AND month='07'
ORDER BY peak_demand_mw DESC LIMIT 10;
```

Filter partition columns to reduce scans. Query results use enforced SSE-S3 and expected
bucket ownership, and query scanning is limited to 100 MiB per query. The limit is not
a total spending cap. Athena scan billing, S3 requests/storage and Glue catalog usage
can consume credits. See [Athena pricing](https://aws.amazon.com/athena/pricing/) and
[Glue pricing](https://aws.amazon.com/glue/pricing/). Current query result objects expire
after seven days; noncurrent versions retain the lake's 30-day policy.

## Incremental publishing

The daily cloud curation step continues writing its CSV and now upserts monthly Parquet
and dimension files too. Repeated hours replace their prior values; earlier hours in the
month are retained. Conditional S3 writes retry after concurrent-update conflicts so
two writers do not silently overwrite each other's additions. Schemas live in
`gridcast.analytics` and the corresponding Terraform Glue definitions.

S3 object updates are atomic individually, not across every dataset or month. Athena
queries during a pipeline run may see a mix of old/new partitions. Require successful
pipeline completion before taking a consistent reporting extract. Historical sources
can be revised, so reports are retrospective. Reanalysis weather remains unsuitable as
known future weather in forecasting backtests.
