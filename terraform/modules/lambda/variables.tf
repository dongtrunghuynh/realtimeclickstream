variable "env"                    { type = string }
variable "kinesis_stream_arn"     { type = string }
variable "dynamodb_table_name"    { type = string }
variable "dynamodb_table_arn"     { type = string }
variable "s3_bucket"              { type = string }
variable "s3_bucket_arn"          { type = string }
variable "aws_region"             { type = string }

variable "lambda_memory_mb" {
  type    = number
  default = 512
}

variable "lambda_timeout_seconds" {
  type    = number
  default = 60
}

variable "kinesis_batch_size" {
  type    = number
  default = 100
}
