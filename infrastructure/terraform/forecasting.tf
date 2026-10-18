variable "forecast_image_digest" {
  type    = string
  default = ""
  validation {
    condition     = var.forecast_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.forecast_image_digest))
    error_message = "Use an ECR SHA-256 image digest."
  }
}
variable "forecast_model_sha256" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.forecast_model_sha256))
    error_message = "Model SHA-256 must be 64 lowercase hexadecimal characters."
  }
}
variable "forecast_schedule_enabled" {
  type    = bool
  default = false
}
locals {
  forecast_workflow  = "arn:aws:states:us-east-2:${local.account}:stateMachine:gridcast-forecast"
  model_key          = "models/weather/${var.forecast_model_sha256}.joblib"
  forecast_image     = var.forecast_image_digest == "" ? "${aws_ecr_repository.model.repository_url}:bootstrap" : "${aws_ecr_repository.model.repository_url}@${var.forecast_image_digest}"
  forecast_generated = jsondecode(file("${path.module}/forecast-policy.generated.json")).Policies[0].Policy.Statement
}
resource "aws_ecr_repository" "model" {
  name                 = "gridcast-model"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  encryption_configuration { encryption_type = "AES256" }
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_ecr_lifecycle_policy" "model" {
  repository = aws_ecr_repository.model.name
  policy     = jsonencode({ rules = [{ rulePriority = 1, description = "Expire untagged images after 7 days", selection = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }, action = { type = "expire" } }] })
}
resource "aws_vpc" "forecast" {
  cidr_block           = "10.42.0.0/24"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "gridcast-forecast" }
}
resource "aws_internet_gateway" "forecast" { vpc_id = aws_vpc.forecast.id }
resource "aws_subnet" "forecast" {
  vpc_id            = aws_vpc.forecast.id
  cidr_block        = "10.42.0.0/26"
  availability_zone = "us-east-2a"
}
resource "aws_route_table" "forecast" {
  vpc_id = aws_vpc.forecast.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.forecast.id
  }
}
resource "aws_route_table_association" "forecast" {
  subnet_id      = aws_subnet.forecast.id
  route_table_id = aws_route_table.forecast.id
}
resource "aws_security_group" "forecast" {
  name        = "gridcast-forecast"
  description = "No inbound access; HTTPS egress for AWS, EIA and weather APIs"
  vpc_id      = aws_vpc.forecast.id
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_ecs_cluster" "forecast" { name = "gridcast" }
resource "aws_cloudwatch_log_group" "forecast" {
  name              = "/ecs/gridcast-forecast"
  retention_in_days = 14
}
resource "aws_iam_role" "forecast_task" {
  name = "gridcast-forecast-task"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnLike = { "aws:SourceArn" = "arn:aws:ecs:us-east-2:${local.account}:*" } }
  }] })
}
resource "aws_iam_role_policy" "forecast_task" {
  role = aws_iam_role.forecast_task.id
  # Generated SDK baseline narrowed by operation and exact application prefixes.
  policy = jsonencode({ Version = "2012-10-17", Statement = concat(
    [for s in local.forecast_generated : { Effect = "Allow", Action = [for a in s.Action : a if contains(["s3:GetObject", "s3:PutObject"], a)], Resource = [for p in ["raw/operational", "raw/operational-export", "processed/operational", "reports/operational", "forecasts", "scores"] : "${aws_s3_bucket.lake.arn}/${p}/*"] } if contains(s.Action, "s3:PutObject")],
    [{ Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${aws_s3_bucket.lake.arn}/${local.model_key}", "${aws_s3_bucket.lake.arn}/curated/parquet/hourly_demand/*"] },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.lake.arn, Condition = { StringLike = { "s3:prefix" = ["forecasts/runs/*", "scores/runs/*", "curated/parquet/hourly_demand/*"] } } },
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = aws_secretsmanager_secret.eia.arn }]
  ) })
}
resource "aws_iam_role" "forecast_execution" {
  name               = "gridcast-forecast-execution"
  assume_role_policy = aws_iam_role.forecast_task.assume_role_policy
}
resource "aws_iam_role_policy" "forecast_execution" {
  role = aws_iam_role.forecast_execution.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], Resource = aws_ecr_repository.model.arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.forecast.arn}:*" }
  ] })
}
resource "aws_ecs_task_definition" "forecast" {
  family                   = "gridcast-forecast"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.forecast_execution.arn
  task_role_arn            = aws_iam_role.forecast_task.arn
  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }
  container_definitions = jsonencode([{
    name                   = "forecast", image = local.forecast_image, essential = true,
    entryPoint             = ["python", "-m", "gridcast.daily"], command = [], user = "10001:10001",
    readonlyRootFilesystem = true,
    mountPoints            = [{ sourceVolume = "scratch", containerPath = "/tmp", readOnly = false }],
    linuxParameters        = { capabilities = { add = [], drop = ["ALL"] } },
    volumesFrom            = [], systemControls = [], portMappings = [],
    environment            = [for k, v in { AWS_DEFAULT_REGION = "us-east-2", LAKE_BUCKET = aws_s3_bucket.lake.id, EIA_SECRET_ARN = aws_secretsmanager_secret.eia.arn, MODEL_KEY = local.model_key, MODEL_SHA256 = var.forecast_model_sha256, MODEL_IMAGE_URI = local.forecast_image } : { name = k, value = v }],
    logConfiguration       = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.forecast.name, awslogs-region = "us-east-2", awslogs-stream-prefix = "forecast" } }
  }])
  volume { name = "scratch" }
}
resource "aws_iam_role" "forecast_workflow" {
  name               = "gridcast-forecast-workflow"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "states.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = local.account }, ArnEquals = { "aws:SourceArn" = local.forecast_workflow } } }] })
}
resource "aws_iam_role_policy" "forecast_workflow" {
  role = aws_iam_role.forecast_workflow.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecs:RunTask"], Resource = aws_ecs_task_definition.forecast.arn, Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.forecast.arn } } },
    { Effect = "Allow", Action = ["ecs:DescribeTasks", "ecs:StopTask"], Resource = "arn:aws:ecs:us-east-2:${local.account}:task/${aws_ecs_cluster.forecast.name}/*" },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = [aws_iam_role.forecast_task.arn, aws_iam_role.forecast_execution.arn], Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } } },
    { Effect = "Allow", Action = ["events:PutRule", "events:PutTargets", "events:DescribeRule"], Resource = "arn:aws:events:us-east-2:${local.account}:rule/StepFunctionsGetEventsForECSTaskRule" }
  ] })
}
resource "aws_sfn_state_machine" "forecast" {
  name     = "gridcast-forecast"
  role_arn = aws_iam_role.forecast_workflow.arn
  type     = "STANDARD"
  definition = jsonencode({ StartAt = "Forecast", TimeoutSeconds = 1500, States = {
    Forecast = { Type = "Task", Resource = "arn:aws:states:::ecs:runTask.sync", TimeoutSeconds = 1200,
      Parameters = { Cluster = aws_ecs_cluster.forecast.arn, TaskDefinition = aws_ecs_task_definition.forecast.arn, LaunchType = "FARGATE", PlatformVersion = "1.4.0",
        NetworkConfiguration = { AwsvpcConfiguration = { Subnets = [aws_subnet.forecast.id], SecurityGroups = [aws_security_group.forecast.id], AssignPublicIp = "ENABLED" } },
      Overrides = { ContainerOverrides = [{ Name = "forecast", Environment = [{ Name = "RUN_ID", "Value.$" = "$$.Execution.Name" }] }] } },
    Retry = [{ ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 30, MaxAttempts = 1, BackoffRate = 2 }], Next = "CheckExit" },
    CheckExit = { Type = "Choice", Choices = [{ Variable = "$.Containers[0].ExitCode", NumericEquals = 0, Next = "Done" }], Default = "Failed" },
    Done      = { Type = "Succeed" }, Failed = { Type = "Fail", Error = "ForecastContainerFailed" }
  } })
  depends_on = [aws_iam_role_policy.forecast_workflow, aws_iam_role_policy.forecast_task, aws_iam_role_policy.forecast_execution, aws_route_table_association.forecast]
}
resource "aws_scheduler_schedule" "forecast" {
  lifecycle {
    precondition {
      condition     = !var.forecast_schedule_enabled || var.forecast_image_digest != ""
      error_message = "Pin a published ECR digest before enabling forecasts."
    }
  }
  name                         = "daily-forecast"
  group_name                   = aws_scheduler_schedule_group.gridcast.name
  schedule_expression          = "cron(30 14 * * ? *)"
  schedule_expression_timezone = "UTC"
  state                        = var.forecast_schedule_enabled ? "ENABLED" : "DISABLED"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_sfn_state_machine.forecast.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{}"
    retry_policy { maximum_retry_attempts = 0 }
    dead_letter_config { arn = aws_sqs_queue.scheduler_dlq.arn }
  }
  depends_on = [aws_iam_role_policy.scheduler]
}
resource "aws_cloudwatch_metric_alarm" "forecast_failure" {
  for_each            = toset(["ExecutionsFailed", "ExecutionsTimedOut"])
  alarm_name          = "gridcast-forecast-${each.key}"
  namespace           = "AWS/States"
  metric_name         = each.key
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.forecast.arn }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
output "forecast_repository" { value = aws_ecr_repository.model.repository_url }
output "forecast_state_machine_arn" { value = aws_sfn_state_machine.forecast.arn }
