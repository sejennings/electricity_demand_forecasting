# GridCast AWS data lake deployment

Deployed October 17, 2026 in us-east-2 using the default AWS CLI profile.

## Provisioned

- Private, encrypted, versioned S3 lake: `gridcast-lake-456112636403-us-east-2`.
- Lambda: `gridcast-ingestion`, with scoped S3/Secrets Manager/log permissions.
- Step Functions Standard: `gridcast-ingestion`, parallel source tasks followed by curation.
- EventBridge Scheduler: `gridcast/daily-ingestion`, 14:00 UTC, currently **disabled**.
- Encrypted Scheduler delivery DLQ, workflow failure/timeout and DLQ-depth alarms.
- Fourteen-day Lambda/workflow log retention and 30-day noncurrent object-version retention.
- Confirmed email subscription to `gridcast-alerts`.
- $5 monthly AWS project budget, with actual and forecast alerts; credits excluded.
- Secrets Manager container: `gridcast/eia-api-key`, **awaiting a key value**.

## Verified

- All 15 Python tests pass, including incomplete-data rejection and cloud curation.
- Terraform configuration validation passes.
- 65 local historical source/data/report objects uploaded to the lake.
- Live Lambda weather import: 24 expected/actual hours, no gaps or nulls, January 2, 2025.
- Live Lambda curation: 24 joined rows written to
  `curated/hourly/region=DUK/year=2025/month=01/day=02/data.csv`.
- The curation test used the actual local historical demand snapshot, not a fresh EIA API
  request. Full workflow execution and scheduled ingestion have **not** been verified yet.

## Remaining activation

1. Enter a replacement EIA key in the local hidden-input prompt or run
   `.venv/Scripts/python.exe scripts/set_eia_secret.py` from the project folder.
2. Run `python scripts/run_cloud.py --end-date 2025-01-02 --days 1`, then a seven-day
   recent historical run using `--days 7` (default end date is seven days ago).
3. After successful source ingestion and curation, set `schedule_enabled = true` in the
   ignored Terraform variables file and review/apply the resulting plan.

No EIA key is in Terraform variables or source control. Regional services remain in
us-east-2. The budget uses the global billing endpoint only. The original project’s next
analytics milestone remains Parquet, Glue Data Catalog and Athena.

See [deployment runbook](../infrastructure/README.md) for commands, architecture,
cost implications and lifecycle controls. Preserve the local Terraform state securely.
