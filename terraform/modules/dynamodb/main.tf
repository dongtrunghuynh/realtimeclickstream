###############################################################################
# DynamoDB Module — Single-Table Design for Session State
#
# Schema:
#   PK: session_id (String)
#   Attributes: user_id, event_count, cart_total, converted, session_start,
#               last_event_time, expires_at (TTL), event_types_seen
#
# GSI: user_id-index for querying all sessions for a user
# TTL: expires_at auto-deletes sessions after 2h — keeps costs in free tier
###############################################################################

resource "aws_dynamodb_table" "sessions" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST" # On-demand — free tier for <25GB + <200M requests/month
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  # TTL — DynamoDB auto-deletes items when expires_at < current Unix epoch
  # This keeps the table small and costs near $0
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  # GSI: query all sessions for a user (for user-level analytics)
  global_secondary_index {
    name            = "user_id-index"
    hash_key        = "user_id"
    projection_type = "ALL"
  }

  # Point-in-time recovery (PITR) — free, good practice
  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = var.table_name
    Env  = var.env
  }
}

output "table_name" {
  value = aws_dynamodb_table.sessions.name
}

output "table_arn" {
  value = aws_dynamodb_table.sessions.arn
}
