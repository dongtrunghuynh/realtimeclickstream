##############################################################################
# main.tf — root module
# Wires together: Kinesis → Lambda → S3 (raw + processed) + Glue + Monitoring
##############################################################################

locals {
  prefix     = "${var.project}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
}

# ── IAM ──────────────────────────────────────────────────────────────────────

module "iam" {
  source = "./modules/iam"

  project        = var.project
  environment    = var.environment
  aws_region     = local.region
  aws_account_id = local.account_id

  kinesis_stream_arns = [module.kinesis.stream_arn]
  raw_bucket_arn      = module.s3_raw.bucket_arn
  processed_bucket_arn = module.s3_processed.bucket_arn
  dlq_arn             = module.monitoring.dlq_arn

  tags = var.tags
}

# ── Kinesis Data Stream ───────────────────────────────────────────────────────

module "kinesis" {
  source = "./modules/kinesis"

  name             = "${local.prefix}-events"
  shard_count      = var.kinesis_shard_count
  retention_hours  = var.kinesis_retention_hours
  stream_mode      = var.kinesis_stream_mode

  tags = var.tags
}

# ── S3 Buckets ────────────────────────────────────────────────────────────────

module "s3_raw" {
  source = "./modules/s3"

  project       = var.project
  environment   = var.environment
  bucket_suffix = "raw"
  force_destroy = var.s3_force_destroy
  expiry_days   = null    # raw events kept indefinitely for replay

  tags = var.tags
}

module "s3_processed" {
  source = "./modules/s3"

  project       = var.project
  environment   = var.environment
  bucket_suffix = "processed"
  force_destroy = var.s3_force_destroy
  expiry_days   = var.s3_processed_expiry_days

  tags = var.tags
}

# ── Lambda Stream Processor ───────────────────────────────────────────────────

module "lambda" {
  source = "./modules/lambda"

  function_name  = "${local.prefix}-stream-processor"
  description    = "Clickstream event processor: Kinesis → S3 (raw + processed)"
  iam_role_arn   = module.iam.lambda_exec_role_arn

  zip_path       = var.lambda_zip_path
  memory_mb      = var.lambda_memory_mb
  timeout        = var.lambda_timeout_seconds
  reserved_concurrency = var.lambda_reserved_concurrency

  environment_variables = {
    ENVIRONMENT       = var.environment
    RAW_BUCKET        = module.s3_raw.bucket_id
    PROCESSED_BUCKET  = module.s3_processed.bucket_id
    PROCESSED_PREFIX  = "processed/"
    LOG_LEVEL         = var.environment == "prod" ? "WARNING" : "INFO"
  }

  kinesis_stream_arn      = module.kinesis.stream_arn
  kinesis_batch_size      = var.lambda_batch_size
  kinesis_starting_position = var.lambda_starting_position
  dlq_arn                 = module.monitoring.dlq_arn
  log_retention_days      = var.log_retention_days

  tags = var.tags
}

# ── Glue Catalog + Crawler ────────────────────────────────────────────────────

module "glue" {
  source = "./modules/glue"

  project             = var.project
  environment         = var.environment
  aws_region          = local.region
  aws_account_id      = local.account_id
  processed_bucket_id = module.s3_processed.bucket_id
  processed_prefix    = "processed/"

  tags = var.tags
}

# ── Monitoring: CloudWatch Alarms + DLQ + Dashboard ──────────────────────────

module "monitoring" {
  source = "./modules/monitoring"

  project       = var.project
  environment   = var.environment
  aws_region    = local.region

  lambda_function_name   = module.lambda.function_name
  kinesis_stream_name    = module.kinesis.stream_name
  processed_bucket_id    = module.s3_processed.bucket_id

  alarm_email            = var.alarm_email
  log_retention_days     = var.log_retention_days

  tags = var.tags
}
