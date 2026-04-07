terraform {
  backend "s3" {
    bucket  = "real-time-streaming-1"
    key     = "clickstream-pipeline/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}
