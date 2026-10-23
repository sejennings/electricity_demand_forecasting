# Terraform and GitHub Actions deployment

`Checks` runs on pull requests and pushes to `main`: regression tests,
deterministic PyArrow packaging, Terraform format/validation, and a Linux Docker
build with a non-root, read-only scratch-storage check. It receives no AWS
credentials. Actions use verified full commit SHAs.

`Deploy production` runs on relevant pushes to `main` or manual dispatch. It is
currently **disabled** with `AWS_DEPLOY_ENABLED=false`: AWS's managed service
control policy rejects GitHub OIDC provider creation. Existing daily forecasts
remain enabled independently of CI.

## Shared state

The existing production state has been migrated to
`s3://gridcast-tfstate-456112636403-us-east-2/production/terraform.tfstate`, preserving
all 57 resource records and its original lineage. The dedicated bucket is private,
encrypted with SSE-S3, versioned and protected against Terraform destruction.
`backend.hcl` enables native S3 state locking. State and plans never belong in Git
or Actions artifacts.

CI pins Terraform 1.16.6; provider locks include Windows and Linux checksums.
Locally, use the `default` profile. CI leaves the optional `aws_profile` variable
unset and uses OIDC environment credentials:

```powershell
$env:AWS_PROFILE='default'
terraform -chdir=infrastructure/terraform init '-backend-config=backend.hcl'
terraform -chdir=infrastructure/terraform plan
```

`infrastructure/bootstrap` separately owns the state bucket and GitHub identity.
Its initial local state is ignored by Git and must be preserved securely;
production CI cannot manage its own trust or permissions. The production S3 key
is authoritative. Never force-push stale local backups over the live shared state.

## Owner decision required for AWS deployment

Both `iam:ListOpenIDConnectProviders` and `iam:CreateOpenIDConnectProvider` returned
explicit SCP denies. The managed `DenyIAMRestrictedActions` statement includes
`iam:*Provider*`; an identity policy cannot override this deny. See
[AWS managed policies](https://docs.aws.amazon.com/accounts/latest/reference/scps-and-rcps-for-projects.html).

AWS says activating advanced features requires a plan upgrade, **cannot be
reversed**, and removes project spend limits. The $5 budget is an alert, not a
cap. Review [AWS activation](https://docs.aws.amazon.com/accounts/latest/reference/activate-advanced-features.html)
before deciding. This setup does not upgrade the plan, activate advanced features,
change organization policies, or create permanent access keys.

After owner authorization and activation, the organization's policy must permit
GitHub OIDC provider management. Review the generated deployment policies, then:

```powershell
terraform -chdir=infrastructure/bootstrap init
terraform -chdir=infrastructure/bootstrap plan '-var=enable_github_oidc=true' '-out=oidc.tfplan'
terraform -chdir=infrastructure/bootstrap apply oidc.tfplan
```

The trust uses the repository's verified immutable subject:
`repo:sejennings@89467945/electricity_demand_forecasting@1420011062:environment:production`.
Audience is exactly `sts.amazonaws.com`. The `production` GitHub environment allows
only `main`. PR workflows have no OIDC permission. See [GitHub OIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).

GitHub already has the expected deploy role ARN, weather-model SHA-256 and an
alert-email secret. No AWS keys are stored in GitHub. Once bootstrap succeeds and
this change is merged to `main`:

```powershell
gh variable set AWS_DEPLOY_ENABLED --body true --repo sejennings/electricity_demand_forecasting
gh workflow run deploy.yml --ref main --repo sejennings/electricity_demand_forecasting
```

The OIDC-authenticated production workflow remains unverified until that
prerequisite is resolved. New infrastructure operations can require regeneration
and owner review of deployment permissions.

## Release flow

1. Test, build the deterministic Lambda layer and validate Terraform before AWS
   authentication.
2. Assume the one-hour OIDC deployment role. Build/push an immutable tag containing
   commit/run/attempt IDs and resolve its digest.
3. Explicitly start a basic scan of the Linux amd64 image; the registry may have
   no scan-on-push rules even when the repository has its legacy scan flag set.
   Reuse the existing result if AWS's once-per-24-hours scan limit is reached.
   Critical findings block deployment; high findings
   are reported. Allow up to ten minutes for AWS to finish the scan; an incomplete
   scan blocks release. Existing findings are documented in [scheduled forecasts](scheduled-forecasts.md).
4. Verify the S3 model SHA-256 without deserializing it. CI does not train or
   silently promote a different model.
5. Plan against shared state, reject unexpected destruction and apply that exact
   plan. Only ECS task-definition and Lambda-layer replacements pass the deletion
   guard, plus cleanup of a deposed layer when a different, known active layer
   remains at the same Terraform address. Temporary plans are removed and never
   uploaded as artifacts.
6. Run a real forecast, checking exit status, image/model/content hashes, snapshot
   availability, 24 consecutive future hours, issue time and the matching score.
   Future actuals are expected to remain pending.

Deployments are serialized and are not cancelled by a newer push. The state-lock
timeout is five minutes. A failed smoke test fails the job and does not trigger an
automatic rollback. Recover by deploying reviewed known-good code/image changes;
an older model image alone does not roll back Lambda or infrastructure changes.

## Cost controls

The operating target is $10/month before promotional credits. The
[October cost audit](cost-audit-2026-10-18.md) estimates normal and stress usage
and distinguishes enforced controls from planning allowances. Deployment checks
limit monthly attempts, ECR image growth and the audited Terraform footprint.
They are not a guaranteed billing cap. Automatic deployment remains desired;
the current AWS OIDC policy restriction must be resolved before enabling it.
The guard requires the exact audited Terraform source hash for workflows, even
when their complete definitions are known. This also protects nested branches and
control flow not covered by the summary of task/retry/deadline limits. When a new
task revision makes the definition unknown during planning, the existing workflow
must also match the audited limits. Changing that Terraform source requires
another cost-policy review. Line endings are normalized across Windows and Linux.

## Policy provenance

The committed policy JSON combines IAM Policy Autopilot analysis of a real
release-shaped plan and verification scripts. PassRole is restricted to existing
GridCast service roles. Separate documented statements cover native Docker ECR
pushes and exact state/lock objects. CI has no Secrets Manager value-read access.

Create plan JSON under ignored `.tools/` without logging or committing it, then:

```powershell
uvx iam-policy-autopilot@latest generate-policies "$pwd/.tools/ci-release-plan.json" `
  --region us-east-2 --account 456112636403 --pretty
uvx iam-policy-autopilot@latest generate-policies `
  "$pwd/scripts/verify_model_artifact.py" "$pwd/scripts/check_image_scan.py" `
  "$pwd/scripts/verify_release.py" "$pwd/src/gridcast/scoring.py" `
  --region us-east-2 --account 456112636403 --service-hints ecr s3 states `
  --tf-dir "$pwd/infrastructure/terraform" --pretty
```

Keep only reviewed policy documents in Git. Never apply policy-analysis plans
that intentionally model replacements or use a placeholder image digest.

The explicit ECR scan permission was generated from `scripts/check_image_scan.py`
using the same Autopilot source command with `--service-hints ecr --tf-dir
infrastructure/terraform`, then merged into the existing exact-repository scan
statement. No wildcard scan permissions or enhanced-scanning charges were added.
