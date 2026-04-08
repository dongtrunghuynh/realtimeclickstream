# Prod environment — production-grade settings
# Usage: terraform apply -var-file=environments/prod.tfvars

aws_region             = "us-east-1"
lambda_memory_mb       = 1024
lambda_timeout_seconds = 120
kinesis_batch_size     = 500
dynamodb_ttl_hours     = 4
