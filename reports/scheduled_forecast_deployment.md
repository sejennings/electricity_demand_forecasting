# Daily Fargate forecasting and issue-based scoring

Deployed in **us-east-2**, October 18, 2026. ECR stores the forecast image;
Scheduler `gridcast/daily-forecast` is **enabled at 14:30 UTC daily**. Step Functions
launches a short-lived Fargate task and monitors completion. Existing SNS failure
alerts and the Scheduler DLQ cover the new workflow.

The first real cloud run succeeded and produced 24 prospective weather-aware
predictions, issued **2026-10-18 22:41:34 UTC**, with a 23:00 UTC origin.
Its immutable S3 record contains the predictions, original issue time, model/image
hashes and source snapshot. This issue remains pending until actuals arrive.

The final release, including the EIA fallback fix, also passed a real Fargate run:
task definition revision 3, exit code 0, 24 predictions issued at **23:05:37 UTC**.
ECR pins image digest `sha256:d58149e8e8a6b831ee20233d13710413963c211d3572e6429d2a302a47f23876`.
Terraform's final plan reported no changes.

Yesterday's genuine local weather forecast was registered separately, preserving
its **2026-10-17 21:27:14 UTC** issue time and original predictions. Published
actuals through October 18 at 13:00 UTC scored **16 of its 24 hours**. The remaining
8 hours remain pending. Partial WAPE was 7.3966%; this is a small partial live
sample and does not establish the model's expected accuracy.

The deployed demand importer was invoked again and successfully triggered scoring.
The saved forecast bytes were unchanged, and identical actuals reused score revisions.
If EIA APIs time out, the official published-demand workbook can now be used alone,
with the source limitation and missing hours explicitly reported. No data is imputed.

Validation: **34 tests passed**, Terraform validation/format checks passed, and
read-only, non-root Docker scratch storage was checked. Cloud Fargate execution
and the Lambda ingestion/scoring hook were both exercised against real sources.

ECR scanning reports **7 high, 4 medium and 2 low OS findings**, still open after
applying all available Debian updates. Non-root execution, capability restrictions,
read-only root storage and no inbound access mitigate risk but do not fix findings.
See the [operations guide](../docs/scheduled-forecasts.md) for details and sources.

See [deployment evidence](scheduled_forecast_deployment.json) for execution/task
identifiers, schedule configuration, artifact hashes, scores and scan findings.
