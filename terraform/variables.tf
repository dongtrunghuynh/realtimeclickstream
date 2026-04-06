variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "kinesis_shard_count" {
  description = "Number of Kinesis shards (ignored in ON_DEMAND mode)"
  type        = number
  default     = 1
}

variable "lambda_memory_mb" {
  description = "Lambda function memory in MB"
  type        = number
  default     = 512
}

variable "lambda_timeout_seconds" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 60
}

variable "kinesis_batch_size" {
  description = "Number of Kinesis records per Lambda invocation"
  type        = number
  default     = 100
}

variable "dynamodb_ttl_hours" {
  description = "DynamoDB session TTL in hours"
  type        = number
  default     = 2
}
