terraform {
  required_version = ">= 1.10"
  backend "s3" {}
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
  }
}

provider "aws" {
  region  = "us-east-2"
  profile = var.aws_profile
  default_tags {
    tags = { Project = "GridCast", ManagedBy = "Terraform" }
  }
}
# Budgets is a global billing API; this provider creates no regional infrastructure.
provider "aws" {
  alias   = "billing"
  region  = "us-east-1"
  profile = var.aws_profile
}
variable "aws_profile" {
  type = string
  default = null
  description = "Optional local CLI profile; CI uses OIDC environment credentials."
}
variable "alert_email" { type = string }
variable "schedule_enabled" {
  type    = bool
  default = false
}
data "aws_caller_identity" "current" {}
locals {
  name      = "gridcast"
  account   = data.aws_caller_identity.current.account_id
  workflow  = "arn:aws:states:us-east-2:${local.account}:stateMachine:gridcast-ingestion"
  generated = jsondecode(file("${path.module}/lambda-policy.generated.json")).Policies[0].Policy.Statement
}
resource "aws_s3_bucket" "lake" {
  bucket        = "gridcast-lake-${local.account}-us-east-2"
  force_destroy = false
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = aws_s3_bucket.lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_versioning" "lake" {
  bucket = aws_s3_bucket.lake.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_policy" "lake" {
  bucket = aws_s3_bucket.lake.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.lake.arn, "${aws_s3_bucket.lake.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket     = aws_s3_bucket.lake.id
  depends_on = [aws_s3_bucket_versioning.lake]
  rule {
    id     = "bound-old-versions"
    status = "Enabled"
    filter { prefix = "" }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
  rule {
    id     = "expire-query-results"
    status = "Enabled"
    filter { prefix = "athena-results/" }
    expiration { days = 7 }
  }
  rule {
    id     = "bound-large-operational-exports"
    status = "Enabled"
    filter { prefix = "raw/operational-export/" }
    expiration { days = 30 }
  }
}
resource "aws_secretsmanager_secret" "eia" {
  name                    = "gridcast/eia-api-key"
  description             = "EIA API key; value is provisioned outside Terraform"
  recovery_window_in_days = 7
}
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/gridcast-ingestion"
  retention_in_days = 14
}
resource "aws_cloudwatch_log_group" "workflow" {
  name              = "/aws/vendedlogs/states/gridcast-ingestion"
  retention_in_days = 14
}
resource "aws_iam_role" "lambda" {
  name = "gridcast-ingestion-lambda"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}
