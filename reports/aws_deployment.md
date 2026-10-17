# GridCast AWS data lake deployment

Deployed October 17, 2026 in us-east-2 using the default AWS CLI profile.

## Provisioned

- Private, encrypted, versioned S3 lake: `gridcast-lake-456112636403-us-east-2`.
- Lambda: `gridcast-ingestion`, with scoped S3/Secrets Manager/log permissions.
- Step Functions Standard: `gridcast-ingestion`, parallel source tasks followed by curation.
- EventBridge Scheduler: `gridcast/daily-ingestion`, 14:00 UTC daily, **enabled** after successful manual validation.
- Encrypted Scheduler delivery DLQ, workflow failure/timeout and DLQ-depth alarms.
- Fourteen-day Lambda/workflow log retention and 30-day noncurrent object-version retention.
- Confirmed email subscription to `gridcast-alerts`.
- $5 monthly AWS project budget, with actual and forecast alerts; credits excluded.
- Secrets Manager: `gridcast/eia-api-key`, populated and verified by live demand ingestion.

## Verified

- All 15 Python tests pass, including incomplete-data rejection and cloud curation.
- Terraform configuration validation passes.
- 65 local historical source/data/report objects uploaded to the lake.
- Live Lambda weather import: 24 expected/actual hours, no gaps or nulls, January 2, 2025.
- Live Lambda curation: 24 joined rows written to
  `curated/hourly/region=DUK/year=2025/month=01/day=02/data.csv`.
- Initial curation testing used the local historical demand snapshot.
- Full workflow with fresh EIA and weather API requests: January 2, 2025, **SUCCEEDED**,
  24 validated and joined hourly records. Execution: `manual-96a1f334de25451f9af9ada48c280918`.
- Full seven-day workflow: October 4–10, 2026, **SUCCEEDED**, 168 validated and joined
  hourly records. Execution: `manual-7b829ada9534472a82eab389405e738f`.

## Activation

The key and email subscription are configured. Both manual smoke tests have passed.
Schedule enablement was applied through the ignored Terraform variables file using
`schedule_enabled = true`.
The first automatic daily invocation will still need to be checked after its scheduled time.

No EIA key is in Terraform variables or source control. Regional services remain in
us-east-2. The budget uses the global billing endpoint only. The original project’s next
analytics milestone (Parquet, Glue Data Catalog and Athena) is now also complete; see
[analytics deployment](analytics_deployment.md).

See [deployment runbook](../infrastructure/README.md) for commands, architecture,
cost implications and lifecycle controls. Preserve the local Terraform state securely.
