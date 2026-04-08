###############################################################################
# S3 + Athena Module
#
# Creates:
# - Raw events bucket (Lambda writes NDJSON/Parquet here)
# - Corrected sessions bucket (Spark batch job writes here)
# - Athena query results bucket
# - Athena workgroup
# - Glue Data Catalog database
###############################################################################

locals {
  raw_bucket_name       = "clickstream-raw-${var.account_id}-${var.env}"
  corrected_bucket_name = "clickstream-corrected-${var.account_id}-${var.env}"
  athena_bucket_name    = "clickstream-athena-${var.account_id}-${var.env}"
}

# ---------------------------------------------------------------------------
# S3 Buckets
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "raw_events" {
  bucket        = local.raw_bucket_name
  force_destroy = var.env == "dev" ? true : false # Allow destroy in dev only

  tags = { Name = local.raw_bucket_name, Layer = "raw", Env = var.env }
}

resource "aws_s3_bucket" "corrected_sessions" {
  bucket        = local.corrected_bucket_name
  force_destroy = var.env == "dev" ? true : false

  tags = { Name = local.corrected_bucket_name, Layer = "batch", Env = var.env }
}

resource "aws_s3_bucket" "athena_results" {
  bucket        = local.athena_bucket_name
  force_destroy = var.env == "dev" ? true : false

  tags = { Name = local.athena_bucket_name, Layer = "query", Env = var.env }
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw_events.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "corrected" {
  bucket                  = aws_s3_bucket.corrected_sessions.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "athena" {
  bucket                  = aws_s3_bucket.athena_results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle — delete raw events after 7 days in dev (cost control)
resource "aws_s3_bucket_lifecycle_configuration" "raw_lifecycle" {
  bucket = aws_s3_bucket.raw_events.id

  rule {
    id     = "expire-dev-data"
    status = var.env == "dev" ? "Enabled" : "Disabled"

    expiration {
      days = 7
    }
  }
}

# ---------------------------------------------------------------------------
# Athena Workgroup
# ---------------------------------------------------------------------------

resource "aws_athena_workgroup" "main" {
  name  = "clickstream-${var.env}"
  state = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.bucket}/query-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }

    # Limit query scans to 10GB per query in dev (cost guard)
    bytes_scanned_cutoff_per_query = var.env == "dev" ? 10737418240 : null
  }

  tags = { Name = "clickstream-${var.env}", Env = var.env }
}

# ---------------------------------------------------------------------------
# Glue Data Catalog database
# ---------------------------------------------------------------------------

resource "aws_glue_catalog_database" "clickstream" {
  name        = "clickstream_${var.env}"
  description = "Clickstream pipeline — raw events and corrected sessions"
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "raw_bucket_name" {
  value = aws_s3_bucket.raw_events.bucket
}

output "raw_bucket_arn" {
  value = aws_s3_bucket.raw_events.arn
}

output "corrected_bucket_name" {
  value = aws_s3_bucket.corrected_sessions.bucket
}

output "athena_workgroup_name" {
  value = aws_athena_workgroup.main.name
}

output "glue_database_name" {
  value = aws_glue_catalog_database.clickstream.name
}
