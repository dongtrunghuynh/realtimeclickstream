##############################################################################
# modules/monitoring/main.tf
# DLQ · SNS topic · CloudWatch alarms · unified observability dashboard
##############################################################################

locals {
  prefix = "${var.project}-${var.environment}"
}

# ── Dead-Letter Queue ─────────────────────────────────────────────────────────

resource "aws_sqs_queue" "dlq" {
  name                       = "${local.prefix}-stream-processor-dlq"
  message_retention_seconds  = 1209600   # 14 days
  visibility_timeout_seconds = 300

  tags = merge(var.tags, { Purpose = "Lambda DLQ for failed Kinesis batches" })
}

resource "aws_sqs_queue_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowLambdaDLQ"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.dlq.arn
      Condition = { ArnLike = { "aws:SourceArn" = "arn:aws:lambda:${var.aws_region}:*:function:${local.prefix}-*" } }
    }]
  })
}

# ── SNS for alarm notifications ───────────────────────────────────────────────

resource "aws_sns_topic" "alarms" {
  name = "${local.prefix}-pipeline-alarms"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ── CloudWatch Alarms ─────────────────────────────────────────────────────────

# 1. Lambda errors exceed threshold
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.prefix}-lambda-errors"
  alarm_description   = "Stream processor Lambda errors exceed threshold — check DLQ"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = var.lambda_function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# 2. Lambda duration approaching timeout (>80% of configured timeout)
resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  alarm_name          = "${local.prefix}-lambda-duration-high"
  alarm_description   = "Lambda p95 duration is >80% of timeout — risk of timeouts"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = var.lambda_function_name }
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  threshold           = var.lambda_timeout_ms * 0.8
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# 3. DLQ has messages — means events are being permanently failed
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${local.prefix}-dlq-not-empty"
  alarm_description   = "DLQ has messages — events are failing permanently. Investigate immediately."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# 4. Kinesis IteratorAgeMilliseconds — data freshness SLA
resource "aws_cloudwatch_metric_alarm" "iterator_age" {
  alarm_name          = "${local.prefix}-kinesis-iterator-age"
  alarm_description   = "Kinesis iterator age >5 min — Lambda is falling behind the stream"
  namespace           = "AWS/Kinesis"
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  dimensions          = { StreamName = var.kinesis_stream_name }
  extended_statistic  = "p99"
  period              = 60
  evaluation_periods  = 5
  threshold           = 300000   # 5 minutes in ms
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# 5. Lambda throttles
resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  alarm_name          = "${local.prefix}-lambda-throttles"
  alarm_description   = "Lambda is being throttled — increase reserved concurrency"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = var.lambda_function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# ── CloudWatch Dashboard ──────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "pipeline" {
  dashboard_name = "${local.prefix}-pipeline"

  dashboard_body = jsonencode({
    widgets = [
      # Row 1: Title
      {
        type   = "text"
        x = 0; y = 0; width = 24; height = 2
        properties = {
          markdown = "# ${upper(var.project)} Clickstream Pipeline — ${upper(var.environment)}\nReal-time event processing: Kinesis → Lambda → S3 → Athena"
        }
      },
      # Row 2: Lambda invocations & errors side by side
      {
        type   = "metric"
        x = 0; y = 2; width = 12; height = 6
        properties = {
          title  = "Lambda Invocations vs Errors"
          view   = "timeSeries"
          period = 60
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.lambda_function_name, { stat = "Sum", color = "#2ca02c" }],
            ["AWS/Lambda", "Errors",      "FunctionName", var.lambda_function_name, { stat = "Sum", color = "#d62728" }]
          ]
        }
      },
      {
        type   = "metric"
        x = 12; y = 2; width = 12; height = 6
        properties = {
          title  = "Lambda Duration (p50 / p95 / p99)"
          view   = "timeSeries"
          period = 60
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", var.lambda_function_name, { stat = "p50",  label = "p50",  color = "#1f77b4" }],
            ["AWS/Lambda", "Duration", "FunctionName", var.lambda_function_name, { stat = "p95",  label = "p95",  color = "#ff7f0e" }],
            ["AWS/Lambda", "Duration", "FunctionName", var.lambda_function_name, { stat = "p99",  label = "p99",  color = "#d62728" }]
          ]
        }
      },
      # Row 3: Kinesis
      {
        type   = "metric"
        x = 0; y = 8; width = 12; height = 6
        properties = {
          title  = "Kinesis Iterator Age (data freshness)"
          view   = "timeSeries"
          period = 60
          annotations = {
            horizontal = [{ label = "5-min SLA", value = 300000, color = "#d62728" }]
          }
          metrics = [
            ["AWS/Kinesis", "GetRecords.IteratorAgeMilliseconds", "StreamName", var.kinesis_stream_name, { stat = "p99", label = "p99 age (ms)" }]
          ]
        }
      },
      {
        type   = "metric"
        x = 12; y = 8; width = 12; height = 6
        properties = {
          title  = "Kinesis Incoming Records/sec"
          view   = "timeSeries"
          period = 60
          metrics = [
            ["AWS/Kinesis", "IncomingRecords", "StreamName", var.kinesis_stream_name, { stat = "Sum", label = "Records/min" }]
          ]
        }
      },
      # Row 4: DLQ health
      {
        type   = "metric"
        x = 0; y = 14; width = 12; height = 6
        properties = {
          title  = "DLQ Depth (should be 0)"
          view   = "timeSeries"
          period = 60
          annotations = {
            horizontal = [{ label = "Alert threshold", value = 1, color = "#d62728" }]
          }
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.dlq.name, { stat = "Maximum", color = "#d62728" }]
          ]
        }
      },
      {
        type   = "alarm"
        x = 12; y = 14; width = 12; height = 6
        properties = {
          title  = "Alarm Status"
          alarms = [
            aws_cloudwatch_metric_alarm.lambda_errors.arn,
            aws_cloudwatch_metric_alarm.lambda_duration.arn,
            aws_cloudwatch_metric_alarm.dlq_messages.arn,
            aws_cloudwatch_metric_alarm.iterator_age.arn,
            aws_cloudwatch_metric_alarm.lambda_throttles.arn
          ]
        }
      }
    ]
  })
}
