# Dev environment — lower cost, smaller resources
# Usage: terraform apply -var-file=environments/dev.tfvars

aws_region             = "us-east-1"
lambda_memory_mb       = 512
lambda_timeout_seconds = 60
kinesis_batch_size     = 100
dynamodb_ttl_hours     = 2
