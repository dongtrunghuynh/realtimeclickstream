###############################################################################
# Lambda Module — Sessionizer function + Kinesis event source mapping
###############################################################################

locals {
  function_name = "clickstream-sessionizer-${var.env}"
  lambda_zip    = "${path.root}/../src/lambda/sessionizer.zip"
}

# ---------------------------------------------------------------------------
# IAM Role
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_permissions" {
  # CloudWatch Logs
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:*:log-group:/aws/lambda/${local.function_name}:*"]
  }

  # Kinesis — read from stream
  statement {
    actions = [
      "kinesis:GetRecords",
      "kinesis:GetShardIterator",
      "kinesis:DescribeStream",
      "kinesis:DescribeStreamSummary",
      "kinesis:ListShards",
      "kinesis:ListStreams",
    ]
    resources = [var.kinesis_stream_arn]
  }

  # DynamoDB — read/write session state
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
    ]
    resources = [
      var.dynamodb_table_arn,
      "${var.dynamodb_table_arn}/index/*",
    ]
  }

  # S3 — write raw events
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${var.s3_bucket_arn}/*"]
  }

  # SQS — send failed records to DLQ
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.lambda_dlq.arn]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${local.function_name}-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

# ---------------------------------------------------------------------------
# CloudWatch Log Group (explicit so Terraform can delete it)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 7  # Keep logs 7 days in dev (cost control)
}

# ---------------------------------------------------------------------------
# Lambda Function
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "sessionizer" {
  function_name = local.function_name
  role          = aws_iam_role.lambda.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = var.lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  # TODO: Week 3 — replace with actual zip build in scripts/build_lambda.sh
  filename = local.lambda_zip

  environment {
    variables = {
      DYNAMODB_TABLE_NAME = var.dynamodb_table_name
      S3_BUCKET           = var.s3_bucket
      LOG_LEVEL           = var.env == "dev" ? "DEBUG" : "INFO"
      DLQ_URL             = aws_sqs_queue.lambda_dlq.url
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = { Name = local.function_name, Env = var.env }
}

# ---------------------------------------------------------------------------
# Kinesis Event Source Mapping
# ---------------------------------------------------------------------------

resource "aws_lambda_event_source_mapping" "kinesis" {
  event_source_arn  = var.kinesis_stream_arn
  function_name     = aws_lambda_function.sessionizer.arn
  starting_position = "LATEST"
  batch_size        = var.kinesis_batch_size

  # On error: split batch in half and retry each half separately
  # This prevents one bad record from blocking the entire shard
  bisect_batch_on_function_error = true

  # After 3 failed attempts, send failed record metadata to DLQ
  maximum_retry_attempts = 3

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.lambda_dlq.arn
    }
  }

  # Tumbling window: process records in 5-second micro-batches
  tumbling_window_in_seconds = 5
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "function_name" {
  value = aws_lambda_function.sessionizer.function_name
}

output "function_arn" {
  value = aws_lambda_function.sessionizer.arn
}

