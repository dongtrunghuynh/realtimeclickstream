"""
Lambda shared utilities package.

Used by:
  - sessionizer/handler.py  (DynamoDB client, S3 writer, log helpers)

In production this would be deployed as a Lambda Layer so the code is shared
across multiple functions without duplicating it in each zip.

For this project, shared/ is copied directly into the Lambda zip.
See scripts/build_lambda.sh.
"""
