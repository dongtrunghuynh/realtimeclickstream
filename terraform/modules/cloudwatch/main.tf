###############################################################################
# CloudWatch Dashboard — Operational visibility for the clickstream pipeline
#
# View in AWS Console:
#   CloudWatch → Dashboards → clickstream-pipeline-<env>
#
# Panels:
#   Row 1: Lambda — invocations, errors, duration, throttles
#   Row 2: Kinesis — incoming records, iterator age (lag indicator)
#   Row 3: DynamoDB — write/read capacity, throttles
#   Row 4: Custom simulator metrics — throughput, late arrivals
###############################################################################

locals {
  dashboard_name     = "clickstream-pipeline-${var.env}"
  lambda_fn          = var.lambda_function_name
  kinesis_stream     = var.kinesis_stream_name
  dynamodb_table     = var.dynamodb_table_name
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.dashboard_name

  dashboard_body = jsonencode({
    widgets = [

      # ── Row 1 title ───────────────────────────────────────────────────────
      {
        type   = "text"
        x      = 0; y = 0; width = 24; height = 1
        properties = { markdown = "## Lambda Sessionizer" }
      },

      # Lambda — Invocations
      {
        type = "metric"; x = 0; y = 1; width = 6; height = 6
        properties = {
          title   = "Invocations"
          metrics = [["AWS/Lambda", "Invocations", "FunctionName", local.lambda_fn, { stat = "Sum", period = 60 }]]
          view    = "timeSeries"; stacked = false
          period  = 60; stat = "Sum"
        }
      },

      # Lambda — Errors
      {
        type = "metric"; x = 6; y = 1; width = 6; height = 6
        properties = {
          title   = "Errors"
          metrics = [
            ["AWS/Lambda", "Errors",   "FunctionName", local.lambda_fn, { stat = "Sum",   color = "#d62728" }],
            ["AWS/Lambda", "Throttles","FunctionName", local.lambda_fn, { stat = "Sum",   color = "#ff7f0e" }],
          ]
          view    = "timeSeries"; stacked = false; period = 60
        }
      },

      # Lambda — Duration p50/p99
      {
        type = "metric"; x = 12; y = 1; width = 6; height = 6
        properties = {
          title   = "Duration (ms)"
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", local.lambda_fn, { stat = "p50", label = "p50" }],
            ["AWS/Lambda", "Duration", "FunctionName", local.lambda_fn, { stat = "p99", label = "p99", color = "#d62728" }],
          ]
          view    = "timeSeries"; stacked = false; period = 60
        }
      },

      # Lambda — Concurrent executions
      {
        type = "metric"; x = 18; y = 1; width = 6; height = 6
        properties = {
          title   = "Concurrent Executions"
          metrics = [["AWS/Lambda", "ConcurrentExecutions", "FunctionName", local.lambda_fn, { stat = "Maximum" }]]
          view    = "timeSeries"; stacked = false; period = 60
        }
      },

      # ── Row 2 title ───────────────────────────────────────────────────────
      {
        type   = "text"
        x      = 0; y = 7; width = 24; height = 1
        properties = { markdown = "## Kinesis Data Stream — Iterator Age is the key latency metric" }
      },

      # Kinesis — Incoming Records
      {
        type = "metric"; x = 0; y = 8; width = 8; height = 6
        properties = {
          title   = "Incoming Records/sec"
          metrics = [["AWS/Kinesis", "IncomingRecords", "StreamName", local.kinesis_stream, { stat = "Sum", period = 60 }]]
          view    = "timeSeries"; stacked = false; period = 60
        }
      },

      # Kinesis — Iterator Age (latency between produce and consume)
      {
        type = "metric"; x = 8; y = 8; width = 8; height = 6
        properties = {
          title   = "GetRecords.IteratorAgeMilliseconds (Lambda lag)"
          metrics = [
            ["AWS/Kinesis", "GetRecords.IteratorAgeMilliseconds", "StreamName", local.kinesis_stream, { stat = "Maximum", color = "#d62728", label = "Max lag (ms)" }],
            ["AWS/Kinesis", "GetRecords.IteratorAgeMilliseconds", "StreamName", local.kinesis_stream, { stat = "Average", label = "Avg lag (ms)" }],
          ]
          view    = "timeSeries"; stacked = false; period = 60
          annotations = {
            horizontal = [{ value = 30000, label = "30s — acceptable", color = "#2ca02c" }]
          }
        }
      },

      # Kinesis — Incoming Bytes
      {
        type = "metric"; x = 16; y = 8; width = 8; height = 6
        properties = {
          title   = "Incoming Bytes/sec"
          metrics = [["AWS/Kinesis", "IncomingBytes", "StreamName", local.kinesis_stream, { stat = "Sum", period = 60 }]]
          view    = "timeSeries"; stacked = false; period = 60
        }
      },

      # ── Row 3 title ───────────────────────────────────────────────────────
      {
        type   = "text"
        x      = 0; y = 14; width = 24; height = 1
        properties = { markdown = "## DynamoDB — Session State (Speed Layer)" }
      },

      # DynamoDB — Write latency
      {
        type = "metric"; x = 0; y = 15; width = 8; height = 6
        properties = {
          title   = "Write Latency (ms)"
          metrics = [
            ["AWS/DynamoDB", "SuccessfulRequestLatency", "TableName", local.dynamodb_table, "Operation", "PutItem",    { stat = "p99", label = "PutItem p99" }],
            ["AWS/DynamoDB", "SuccessfulRequestLatency", "TableName", local.dynamodb_table, "Operation", "UpdateItem", { stat = "p99", label = "UpdateItem p99" }],
          ]
          view    = "timeSeries"; stacked = false; period = 60
        }
      },

      # DynamoDB — Throttled requests
      {
        type = "metric"; x = 8; y = 15; width = 8; height = 6
        properties = {
          title   = "Throttled Requests"
          metrics = [
            ["AWS/DynamoDB", "ThrottledRequests", "TableName", local.dynamodb_table, "Operation", "PutItem",    { stat = "Sum", color = "#d62728" }],
            ["AWS/DynamoDB", "ThrottledRequests", "TableName", local.dynamodb_table, "Operation", "GetItem",    { stat = "Sum", color = "#ff7f0e" }],
          ]
          view    = "timeSeries"; stacked = false; period = 60
        }
      },

      # DynamoDB — System errors
      {
        type = "metric"; x = 16; y = 15; width = 8; height = 6
        properties = {
          title   = "System Errors"
          metrics = [["AWS/DynamoDB", "SystemErrors", "TableName", local.dynamodb_table, { stat = "Sum", color = "#d62728" }]]
          view    = "timeSeries"; stacked = false; period = 60
        }
      },

      # ── Row 4 title ───────────────────────────────────────────────────────
      {
        type   = "text"
        x      = 0; y = 21; width = 24; height = 1
        properties = { markdown = "## Simulator — Custom Metrics (published by src/event_simulator/metrics.py)" }
      },

      # Simulator — Throughput
      {
        type = "metric"; x = 0; y = 22; width = 8; height = 6
        properties = {
          title   = "Events Sent/sec"
          metrics = [["ClickstreamPipeline/Simulator", "ThroughputPerSecond", "StreamName", local.kinesis_stream, { stat = "Average" }]]
          view    = "timeSeries"; stacked = false; period = 30
        }
      },

      # Simulator — Late arrivals pending
      {
        type = "metric"; x = 8; y = 22; width = 8; height = 6
        properties = {
          title   = "Late Arrivals Pending (held by injector)"
          metrics = [["ClickstreamPipeline/Simulator", "LateArrivalsPending", "StreamName", local.kinesis_stream, { stat = "Maximum" }]]
          view    = "timeSeries"; stacked = false; period = 30
        }
      },

      # Simulator — Failed records
      {
        type = "metric"; x = 16; y = 22; width = 8; height = 6
        properties = {
          title   = "Failed Kinesis Records"
          metrics = [["ClickstreamPipeline/Simulator", "EventsFailedTotal", "StreamName", local.kinesis_stream, { stat = "Sum", color = "#d62728" }]]
          view    = "timeSeries"; stacked = false; period = 60
        }
      },

    ]
  })
}

