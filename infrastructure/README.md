# AWS infrastructure

GridCast uses Terraform in `us-east-2` with the `default` CLI profile.

The daily ingestion job runs at **14:00 UTC**. It imports demand and historical
weather, validates them, writes Parquet, and collects current operational inputs.
The Fargate forecast job runs at **14:30 UTC**. Historical ERA5 data keeps a
seven-day lag; live forecast weather follows its own retrieval time.

## Before changing a deployment

1. Sign in to AWS and confirm the Region in AWS Settings → Projects → Overview → Additional Info.
2. Keep the existing ignored `infrastructure/terraform/terraform.tfvars`. Do not overwrite it with a partial example.
3. Build the Lambda layer, then review a saved Terraform plan.

```powershell
New-Item -ItemType Directory -Force .tools | Out-Null
.venv/Scripts/python.exe scripts/build_arrow_layer.py
terraform -chdir=infrastructure/terraform init -backend-config=backend.hcl
terraform -chdir=infrastructure/terraform plan -out=../../.tools/review.tfplan
terraform -chdir=infrastructure/terraform show -json ../../.tools/review.tfplan | Set-Content -Encoding utf8 .tools/review.json
.venv/Scripts/python.exe -m scripts.check_deployment_plan .tools/review.json
.venv/Scripts/python.exe -m scripts.check_cost_controls .tools/review.json
```

Apply the reviewed saved plan only after both guards pass. State lives in the
private S3 backend with locking and version history. Never commit state, plans,
local settings or secrets. Never delete state to fix an apply failure.

## Credentials and alerts

The EIA key belongs in Secrets Manager, outside Terraform. Use
`scripts/set_eia_secret.py` for a secure local prompt when replacing it. Confirm
the SNS email subscription to receive failure alerts.

A $5 budget sends early warnings; the operating target is $10/month before credits.
Neither is a guaranteed spending cap. Review spend in AWS Settings → Billing.
The lake blocks public access and keeps old object versions for 30 days.

## Operations

- Pause future jobs through `schedule_enabled` and `forecast_schedule_enabled`, then review and apply the change.
- Missing or invalid source data fails validation. Fix the source problem and rerun a bounded interval; do not fill values to force success.
- Keep the lake's deletion protection in place. Existing forecasts and score revisions are retained.

[Daily forecasts and scoring](../docs/scheduled-forecasts.md) ·
[GitHub deployment](../docs/github-actions-deployment.md) ·
[SQL analytics](../sql/README.md) ·
[Cost assumptions](../docs/cost-audit-2026-10-18.md)
