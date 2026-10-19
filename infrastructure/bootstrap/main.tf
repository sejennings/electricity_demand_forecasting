terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
provider "aws" {
  region = "us-east-2"
  default_tags { tags = { Project = "GridCast", ManagedBy = "Terraform" } }
}
variable "enable_github_oidc" {
  type = bool
  default = false
  description = "Enable only after AWS lifts the managed SCP deny on IAM identity providers."
}
variable "github_subject" {
  type = string
  default = "repo:sejennings@89467945/electricity_demand_forecasting@1420011062:environment:production"
  description = "Verified immutable GitHub repository subject; production environment is restricted to main."
}
resource "aws_s3_bucket" "state" {
  bucket = "gridcast-tfstate-456112636403-us-east-2"
  force_destroy = false
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id
  block_public_acls = true
  block_public_policy = true
  ignore_public_acls = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule { apply_server_side_encryption_by_default { sse_algorithm = "AES256" } }
}
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({Version="2012-10-17",Statement=[{
    Effect="Deny",Principal="*",Action="s3:*",Resource=[aws_s3_bucket.state.arn,"${aws_s3_bucket.state.arn}/*"],
    Condition={Bool={"aws:SecureTransport"="false"}}
  }]})
}
resource "aws_iam_openid_connect_provider" "github" {
  count = var.enable_github_oidc ? 1 : 0
  url = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}
resource "aws_iam_role" "github" {
  count = var.enable_github_oidc ? 1 : 0
  name = "gridcast-github-deploy"
  max_session_duration = 3600
  assume_role_policy = jsonencode({Version="2012-10-17",Statement=[{
    Effect="Allow",Principal={Federated=aws_iam_openid_connect_provider.github[0].arn},
    Action="sts:AssumeRoleWithWebIdentity",Condition={StringEquals={
      "token.actions.githubusercontent.com:aud"="sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub"=var.github_subject
    }}
  }]})
}
resource "aws_iam_policy" "github" {
  for_each = var.enable_github_oidc ? {for i,p in jsondecode(file("${path.module}/deployment-policies.generated.json")) : tostring(i) => p} : {}
  name = "gridcast-github-deploy-${each.key}"
  policy = jsonencode(each.value)
}
resource "aws_iam_role_policy_attachment" "github" {
  for_each = aws_iam_policy.github
  role = aws_iam_role.github[0].name
  policy_arn = each.value.arn
}
output "state_bucket" { value = aws_s3_bucket.state.id }
output "github_role_arn" { value = var.enable_github_oidc ? aws_iam_role.github[0].arn : null }
