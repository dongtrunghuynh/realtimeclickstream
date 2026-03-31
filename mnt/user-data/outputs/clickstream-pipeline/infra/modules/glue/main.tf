##############################################################################
# modules/glue/main.tf
# Glue catalog database + S3 crawler + Athena workgroup
##############################################################################

locals {
  db_name = "${var.project}_${var.environment}_events"
}

# ── Glue Catalog Database ────────────────────────────────────────────────────

resource "aws_glue_catalog_database" "this" {
  name        = local.db_name
  description = "Clickstream events catalog for ${var.environment} — queried via Athena"
}

# ── IAM role for the Glue Crawler ────────────────────────────────────────────

resource "aws_iam_role" "crawler" {
  name = "${var.project}-${var.environment}-glue-crawler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "crawler_s3" {
  role = aws_iam_role.crawler.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3ReadProcessed"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.processed_bucket_id}",
          "arn:aws:s3:::${var.processed_bucket_id}/*"
        ]
      },
      {
        Sid    = "GlueLogging"
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws-glue/*"
      }
    ]
  })
}

# ── Glue Crawler ─────────────────────────────────────────────────────────────

resource "aws_glue_crawler" "processed" {
  name          = "${var.project}-${var.environment}-processed-events"
  role          = aws_iam_role.crawler.arn
  database_name = aws_glue_catalog_database.this.name
  description   = "Discovers schema and partitions for processed clickstream events"
  schedule      = "cron(0 2 * * ? *)"   # 02:00 UTC daily

  s3_target {
    path = "s3://${var.processed_bucket_id}/${var.processed_prefix}"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  # Hive-compatible partition discovery
  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
    }
    Grouping = {
      TableGroupingPolicy     = "CombineCompatibleSchemas"
      TableLevelConfiguration = 3   # event_type/year/month
    }
  })

  tags = var.tags
}

# ── Athena Workgroup ──────────────────────────────────────────────────────────

resource "aws_s3_bucket" "athena_results" {
  bucket        = "${var.project}-${var.environment}-athena-results-${random_id.suffix.hex}"
  force_destroy = var.environment != "prod"
  tags          = merge(var.tags, { Name = "Athena query results" })
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket_public_access_block" "athena_results" {
  bucket                  = aws_s3_bucket.athena_results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id
  rule {
    id     = "expire-results"
    status = "Enabled"
    filter { prefix = "" }
    expiration { days = 30 }
  }
}

resource "aws_athena_workgroup" "this" {
  name        = "${var.project}-${var.environment}"
  description = "Clickstream analytics — ${var.environment}"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.id}/results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }

    # Cost guard: 1 GB scan limit per query in dev/staging, 10 GB in prod
    bytes_scanned_cutoff_per_query = var.environment == "prod" ? 10737418240 : 1073741824
  }

  tags = var.tags
}
