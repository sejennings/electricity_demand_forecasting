locals {
  dashboard_generated = jsondecode(file("${path.module}/dashboard-policy.generated.json")).Policies[0].Policy.Statement
}

# This bucket contains one public summary, never raw data or credentials.
resource "aws_s3_bucket" "dashboard" {
  bucket        = "gridcast-public-${local.account}-us-east-2"
  force_destroy = false
}
resource "aws_s3_bucket_ownership_controls" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_public_access_block" "dashboard" {
  bucket                  = aws_s3_bucket.dashboard.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = false
  restrict_public_buckets = false
}
resource "aws_s3_bucket_policy" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid = "ReadDashboardSummary", Effect = "Allow", Principal = "*", Action = "s3:GetObject", Resource = "${aws_s3_bucket.dashboard.arn}/snapshot.json" },
    { Sid = "RequireTLS", Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [aws_s3_bucket.dashboard.arn, "${aws_s3_bucket.dashboard.arn}/*"], Condition = { Bool = { "aws:SecureTransport" = "false" } } }
  ] })
  depends_on = [aws_s3_bucket_public_access_block.dashboard]
}
resource "aws_s3_bucket_cors_configuration" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  cors_rule {
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["https://sejennings.github.io"]
    max_age_seconds = 300
  }
}
resource "aws_cloudwatch_log_group" "dashboard" {
  name              = "/aws/lambda/gridcast-publish-dashboard"
  retention_in_days = 7
}
resource "aws_iam_role" "dashboard" {
  name = "gridcast-publish-dashboard"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}
resource "aws_iam_role_policy" "dashboard" {
  role = aws_iam_role.dashboard.id
  # Autopilot baseline narrowed to exact runtime calls, objects and workflows.
  # ACLs and customer KMS keys are unused; list-all-buckets is not required.
  policy = jsonencode({ Version = "2012-10-17", Statement = concat(
    [for s in local.dashboard_generated : { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${aws_s3_bucket.lake.arn}/forecasts/runs/*", "${aws_s3_bucket.lake.arn}/scores/runs/*"] } if contains(s.Action, "s3:GetObject")],
    [for s in local.dashboard_generated : { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.dashboard.arn}/snapshot.json" } if contains(s.Action, "s3:PutObject")],
    [for s in local.dashboard_generated : { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.lake.arn, Condition = { StringLike = { "s3:prefix" = ["forecasts/runs/*", "scores/runs/*"] } } } if contains(s.Action, "s3:ListBucket")],
    [for s in local.dashboard_generated : { Effect = "Allow", Action = ["states:ListExecutions"], Resource = [aws_sfn_state_machine.ingestion.arn, aws_sfn_state_machine.forecast.arn] } if contains(s.Action, "states:ListExecutions")],
    [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.dashboard.arn}:*" }]
  ) })
}
resource "aws_lambda_function" "dashboard" {
  function_name    = "gridcast-publish-dashboard"
  role             = aws_iam_role.dashboard.arn
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "gridcast.publish_dashboard.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = 256
  timeout          = 120
  # This Free Plan project must retain all 10 slots as unreserved capacity.
  # There is no public invoke endpoint; only the twice-daily scheduler invokes it.
  reserved_concurrent_executions = -1
  environment {
    variables = { PUBLIC_BUCKET = aws_s3_bucket.dashboard.id }
  }
  depends_on = [aws_iam_role_policy.dashboard, aws_cloudwatch_log_group.dashboard]
}
resource "aws_lambda_function_event_invoke_config" "dashboard" {
  function_name                = aws_lambda_function.dashboard.function_name
  maximum_event_age_in_seconds = 1800
  maximum_retry_attempts       = 0
}
resource "aws_iam_role" "dashboard_schedule" {
  name = "gridcast-dashboard-scheduler"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnEquals = { "aws:SourceArn" = aws_scheduler_schedule_group.gridcast.arn } }
  }] })
}
resource "aws_iam_role_policy" "dashboard_schedule" {
  role = aws_iam_role.dashboard_schedule.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.dashboard.arn },
    { Effect = "Allow", Action = "sqs:SendMessage", Resource = aws_sqs_queue.scheduler_dlq.arn }
  ] })
}
resource "aws_scheduler_schedule" "dashboard" {
  name                         = "publish-dashboard"
  group_name                   = aws_scheduler_schedule_group.gridcast.name
  schedule_expression          = "cron(15 14,15 * * ? *)"
  schedule_expression_timezone = "UTC"
  state                        = var.schedule_enabled ? "ENABLED" : "DISABLED"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.dashboard.arn
    role_arn = aws_iam_role.dashboard_schedule.arn
    input    = "{}"
    retry_policy {
      maximum_retry_attempts       = 1
      maximum_event_age_in_seconds = 1800
    }
    dead_letter_config { arn = aws_sqs_queue.scheduler_dlq.arn }
  }
  depends_on = [aws_iam_role_policy.dashboard_schedule]
}
resource "aws_cloudwatch_metric_alarm" "dashboard" {
  alarm_name          = "gridcast-dashboard-publish-failed"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.dashboard.function_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
output "dashboard_snapshot_url" {
  value = "https://${aws_s3_bucket.dashboard.bucket_regional_domain_name}/snapshot.json"
}
