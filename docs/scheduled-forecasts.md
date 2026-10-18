# Scheduled forecasts and delayed scoring

Terraform provisions private ECR `gridcast-model`, ECS cluster `gridcast`, the
`gridcast-forecast` Fargate task/workflow, and Scheduler `gridcast/daily-forecast`
in **us-east-2**. The daily schedule is 14:30 UTC (10:30 AM Eastern daylight time,
9:30 AM Eastern standard time). The existing demand pipeline runs at 14:00 UTC.

The workflow waits for task completion, checks its exit code and limits a task to
20 minutes with one task-failure retry, within a 25-minute workflow deadline.
CloudWatch failure/timeout alarms use the existing confirmed SNS subscription;
Scheduler delivery failures use the existing DLQ. A delivery retry is disabled
to avoid additional daily issues when an acknowledgement is ambiguous.

The task uses 0.5 vCPU / 2 GiB RAM, Linux x86-64 Fargate 1.4.0, UID 10001,
a read-only root filesystem and writable ephemeral `/tmp`. All Linux capabilities
are dropped. A dedicated public subnet provides HTTPS egress for AWS/EIA/weather
with no inbound security-group rules, NAT gateway, load balancer or persistent
running service. Its public IPv4 exists only while the task runs. ECR, storage,
Fargate, IPv4 and logging incur usage charges; the existing $5 budget is an alert,
not a spending cap. The project remains on its Free plan.

## Reproducible artifacts

Task definitions pin the ECR image by digest and the trusted model by SHA-256.
The task role can read only the chosen model key, published actual-demand Parquet,
and operational/forecast/score prefixes; it can write operational snapshots,
forecasts and scores. It cannot overwrite the model. Its only secret access is
the existing EIA secret. A separate execution role handles ECR pulls and logs.
No local AWS credentials, model or datasets are embedded in the image.
If both EIA API requests time out, collection can use the official published
workbook alone. The manifest labels that source explicitly, reports the latest
observed hour and missing hours, and does not fabricate API updates.

Each task downloads and verifies the model before loading it, collects fresh
inputs and records actual issuance after input retrieval. The scheduled trigger
time is never substituted for the issue time. The next whole UTC hour begins its
24-hour horizon. A run that misses that origin before publication fails.

Each workflow execution name is the forecast ID. The atomic S3 record at
`forecasts/runs/<id>/manifest.json` contains the original CSV, issue time, origin,
model/content hashes, image URI and snapshot reference. Conditional creation
prevents replacement. A retry reuses a committed record and continues scoring.
Overlapping target hours from separate issues remain separate forecasts.
Source snapshots retain their existing raw/processed/report archival paths.

## Actuals and scores

Scoring runs after the ingestion pipeline's operational demand import and after
each Fargate forecast. It reads current monthly demand Parquet and overlays the
newest published observations in the operational snapshot. It never fills missing
actuals and does not score an hour before it has ended. Consequently a forecast
can remain `pending` or `partial` until a later daily import supplies its final
hours. This is scoring on daily imports, not continuous source polling.

`scores/runs/<id>/latest.json` points to the newest scoring observation. The
immutable `revisions/<content-hash>.json` records its actual values, first scoring
time, source snapshot, MAE/RMSE/WAPE, horizon errors and pending count. Identical
inputs reuse the same revision. EIA corrections create another revision without
changing the forecast or deleting earlier scores. Conditional pointer updates
prevent an older concurrent scorer from replacing a newer observation.

The actuals policy is latest published demand at each scoring observation, not
an assertion that those values were the original publication. Forecast-vintage
timing assumptions from training remain documented separately. Online accuracy
accumulates prospectively and is separate from retrospective evaluation metrics.

## Operations

Use `aws stepfunctions start-execution --state-machine-arn
arn:aws:states:us-east-2:456112636403:stateMachine:gridcast-forecast --region us-east-2
--profile default` for an additional issue. An extra execution creates another
forecast; it does not replace the daily one. Task logs are in `/ecs/gridcast-forecast`.

`forecast_image_digest`, `forecast_model_sha256`, and
`forecast_schedule_enabled` are Terraform inputs saved locally in ignored tfvars.
Keep the schedule disabled until the image/model are present and a manual cloud
run succeeds. To pause future jobs, set `forecast_schedule_enabled=false` and
apply Terraform. Historical forecasts and scores remain in the versioned lake.
Tagged ECR release images are retained; untagged images expire after seven days.
Rebuilds should apply OS security updates, use a new immutable tag, scan the
platform image and pin the tested digest in Terraform.

## Open image scan findings

The October 18 release applied all available Bookworm OS updates (none were
available at build time). ECR basic scanning still reports **7 high, 4 medium and
2 low** OS findings. These remain open; capability restrictions and non-root
execution are mitigations, not fixes. The high findings name util-linux and zlib.
Debian's trackers for [util-linux](https://security-tracker.debian.org/tracker/CVE-2026-76642)
and [zlib](https://security-tracker.debian.org/tracker/CVE-2026-85091) document
their release status. Do not represent this image as vulnerability-free.
