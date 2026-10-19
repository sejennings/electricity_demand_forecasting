# GridCast cost audit — October 18, 2026

The user's operating budget is **$10/month or less without promotional credits**.
Automatic deployment is desired when usage controls are present. The existing
footprint is expected to fit, but neither this estimate nor the controls below
guarantee a maximum AWS invoice.

## Live observations

- Region: us-east-2; Free Plan ACTIVE, $139.98 credits remaining. No upgrade or
  advanced-feature activation was performed.
- Cost Explorer, October 1–18 UTC, excluding credits/refunds: $0.0077246846.
  The existing budget separately reported $0.017. Different refresh times and
  incomplete new-workload billing make these unsuitable for monthly extrapolation.
- No running EC2 instances, available NAT gateways, or running ECS tasks were
  found in us-east-2. There is no always-on ECS service in the Terraform footprint.
- Two successful forecast workflows took approximately one minute each. Forecast
  compute requests 0.5 vCPU and 2 GiB RAM, with a public IPv4 address only while running.
- Both S3 buckets together contained 69,516,395 bytes including noncurrent object
  versions (about 0.0647 GiB). Logs have 14-day retention. Five standard alarms exist.
- The enforced Athena workgroup scan limit is 100 MiB **per query**. This does
  not cap the number of queries or queries submitted outside that workgroup.
- The $5 monthly gross-cost budget is healthy, with actual/forecast email alerts.
  It excludes credits, so credits cannot hide growth. It is not a spending cutoff.
- Today's scheduled ingestion failed with `Source request failed after retries`.
  This is a source-fetch failure, not a billing/permission error; recent forecast
  workflows succeeded. This audit did not retry or change ingestion.

## Monthly planning estimate

This uses 31 days, ten release smoke forecasts, and paid on-demand rates with
**no free allowances or promotional credits subtracted**. Taxes are excluded.

| Component | Monthly USD |
|---|---:|
| Forecast compute and IPv4: 41 tasks, two minutes each | 0.0466 |
| Five standard CloudWatch alarms | 0.50 |
| One Secrets Manager secret | 0.40 |
| ECR: 5 GiB allowance | 0.50 |
| S3: 5 GiB allowance | 0.115 |
| Athena: 1,000 queries scanning 100 MiB each | 0.4768 |
| Logs: 1 GB ingestion and storage allowance | 0.53 |
| Lambda, Step Functions and API request allowance | 1.00 |
| **Normal planning total** | **3.5685** |
| **Stress total: every forecast uses two 20-minute attempts** | **4.4547** |

Reproduce the arithmetic with `python scripts/estimate_monthly_cost.py`.
Ohio Price List API responses verified Fargate $0.04048/vCPU-hour and
$0.004445/GiB-hour; standard alarms $0.10/metric-month; S3 Standard first-tier
$0.023/GB-month; Secrets Manager $0.40/secret-month and $0.05/10,000 calls.
Other inputs use published pricing: [IPv4](https://aws.amazon.com/vpc/pricing/),
[ECR](https://aws.amazon.com/ecr/pricing/),
[Athena](https://aws.amazon.com/athena/pricing/), and
[CloudWatch](https://aws.amazon.com/cloudwatch/pricing/).

These are workload scenarios, not a Cost Explorer forecast or upper bound.
Storage grows over time; query count, log volume, manual executions, image pull
and cleanup duration, transfer charges, API calls, and other project resources
can differ. Regional public IPv4 billing and Fargate image-pull time are included
only through the task duration allowance. The stress case is not a worst-case bill.

## Controls

Already live: one daily ingestion and forecast schedule, bounded workflow timeouts
and retries, Lambda 512 MiB/600 seconds, Fargate 0.5 vCPU/2 GiB, 14-day logs,
100 MiB Athena query limit, old S3-version/query-result cleanup, and a $5 budget alert.

Added to the deployment PR:

- Before AWS authentication, refuse more than ten deployment attempts in a UTC
  calendar month, including reruns, failures and skipped runs. Missing/incomplete
  history fails closed. Workflow history must not be deleted to reset this counter.
- Before image publication, reserve room for a 1 GiB image within a conservative
  5 GiB ECR image-size allowance; block larger local images. Shared layers may be
  counted more than once. This prevents further pushes rather than deleting images.
- Before Terraform apply, require exactly the audited managed resource addresses
  and types. Reject changes to compute sizes, schedules, log retention, and Athena
  scan limits until the cost policy and estimate are reviewed. This blocks adding
  NAT gateways, always-on services, databases, or other unreviewed resources.
- The next container release adds an OS-level 20-minute process deadline, in
  addition to the existing workflow timeout and best-effort ECS cancellation.

The workflow changes and process deadline take effect after the PR is merged and
the image is released. They have not been applied to the running workload by this
audit. These controls limit this deployment path; they do not constrain console
changes or every AWS API. The policy file can itself be changed by maintainers,
and storage/query/log allowances are not global hard quotas.

## Deployment status and spending protection

The current blocker is AWS's managed organization policy denying IAM OIDC provider
creation. Automatic deployment is not being rejected because it is automatic.
It can be enabled after the owner resolves that restriction and reviews these
controls. No long-lived AWS access keys are substituted.

AWS's new-experience spend limit has a minimum of $20; advanced activation removes
that feature and is irreversible. A $10 guaranteed invoice ceiling is therefore
not available through this setup. [Spend limits](https://docs.aws.amazon.com/accounts/latest/reference/create-spend-limit.html),
[advanced activation](https://docs.aws.amazon.com/accounts/latest/reference/activate-advanced-features.html).
No billing upgrade or activation is authorized solely by accepting this estimate.
