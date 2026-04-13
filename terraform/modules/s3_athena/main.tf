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

# Lifecycle — expire raw events (7 days dev, 30 days prod)
resource "aws_s3_bucket_lifecycle_configuration" "raw_lifecycle" {
  bucket = aws_s3_bucket.raw_events.id

  rule {
    id     = "expire-raw-events"
    status = "Enabled"

    expiration {
      days = var.env == "dev" ? 7 : 30
    }

    # Move to Glacier after 14 days in prod before deleting
    dynamic "transition" {
      for_each = var.env == "prod" ? [1] : []
      content {
        days          = 14
        storage_class = "GLACIER"
      }
    }
  }
}

# Lifecycle — expire corrected sessions (30 days dev, 90 days prod)
resource "aws_s3_bucket_lifecycle_configuration" "corrected_lifecycle" {
  bucket = aws_s3_bucket.corrected_sessions.id

  rule {
    id     = "expire-corrected-sessions"
    status = "Enabled"

    expiration {
      days = var.env == "dev" ? 30 : 90
    }
  }
}

# Lifecycle — expire Athena query results after 3 days (both envs)
resource "aws_s3_bucket_lifecycle_configuration" "athena_lifecycle" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    id     = "expire-query-results"
    status = "Enabled"

    expiration {
      days = 3
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
