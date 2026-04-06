###############################################################################
# Glue Crawler — auto-discovers S3 partitions and updates Athena table schemas
#
# Why needed:
#   Athena uses partition projection (defined in create_tables.sql) which handles
#   date partitions automatically. However, if you add new columns or change the
#   schema, you need a Glue crawler to re-infer and update the table definition.
#
#   For this project: run the crawler after Week 4 (Spark job produces Parquet)
#   to update the batch_sessions table from NDJSON schema to Parquet schema.
#
# Run manually:
#   aws glue start-crawler --name clickstream-raw-events-crawler-dev
#   aws glue start-crawler --name clickstream-batch-sessions-crawler-dev
###############################################################################

# ─── Raw Events Crawler ───────────────────────────────────────────────────────

resource "aws_glue_crawler" "raw_events" {
  name          = "clickstream-raw-events-crawler-${var.env}"
  database_name = aws_glue_catalog_database.clickstream.name
  role          = aws_iam_role.glue_crawler.arn
  description   = "Crawls raw NDJSON events written by Lambda sessionizer"

  # Only run when explicitly triggered — not on a schedule (cost control)
  schedule = null

  s3_target {
    path = "s3://${aws_s3_bucket.raw_events.bucket}/events/"
    exclusions = ["**/_temporary/**", "**/.temporary/**"]
  }

  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
      Tables     = { AddOrUpdateBehavior = "MergeNewColumns" }
    }
    Grouping = {
      TableGroupingPolicy = "CombineCompatibleSchemas"
    }
  })

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  tags = { Name = "clickstream-raw-events-crawler-${var.env}", Env = var.env }
}

# ─── Batch Sessions Crawler ───────────────────────────────────────────────────

resource "aws_glue_crawler" "batch_sessions" {
  name          = "clickstream-batch-sessions-crawler-${var.env}"
  database_name = aws_glue_catalog_database.clickstream.name
  role          = aws_iam_role.glue_crawler.arn
  description   = "Crawls Parquet sessions written by Spark batch reconciler"

  schedule = null

  s3_target {
    path = "s3://${aws_s3_bucket.corrected_sessions.bucket}/sessions/"
    exclusions = ["**/_temporary/**", "**/.temporary/**"]
  }

  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
      Tables     = { AddOrUpdateBehavior = "MergeNewColumns" }
    }
  })

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  tags = { Name = "clickstream-batch-sessions-crawler-${var.env}", Env = var.env }
}

# ─── IAM Role for Glue Crawlers ──────────────────────────────────────────────

data "aws_iam_policy_document" "glue_crawler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue_crawler" {
  name               = "clickstream-glue-crawler-${var.env}"
  assume_role_policy = data.aws_iam_policy_document.glue_crawler_assume.json
}

data "aws_iam_policy_document" "glue_crawler_permissions" {
  # S3 read access for crawling
  statement {
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.raw_events.arn,
      "${aws_s3_bucket.raw_events.arn}/*",
      aws_s3_bucket.corrected_sessions.arn,
      "${aws_s3_bucket.corrected_sessions.arn}/*",
    ]
  }

  # Glue Data Catalog write access
  statement {
    actions = [
      "glue:GetDatabase", "glue:GetTable", "glue:CreateTable",
      "glue:UpdateTable", "glue:GetPartition", "glue:CreatePartition",
      "glue:BatchCreatePartition", "glue:GetPartitions",
    ]
    resources = ["*"]
  }

  # CloudWatch logs for crawler run output
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:*:log-group:/aws-glue/*"]
  }
}

resource "aws_iam_role_policy" "glue_crawler" {
  name   = "clickstream-glue-crawler-policy-${var.env}"
  role   = aws_iam_role.glue_crawler.id
  policy = data.aws_iam_policy_document.glue_crawler_permissions.json
}

# Outputs
output "raw_events_crawler_name" {
  value = aws_glue_crawler.raw_events.name
}

output "batch_sessions_crawler_name" {
  value = aws_glue_crawler.batch_sessions.name
}