# CloudWatch Alarm — Lambda error rate > 5%
resource "aws_cloudwatch_metric_alarm" "lambda_error_rate" {
  alarm_name          = "clickstream-lambda-error-rate-${var.env}"
  alarm_description   = "Lambda error rate exceeded 5% over 5 minutes"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  threshold           = 5

  metric_query {
    id          = "error_rate"
    expression  = "errors / invocations * 100"
    label       = "Error Rate (%)"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Errors"
      dimensions  = { FunctionName = local.lambda_fn }
      period      = 60
      stat        = "Sum"
    }
  }

  metric_query {
    id = "invocations"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Invocations"
      dimensions  = { FunctionName = local.lambda_fn }
      period      = 60
      stat        = "Sum"
    }
  }

  treat_missing_data = "notBreaching"

  tags = { Name = "clickstream-lambda-errors-${var.env}", Env = var.env }
}

# CloudWatch Alarm — Kinesis iterator age > 60 seconds (Lambda falling behind)
resource "aws_cloudwatch_metric_alarm" "kinesis_lag" {
  alarm_name          = "clickstream-kinesis-lag-${var.env}"
  alarm_description   = "Lambda is >60s behind Kinesis — possible backlog"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  threshold           = 60000   # 60 seconds in ms
  namespace           = "AWS/Kinesis"
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  dimensions          = { StreamName = local.kinesis_stream }
  period              = 60
  statistic           = "Maximum"
  treat_missing_data  = "notBreaching"

  tags = { Name = "clickstream-kinesis-lag-${var.env}", Env = var.env }
}

output "dashboard_url" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${local.dashboard_name}"
}
