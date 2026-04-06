###############################################################################
# EMR Serverless Module — Spark application for batch reconciliation
#
# Key cost-saving settings:
# - Initial capacity: 0 (no pre-warmed workers — pay only during job runs)
# - Auto-stop: 15 minutes idle (so a forgotten application costs nothing)
# - No minimum capacity: scales to 0 between jobs
###############################################################################

locals {
  app_name = "clickstream-reconciler-${var.env}"
}

# ---------------------------------------------------------------------------
# EMR Serverless Application
# ---------------------------------------------------------------------------

resource "aws_emrserverless_application" "spark" {
  name          = local.app_name
  release_label = "emr-7.0.0"
  type          = "SPARK"

  # Auto-stop: application idles for 15 minutes → stops automatically
  # This is the primary cost-control mechanism for EMR Serverless
  auto_stop_configuration {
    enabled              = true
    idle_timeout_minutes = 15
  }

  # No initial capacity — don't pre-warm workers
  # Workers spin up when a job is submitted (~30-60 seconds cold start)
  # This trades some latency for ~$0 cost between jobs

  # Maximum capacity guard — prevents runaway spending
  maximum_capacity {
    cpu    = "40 vCPU"
    memory = "80 GB"
    disk   = "200 GB"
  }

  tags = { Name = local.app_name, Env = var.env }
}

# ---------------------------------------------------------------------------
# IAM Execution Role for Spark Jobs
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "emr_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["emr-serverless.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "emr_execution" {
  name               = "${local.app_name}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.emr_assume.json
}

data "aws_iam_policy_document" "emr_permissions" {
  # S3 — read raw events, write corrected sessions
  statement {
    actions = [
      "s3:GetObject", "s3:ListBucket",
      "s3:PutObject", "s3:DeleteObject",
    ]
    resources = [
      var.s3_bucket_arn,
      "${var.s3_bucket_arn}/*",
    ]
  }

  # Glue — create/update table definitions
  statement {
    actions = [
      "glue:GetDatabase", "glue:GetTable", "glue:CreateTable",
      "glue:UpdateTable", "glue:GetPartition", "glue:CreatePartition",
      "glue:BatchCreatePartition",
    ]
    resources = ["*"]
  }

  # CloudWatch — write Spark application logs
  statement {
    actions = [
      "logs:CreateLogGroup", "logs:CreateLogStream",
      "logs:PutLogEvents", "logs:DescribeLogGroups",
    ]
    resources = ["arn:aws:logs:*:*:log-group:/aws/emr-serverless/*"]
  }
}

resource "aws_iam_role_policy" "emr_execution" {
  name   = "${local.app_name}-policy"
  role   = aws_iam_role.emr_execution.id
  policy = data.aws_iam_policy_document.emr_permissions.json
}

# ---------------------------------------------------------------------------
# CloudWatch Log Group for Spark application logs
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "emr" {
  name              = "/aws/emr-serverless/${local.app_name}"
  retention_in_days = 7
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "application_id" {
  value       = aws_emrserverless_application.spark.id
  description = "Used in scripts/submit_spark_job.sh"
}

output "execution_role_arn" {
  value       = aws_iam_role.emr_execution.arn
  description = "Pass as --execution-role-arn when submitting Spark jobs"
}
