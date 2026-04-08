###############################################################################
# Dead Letter Queue — catches Kinesis records that Lambda fails to process
# after maximum_retry_attempts.
#
# When to check the DLQ:
#   - CloudWatch alarm fires for Lambda errors
#   - Session counts diverge unexpectedly between speed and batch layers
#   - Run: python src/lambda/sessionizer/dlq_handler.py --list
###############################################################################

resource "aws_sqs_queue" "lambda_dlq" {
  name                      = "clickstream-sessionizer-dlq-${var.env}"
  message_retention_seconds = 86400 * 7 # 7 days — time to investigate failures

  # Redrive from the DLQ back to processing (optional — manual for this project)
  # redrive_allow_policy = ...

  tags = {
    Name = "clickstream-sessionizer-dlq-${var.env}"
    Env  = var.env
  }
}

# Policy that allows Lambda to send messages to the DLQ
data "aws_iam_policy_document" "dlq_send" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.lambda_dlq.arn]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_sqs_queue_policy" "lambda_dlq" {
  queue_url = aws_sqs_queue.lambda_dlq.id
  policy    = data.aws_iam_policy_document.dlq_send.json
}

# CloudWatch alarm — any DLQ message is worth investigating
resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "clickstream-dlq-not-empty-${var.env}"
  alarm_description   = "Failed Kinesis records landed in DLQ — investigate Lambda errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.lambda_dlq.name }
  period              = 300
  statistic           = "Maximum"
  treat_missing_data  = "notBreaching"

  tags = { Env = var.env }
}

output "dlq_url" {
  value       = aws_sqs_queue.lambda_dlq.url
  description = "Set as DLQ_URL env var to use src/lambda/sessionizer/dlq_handler.py"
}

output "dlq_arn" {
  value = aws_sqs_queue.lambda_dlq.arn
}
