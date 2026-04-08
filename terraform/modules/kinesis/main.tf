###############################################################################
# Kinesis Data Stream Module
#
# Uses ON_DEMAND mode — no shard management, auto-scales, charges per GB.
# ~$0.08/GB ingested. Turns off automatically when no producers are active.
###############################################################################

resource "aws_kinesis_stream" "clickstream" {
  name = var.stream_name

  # ON_DEMAND: no shard count needed, scales automatically
  # Cost: ~$0.08/GB ingested vs ~$0.36/day/shard for provisioned
  stream_mode_details {
    stream_mode = "ON_DEMAND"
  }

  # Retain records for 24 hours (free tier is 24h, extended is $0.02/shard-hour)
  retention_period = 24

  # Server-side encryption with AWS managed key (free)
  encryption_type = "KMS"
  kms_key_id      = "alias/aws/kinesis"

  tags = {
    Name = var.stream_name
    Env  = var.env
  }
}

output "stream_name" {
  value = aws_kinesis_stream.clickstream.name
}

output "stream_arn" {
  value = aws_kinesis_stream.clickstream.arn
}
