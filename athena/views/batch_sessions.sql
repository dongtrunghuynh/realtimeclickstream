-- =============================================================================
-- Athena View: Batch Sessions (Batch Layer — Spark reconciled)
-- =============================================================================
-- Reads corrected sessions written by the Spark batch reconciler.
--
-- S3 path: s3://clickstream-corrected-<account>-<env>/sessions/
-- Format: Parquet, partitioned by year/month/day
-- Written by: src/spark/session_stitcher.py
-- =============================================================================

-- Underlying table (register once)
CREATE EXTERNAL TABLE IF NOT EXISTS "clickstream_dev"."batch_sessions" (
    batch_session_id        STRING,
    user_id                 STRING,
    session_start           TIMESTAMP,
    session_end             TIMESTAMP,
    event_count             BIGINT,
    cart_total              DOUBLE,
    conversion_value        DOUBLE,
    converted               BOOLEAN,
    duration_seconds        BIGINT,
    late_arrival_count      BIGINT,
    had_restatement         BOOLEAN,
    original_session_ids    ARRAY<STRING>
)
PARTITIONED BY (year INT, month INT, day INT)
STORED AS PARQUET
LOCATION 's3://clickstream-corrected-YOUR_ACCOUNT_ID-dev/sessions/'
TBLPROPERTIES (
    'parquet.compress'      = 'SNAPPY',
    'projection.enabled'    = 'true',
    'projection.year.type'  = 'integer',
    'projection.year.range' = '2024,2030',
    'projection.month.type' = 'integer',
    'projection.month.range'= '1,12',
    'projection.day.type'   = 'integer',
    'projection.day.range'  = '1,31',
    'storage.location.template' = 's3://clickstream-corrected-YOUR_ACCOUNT_ID-dev/sessions/year=${year}/month=${month}/day=${day}/'
)
;

-- View (for easier querying)
CREATE OR REPLACE VIEW batch_sessions_v AS
SELECT
    batch_session_id,
    user_id,
    session_start,
    session_end,
    event_count,
    ROUND(cart_total, 2)            AS cart_total,
    ROUND(conversion_value, 2)      AS conversion_value,
    converted,
    duration_seconds,
    late_arrival_count,
    had_restatement,
    original_session_ids,
    year, month, day,
    DATE(DATE_PARSE(
        LPAD(CAST(year AS VARCHAR), 4, '0') || '-' ||
        LPAD(CAST(month AS VARCHAR), 2, '0') || '-' ||
        LPAD(CAST(day AS VARCHAR), 2, '0'),
        '%Y-%m-%d'
    )) AS session_date
FROM "clickstream_dev"."batch_sessions"
;
