###############################################################################
# Root Terraform configuration — wires together all modules
#
# Usage:
#   terraform workspace select dev
#   terraform apply -var-file=environments/dev.tfvars
#
# To tear down completely (costs go to $0):
#   terraform destroy -var-file=environments/dev.tfvars
###############################################################################

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "clickstream-pipeline"
      Environment = terraform.workspace
      ManagedBy   = "terraform"
    }
  }
}

locals {
  env    = terraform.workspace # "dev" or "prod"
  suffix = local.env
}

# ---------------------------------------------------------------------------
# Kinesis Data Stream
# ---------------------------------------------------------------------------

module "kinesis" {
  source      = "./modules/kinesis"
  stream_name = "clickstream-events-${local.suffix}"
  env         = local.env
}

# ---------------------------------------------------------------------------
# DynamoDB — Speed Layer (real-time session state)
# ---------------------------------------------------------------------------

module "dynamodb" {
  source     = "./modules/dynamodb"
  table_name = "clickstream-sessions-${local.suffix}"
  env        = local.env
}

# ---------------------------------------------------------------------------
# S3 + Athena — Batch Layer
# ---------------------------------------------------------------------------

module "s3_athena" {
  source     = "./modules/s3_athena"
  account_id = data.aws_caller_identity.current.account_id
  env        = local.env
  aws_region = var.aws_region
}

# ---------------------------------------------------------------------------
# Lambda — Sessionizer (speed layer consumer)
# ---------------------------------------------------------------------------

module "lambda" {
  source                 = "./modules/lambda"
  env                    = local.env
  kinesis_stream_arn     = module.kinesis.stream_arn
  dynamodb_table_name    = module.dynamodb.table_name
  dynamodb_table_arn     = module.dynamodb.table_arn
  s3_bucket              = module.s3_athena.raw_bucket_name
  s3_bucket_arn          = module.s3_athena.raw_bucket_arn
  aws_region             = var.aws_region
  lambda_memory_mb       = var.lambda_memory_mb
  lambda_timeout_seconds = var.lambda_timeout_seconds
  kinesis_batch_size     = var.kinesis_batch_size
}

# ---------------------------------------------------------------------------
# EMR Serverless — Batch Layer (Spark job)
# ---------------------------------------------------------------------------

module "emr_serverless" {
  source        = "./modules/emr_serverless"
  env           = local.env
  s3_bucket     = module.s3_athena.raw_bucket_name
  s3_bucket_arn = module.s3_athena.raw_bucket_arn
  aws_region    = var.aws_region
}

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# CloudWatch — Dashboard and alarms
# ---------------------------------------------------------------------------

module "cloudwatch" {
  source               = "./modules/cloudwatch"
  env                  = local.env
  aws_region           = var.aws_region
  lambda_function_name = module.lambda.function_name
  kinesis_stream_name  = module.kinesis.stream_name
  dynamodb_table_name  = module.dynamodb.table_name
}

# ---------------------------------------------------------------------------
# Outputs — reference these in scripts and application code
# ---------------------------------------------------------------------------

output "kinesis_stream_name" {
  description = "Set as KINESIS_STREAM_NAME env var in the simulator"
  value       = module.kinesis.stream_name
}

output "dynamodb_table_name" {
  description = "Set as DYNAMODB_TABLE_NAME env var in Lambda"
  value       = module.dynamodb.table_name
}

output "raw_s3_bucket" {
  description = "S3 bucket for raw events + late arrivals"
  value       = module.s3_athena.raw_bucket_name
}

output "emr_application_id" {
  description = "Set as EMR_APPLICATION_ID env var in submit_spark_job.sh"
  value       = module.emr_serverless.application_id
}

output "emr_execution_role_arn" {
  description = "IAM role ARN for Spark job submissions"
  value       = module.emr_serverless.execution_role_arn
}

output "athena_workgroup" {
  description = "Athena workgroup name"
  value       = module.s3_athena.athena_workgroup_name
}

output "lambda_dlq_url" {
  description = "Set as DLQ_URL env var for dlq_handler.py"
  value       = module.lambda.dlq_url
}

output "cloudwatch_dashboard_url" {
  description = "Direct link to the operational dashboard"
  value       = module.cloudwatch.dashboard_url
}