resource "aws_iam_role_policy" "lambda" {
  role = aws_iam_role.lambda.id
  # Autopilot baseline narrowed to the API operations and exact resources used here.
  # SSE-S3/default Secrets Manager encryption require no customer KMS permissions.
  policy = jsonencode({ Version = "2012-10-17", Statement = concat(
    [for s in local.generated : {
      Effect   = "Allow"
      Action   = [for a in s.Action : a if contains(["s3:GetObject", "s3:PutObject"], a)]
      Resource = [for prefix in ["raw", "processed", "curated", "reports", "scores"] : "${aws_s3_bucket.lake.arn}/${prefix}/*"]
    } if contains(s.Action, "s3:PutObject")],
    [for s in local.generated : {
      Effect = "Allow", Action = s.Action, Resource = [aws_secretsmanager_secret.eia.arn]
    } if contains(s.Action, "secretsmanager:GetSecretValue")],
    [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.lambda.arn}:*" }]
    , [{ Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.lake.arn,
      Condition = { StringLike = { "s3:prefix" = ["curated/parquet/*", "forecasts/runs/*", "scores/runs/*"] } } },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.lake.arn}/forecasts/*" }]
  ) })
}
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../../src"
  output_path = "${path.module}/build/ingestion.zip"
  excludes    = ["gridcast/__pycache__"]
}
resource "aws_lambda_function" "ingestion" {
  function_name    = "gridcast-ingestion"
  role             = aws_iam_role.lambda.arn
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "gridcast.cloud.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = 512
  layers           = [aws_lambda_layer_version.arrow.arn]
  timeout          = 600
  environment {
    variables = { LAKE_BUCKET = aws_s3_bucket.lake.id, EIA_SECRET_ARN = aws_secretsmanager_secret.eia.arn }
  }
  depends_on = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
}
resource "aws_iam_role" "workflow" {
  name = "gridcast-ingestion-workflow"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "states.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnEquals = { "aws:SourceArn" = local.workflow } }
  }] })
}
resource "aws_iam_role_policy" "workflow" {
  role = aws_iam_role.workflow.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.ingestion.arn },
    # CloudWatch delivery APIs do not support resource-level permissions.
    { Effect = "Allow", Action = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"], Resource = "*" }
  ] })
}
resource "aws_sfn_state_machine" "ingestion" {
  name     = "gridcast-ingestion"
  role_arn = aws_iam_role.workflow.arn
  type     = "STANDARD"
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.workflow.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }
  definition = jsonencode({ StartAt = "Fetch", TimeoutSeconds = 1800, States = {
    Fetch = {
      Type = "Parallel", ResultPath = "$.sources", Next = "Curate",
      Branches = [for source in ["demand", "weather"] : {
        StartAt = "Import${source}", States = { ("Import${source}") = {
          Type       = "Task", Resource = "arn:aws:states:::lambda:invoke", TimeoutSeconds = 650,
          Parameters = { FunctionName = aws_lambda_function.ingestion.arn, Payload = { source = source, "run_id.$" = "$$.Execution.Name", "days.$" = "$.days", "end_date.$" = "$.end_date" } },
          Retry      = [{ ErrorEquals = ["Lambda.ServiceException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException", "States.TaskFailed"], IntervalSeconds = 10, MaxAttempts = 2, BackoffRate = 2, JitterStrategy = "FULL" }],
          OutputPath = "$.Payload", End = true
        } }
      }]
    },
    Curate = {
      Type       = "Task", Resource = "arn:aws:states:::lambda:invoke", TimeoutSeconds = 650,
      Parameters = { FunctionName = aws_lambda_function.ingestion.arn, Payload = { action = "curate", "run_id.$" = "$$.Execution.Name", "days.$" = "$.days", "end_date.$" = "$.end_date" } },
      Retry      = [{ ErrorEquals = ["Lambda.ServiceException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"], IntervalSeconds = 5, MaxAttempts = 2, BackoffRate = 2 }],
      OutputPath = "$.Payload", Next = "Operational"
    },
    Operational = {
      Type           = "Task", Resource = "arn:aws:states:::lambda:invoke", TimeoutSeconds = 650,
      Parameters     = { FunctionName = aws_lambda_function.ingestion.arn, Payload = { action = "operational" } },
      Retry          = [{ ErrorEquals = ["Lambda.ServiceException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"], IntervalSeconds = 5, MaxAttempts = 2, BackoffRate = 2 }],
      ResultSelector = { "snapshot.$" = "$.Payload" }, ResultPath = "$.operational", End = true
    }
  } })
  depends_on = [aws_iam_role_policy.workflow]
}
resource "aws_sqs_queue" "scheduler_dlq" {
  name                      = "gridcast-scheduler-dlq"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}
resource "aws_scheduler_schedule_group" "gridcast" { name = "gridcast" }
resource "aws_iam_role" "scheduler" {
  name = "gridcast-scheduler"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnEquals = { "aws:SourceArn" = aws_scheduler_schedule_group.gridcast.arn } }
  }] })
}
resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["states:StartExecution"], Resource = [aws_sfn_state_machine.ingestion.arn, local.forecast_workflow] },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.scheduler_dlq.arn }
  ] })
}
resource "aws_scheduler_schedule" "daily" {
  name                         = "daily-ingestion"
  group_name                   = aws_scheduler_schedule_group.gridcast.name
  schedule_expression          = "cron(0 14 * * ? *)"
  schedule_expression_timezone = "UTC"
  state                        = var.schedule_enabled ? "ENABLED" : "DISABLED"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_sfn_state_machine.ingestion.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ days = 7, end_date = "" })
    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
    dead_letter_config { arn = aws_sqs_queue.scheduler_dlq.arn }
  }
  depends_on = [aws_iam_role_policy.scheduler]
}
resource "aws_sns_topic" "alerts" { name = "gridcast-alerts" }
resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" }, Action = "sns:Publish",
    Resource = aws_sns_topic.alerts.arn,
    Condition = { StringEquals = { "aws:SourceAccount" = local.account },
    ArnLike = { "aws:SourceArn" = "arn:aws:cloudwatch:us-east-2:${local.account}:alarm:gridcast-*" } }
  }] })
}
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
resource "aws_cloudwatch_metric_alarm" "failed" {
  alarm_name          = "gridcast-pipeline-failed"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.ingestion.arn }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "dlq" {
  alarm_name          = "gridcast-scheduler-delivery-failed"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = aws_sqs_queue.scheduler_dlq.name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "timed_out" {
  alarm_name          = "gridcast-pipeline-timed-out"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsTimedOut"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.ingestion.arn }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_budgets_budget" "monthly" {
  provider     = aws.billing
  name         = "GridCast-project-monthly"
  budget_type  = "COST"
  limit_amount = "5"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  cost_types {
    include_credit = false
    include_refund = false
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
output "lake_bucket" { value = aws_s3_bucket.lake.id }
output "state_machine_arn" { value = aws_sfn_state_machine.ingestion.arn }
output "eia_secret_arn" { value = aws_secretsmanager_secret.eia.arn }
output "schedule_enabled" { value = var.schedule_enabled }
