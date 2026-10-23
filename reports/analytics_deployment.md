# Parquet, Glue and Athena deployment

Verified October 17, 2026 in us-east-2, AWS CLI profile `default`.

## Deployed

- 185 Snappy Parquet objects: monthly demand, weather, joined facts and calendar/region dimensions.
- Glue database `gridcast` with five external physical tables, plus five Athena reporting views.
- Athena workgroup `gridcast-analytics`: engine v3, encrypted results in the existing lake,
  expected-owner enforcement, 100 MiB per-query scan ceiling and CloudWatch metrics.
- Five named queries, with their versioned SQL under `sql/reports/`.
- Daily Lambda curation now publishes Parquet as well as its existing CSV output.
- Pinned Python 3.12 / Linux ARM64 PyArrow 26.0.0 layer and scoped S3 listing permission.
- Query result current objects expire after seven days; prior versions retain the lake policy.

## Validation evidence

| Check | Result |
| --- | --- |
| 2021–2025 demand table | 43,823 hours |
| 2021–2025 weather table | 43,824 hours |
| 2021–2025 joined table | 43,823 rows, 43,823 distinct timestamps |
| Critical joined nulls | 0 |
| Completeness exception | November 3, 2025: one missing demand hour; weather complete |
| Historical month after updating one day | January 2025 retained all 744 hours |
| Repeated current-window publishing | October 2026 retained 168 unique hours |
| Native Lambda Parquet integration | Seven-day workflow SUCCEEDED, 168 rows, five Parquet object updates |
| Python tests | 18 passed |
| Terraform | Validated and applied without deleting resources |

The full post-upgrade cloud workflow execution was
`manual-bbb66036ec414378a50f04e3c682e692`, covering October 4–10, 2026.
Historical sources and the current seven-day sample together contain 43,991 demand/joined
hours and 43,992 weather hours. This does not constitute a complete 2026 backfill.

Query IDs, sample rows, report results, runtime and scan bytes are in
`athena_validation.json`. The captured validation/report SELECT queries, including the
incremental preservation check, scanned 1,667,583 bytes in total. Scanned bytes are not a
bill estimate: Athena's minimum billing units and S3/catalog requests still apply.
See [Athena pricing](https://aws.amazon.com/athena/pricing/).

No missing hour was fabricated or filled. Calendar and expected-hour calculations use UTC.
Weather is historical reanalysis; the analytical feature view is not automatically safe as
future-weather input for forecasting. Plain Parquet object updates are individually atomic,
not a transaction across all tables; run reporting extracts after pipeline success.

The daily schedule remains enabled
`../sql/README.md`. Preserve the ignored Terraform state securely.
