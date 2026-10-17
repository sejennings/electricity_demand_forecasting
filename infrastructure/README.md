# GridCast AWS data lake and ingestion

Terraform provisions the original project's first cloud milestone in **us-east-2**, using
the `default` AWS CLI profile. No web server or always-running container is needed.

EventBridge Scheduler → Step Functions Standard → parallel demand/weather Lambda tasks
→ validation and hourly demand/weather join → curated S3 CSV partitions.

## Data layout and behavior

- `raw/<source>/region=DUK/year=.../month=.../day=.../run=<execution>/`: source JSON.
- `processed/<source>/region=DUK/year=.../month=.../day=.../data.json`: validated hourly records.
- `curated/hourly/region=DUK/year=.../month=.../day=.../data.csv`: aligned demand and historical weather.
- `reports/`: source completeness and successful pipeline reports.
- `raw/history/`, `processed/history/`, `reports/history/`: original local backfill snapshot.

The daily run covers seven dates ending seven UTC days before execution, allowing ERA5
publication time and replay of recent revisions. This is a historical research pipeline,
not current-day forecasting. The model's assumed 24-hour demand delay does not change
this historical weather publication constraint. Future forecast-weather ingestion remains
necessary before deploying operational daily predictions.

Each invocation is limited to seven days. Missing hours, duplicates, nulls, unexpected
units and nonpositive demand fail validation. Raw downloaded evidence and completeness
reports are saved before validation; incomplete source data is not published as processed
or curated output. A failure can leave already validated processed source partitions,
but no successful pipeline report is written until curation completes. Consumers should
require a successful pipeline report for their requested interval. Current partition keys
are deterministic, with S3 versioning retaining overwritten versions for 30 days.
The source tasks retry twice; malformed/incomplete source data may remain failed until
the provider corrects it. Resolve the issue and rerun that bounded interval.

## Deploy and configure

Install Terraform and Python dependencies, authenticate using `aws login --profile default`,
and confirm the selected Region in AWS Settings → View all projects → Overview →
Additional Info → Region (`us-east-2`). Run from the repository root:

```powershell
python -m pip install -e ".[aws,model,analytics]"
python scripts/build_arrow_layer.py
terraform -chdir=infrastructure/terraform init
# This local file is ignored by Git:
'alert_email = "you@example.com"' | Set-Content infrastructure/terraform/terraform.tfvars
terraform -chdir=infrastructure/terraform plan -out=deploy.tfplan
terraform -chdir=infrastructure/terraform apply deploy.tfplan
# Secure local prompt; never paste an API key into chat or Terraform:
python scripts/set_eia_secret.py
python scripts/seed_lake.py --bucket <lake_bucket_output>
python scripts/run_cloud.py --end-date 2025-01-02 --days 1
```

The fresh EIA key is stored only in Secrets Manager, outside Terraform state. The secret
container exists after deployment but requires a value before demand ingestion works.
Confirm the SNS email subscription in your inbox to receive pipeline-failure alerts.
Only enable scheduling after a successful manual cloud run:

```powershell
# Add schedule_enabled = true to the ignored terraform.tfvars, then review and apply:
terraform -chdir=infrastructure/terraform plan -out=enable.tfplan
terraform -chdir=infrastructure/terraform apply enable.tfplan
```

Scheduler runs at 14:00 UTC daily. Its retry policy and encrypted SQS DLQ cover delivery
to Step Functions; delivery success does not imply workflow success. CloudWatch alarms
cover failed workflows and queued failed deliveries. Workflow ERROR logs exclude payload
data; Lambda and workflow log groups retain 14 days. AWS-managed encryption protects
logs and the secret. S3 uses SSE-S3 with public access blocked, ACLs disabled, TLS required,
and versioning enabled. Execution roles are scoped to this pipeline's resources. The
Step Functions and Scheduler role trusts have source-project/source-resource conditions.

## Costs and lifecycle

A $5 monthly budget covers the AWS project, excluding credits/refunds so credits do not
mask gross consumption. Alerts trigger above 80% actual or 100% forecast usage. This is
an alert, not a spending cap. Budget monitoring can lag actual usage. Review AWS Settings
→ Billing for your plan's credits and spending controls.

Charges can accrue for storage, S3 requests, Secrets Manager, workflow transitions,
Lambda, alarms, logs and notifications. No NAT Gateway, provisioned concurrency or
dedicated compute is configured. See current [S3](https://aws.amazon.com/s3/pricing/),
[Lambda](https://aws.amazon.com/lambda/pricing/),
[Step Functions](https://aws.amazon.com/step-functions/pricing/), and
[Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/) pricing.

For expanded auditing, enable S3 access logging, targeted CloudTrail S3 data events and
request metrics after reviewing their additional request/storage/event costs. Customer-managed
KMS encryption for logs and the alert topic can be added if stronger key control is needed.
Alert messages contain workflow metadata, not API keys or source payloads.

State and plans are local and ignored. Back up `terraform.tfstate` securely; never delete
it to troubleshoot a failed apply. The provider lockfile is committed for reproducibility.
The lake has Terraform deletion protection and `force_destroy=false`. To pause costs,
disable scheduling through Terraform. Destruction requires deliberate removal of the
lake protection and handling all stored versions; do not run destructive cleanup blindly.
The Parquet, Glue and Athena layer is deployed alongside ingestion. See
[SQL analytics instructions](../sql/README.md) for schemas, historical conversion and queries.

## Validate

```powershell
python -m unittest discover -s tests -v
terraform -chdir=infrastructure/terraform fmt -check
terraform -chdir=infrastructure/terraform validate
```

The Autopilot-generated IAM baseline is tracked as `lambda-policy.generated.json`.
Terraform narrows its S3 actions/resources and secret ARN, omits unused KMS/ACL/Object
Lambda actions, and adds runtime log-write permissions. Regenerate the baseline with:

```powershell
uvx --python .venv/Scripts/python.exe iam-policy-autopilot@latest generate-policies src/gridcast/cloud.py src/gridcast/analytics.py --region us-east-2 --account <project_aws_id> --service-hints s3 secretsmanager --pretty
```
