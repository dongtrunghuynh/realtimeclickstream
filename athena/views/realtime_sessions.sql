-- =============================================================================
-- Athena View: Real-Time Sessions (Speed Layer)
-- =============================================================================
-- Reads session state that was exported from DynamoDB to S3.
--
-- NOTE: DynamoDB does not natively support Athena queries. To compare speed
-- vs batch layer, you must export or stream DynamoDB data to S3 first.
--
-- Two options (choose one):
--   Option A: DynamoDB Export to S3 (built-in feature, ~2hr delay)
--             aws dynamodb export-table-to-point-in-time \
--               --table-arn <arn> --s3-bucket <bucket> --s3-prefix dynamodb-export/
--
--   Option B: Lambda writes a nightly snapshot to S3 (simpler for this project)
--             See scripts/export_dynamodb_snapshot.sh
--
-- This view assumes Option B — Lambda-written NDJSON files at:
--   s3://clickstream-raw-<account>-<env>/realtime-sessions/date_partition=YYYY-MM-DD/
-- =============================================================================

CREATE OR REPLACE VIEW realtime_sessions AS
SELECT
    session_id,
    CAST(event_count AS BIGINT)          AS event_count,
    CAST(cart_total AS DOUBLE)           AS cart_total,
    CAST(conversion_value AS DOUBLE)     AS conversion_value,
    CAST(converted AS BOOLEAN)           AS converted,
    session_start,
    last_event_time                      AS session_end,
    CAST(duration_seconds AS DOUBLE)     AS duration_seconds,
    date_partition                       AS date_partition
FROM "clickstream_dev"."realtime_sessions_raw"
WHERE date_partition IS NOT NULL
;

-- =============================================================================
-- Underlying table definition (run this once to register the raw S3 data)
-- =============================================================================

CREATE EXTERNAL TABLE IF NOT EXISTS "clickstream_dev"."realtime_sessions_raw" (
    session_id          STRING,
    event_count         STRING,
    cart_total          STRING,
    conversion_value    STRING,
    converted           STRING,
    session_start       STRING,
    last_event_time     STRING,
    duration_seconds    STRING
)
PARTITIONED BY (date_partition STRING)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://clickstream-raw-YOUR_ACCOUNT_ID-dev/realtime-sessions/'
TBLPROPERTIES (
    'has_encrypted_data' = 'false',
    'projection.enabled' = 'true',
    'projection.date_partition.type' = 'date',
    'projection.date_partition.format' = 'yyyy-MM-dd',
    'projection.date_partition.range' = '2024-01-01,NOW',
    'projection.date_partition.interval' = '1',
    'projection.date_partition.interval.unit' = 'DAYS',
    'storage.location.template' = 's3://clickstream-raw-YOUR_ACCOUNT_ID-dev/realtime-sessions/date_partition=${date_partition}/'
)
;
