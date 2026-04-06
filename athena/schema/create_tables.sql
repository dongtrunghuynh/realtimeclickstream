-- =============================================================================
-- Athena Table Definitions — Clickstream Pipeline
-- =============================================================================
-- Run this file once after deploying infrastructure to register all tables.
-- Execute via: bash scripts/athena_setup.sh
-- OR manually paste into the Athena query editor.
--
-- Replace YOUR_ACCOUNT_ID with your AWS account ID everywhere below,
-- or use the athena_setup.sh script which does this automatically.
-- =============================================================================

-- ─── 1. Raw Events ──────────────────────────────────────────────────────────
-- Written by the Lambda sessionizer as NDJSON.
-- Covers ALL events including late arrivals.

CREATE EXTERNAL TABLE IF NOT EXISTS clickstream_dev.raw_events (
    event_id                    STRING,
    event_time                  STRING,
    arrival_time                STRING,
    event_type                  STRING,
    product_id                  STRING,
    category_id                 STRING,
    category_code               STRING,
    brand                       STRING,
    price                       DOUBLE,
    user_id                     STRING,
    session_id                  STRING,
    is_late_arrival             BOOLEAN,
    late_arrival_delay_seconds  BIGINT
)
PARTITIONED BY (
    year  INT,
    month INT,
    day   INT,
    hour  INT
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES ('ignore.malformed.json' = 'true')
LOCATION 's3://clickstream-raw-YOUR_ACCOUNT_ID-dev/events/'
TBLPROPERTIES (
    'projection.enabled'            = 'true',
    'projection.year.type'          = 'integer',
    'projection.year.range'         = '2024,2030',
    'projection.month.type'         = 'integer',
    'projection.month.range'        = '1,12',
    'projection.day.type'           = 'integer',
    'projection.day.range'          = '1,31',
    'projection.hour.type'          = 'integer',
    'projection.hour.range'         = '0,23',
    'storage.location.template'     = 's3://clickstream-raw-YOUR_ACCOUNT_ID-dev/events/year=${year}/month=${month}/day=${day}/hour=${hour}/'
);

-- ─── 2. Late Arrivals ───────────────────────────────────────────────────────
-- Subset of raw events where is_late_arrival = TRUE.
-- Written by Lambda to a separate S3 prefix for easy Spark consumption.

CREATE EXTERNAL TABLE IF NOT EXISTS clickstream_dev.late_arrivals (
    event_id                    STRING,
    event_time                  STRING,
    arrival_time                STRING,
    event_type                  STRING,
    product_id                  STRING,
    category_id                 STRING,
    category_code               STRING,
    brand                       STRING,
    price                       DOUBLE,
    user_id                     STRING,
    session_id                  STRING,
    is_late_arrival             BOOLEAN,
    late_arrival_delay_seconds  BIGINT
)
PARTITIONED BY (year INT, month INT, day INT, hour INT)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES ('ignore.malformed.json' = 'true')
LOCATION 's3://clickstream-raw-YOUR_ACCOUNT_ID-dev/late-arrivals/'
TBLPROPERTIES (
    'projection.enabled'        = 'true',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '2024,2030',
    'projection.month.type'     = 'integer',
    'projection.month.range'    = '1,12',
    'projection.day.type'       = 'integer',
    'projection.day.range'      = '1,31',
    'projection.hour.type'      = 'integer',
    'projection.hour.range'     = '0,23',
    'storage.location.template' = 's3://clickstream-raw-YOUR_ACCOUNT_ID-dev/late-arrivals/year=${year}/month=${month}/day=${day}/hour=${hour}/'
);

-- ─── 3. Batch Sessions ──────────────────────────────────────────────────────
-- Written by the Spark batch reconciler (session_stitcher.py).
-- These are the "correct" sessions after including late arrivals.

CREATE EXTERNAL TABLE IF NOT EXISTS clickstream_dev.batch_sessions (
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
    'parquet.compress'          = 'SNAPPY',
    'projection.enabled'        = 'true',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '2024,2030',
    'projection.month.type'     = 'integer',
    'projection.month.range'    = '1,12',
    'projection.day.type'       = 'integer',
    'projection.day.range'      = '1,31',
    'storage.location.template' = 's3://clickstream-corrected-YOUR_ACCOUNT_ID-dev/sessions/year=${year}/month=${month}/day=${day}/'
);

-- ─── 4. Real-Time Sessions Snapshot ─────────────────────────────────────────
-- DynamoDB session state exported to S3 by export_dynamodb_snapshot.sh.
-- Used to compare speed layer vs batch layer in the dashboard.

CREATE EXTERNAL TABLE IF NOT EXISTS clickstream_dev.realtime_sessions_raw (
    session_id          STRING,
    event_count         STRING,
    cart_total          STRING,
    conversion_value    STRING,
    converted           STRING,
    session_start       STRING,
    last_event_time     STRING,
    duration_seconds    STRING,
    user_id             STRING
)
PARTITIONED BY (date_partition STRING)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES ('ignore.malformed.json' = 'true')
LOCATION 's3://clickstream-raw-YOUR_ACCOUNT_ID-dev/realtime-sessions/'
TBLPROPERTIES (
    'projection.enabled'                    = 'true',
    'projection.date_partition.type'        = 'date',
    'projection.date_partition.format'      = 'yyyy-MM-dd',
    'projection.date_partition.range'       = '2024-01-01,NOW',
    'projection.date_partition.interval'    = '1',
    'projection.date_partition.interval.unit' = 'DAYS',
    'storage.location.template'             = 's3://clickstream-raw-YOUR_ACCOUNT_ID-dev/realtime-sessions/date_partition=${date_partition}/'
);

-- ─── 5. Restatement Audit ───────────────────────────────────────────────────
-- Written by the Spark late arrival handler (late_arrival_handler.py).
-- Per-session delta between speed and batch layers.

CREATE EXTERNAL TABLE IF NOT EXISTS clickstream_dev.restatement_audit (
    session_id              STRING,
    batch_session_id        STRING,
    rt_cart_total           DOUBLE,
    batch_cart_total        DOUBLE,
    cart_total_delta        DOUBLE,
    cart_total_abs_delta    DOUBLE,
    rt_event_count          BIGINT,
    batch_event_count       BIGINT,
    event_count_delta       BIGINT,
    rt_converted            BOOLEAN,
    batch_converted         BOOLEAN,
    conversion_flipped      BOOLEAN,
    had_restatement         BOOLEAN,
    late_arrival_count      BIGINT,
    restatement_type        STRING
)
PARTITIONED BY (year INT, month INT, day INT)
STORED AS PARQUET
LOCATION 's3://clickstream-corrected-YOUR_ACCOUNT_ID-dev/restatement-audit/'
TBLPROPERTIES (
    'parquet.compress'          = 'SNAPPY',
    'projection.enabled'        = 'true',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '2024,2030',
    'projection.month.type'     = 'integer',
    'projection.month.range'    = '1,12',
    'projection.day.type'       = 'integer',
    'projection.day.range'      = '1,31',
    'storage.location.template' = 's3://clickstream-corrected-YOUR_ACCOUNT_ID-dev/restatement-audit/year=${year}/month=${month}/day=${day}/'
);

-- ─── Useful ad-hoc queries ───────────────────────────────────────────────────

-- Late arrival rate by hour
-- SELECT hour, COUNT(*) as total_events,
--        SUM(CAST(is_late_arrival AS INT)) as late_count,
--        ROUND(SUM(CAST(is_late_arrival AS INT)) * 100.0 / COUNT(*), 2) as late_pct
-- FROM clickstream_dev.raw_events
-- WHERE year=2024 AND month=10 AND day=15
-- GROUP BY hour ORDER BY hour;

-- Top restated sessions by revenue impact
-- SELECT session_id, rt_cart_total, batch_cart_total, cart_total_delta, restatement_type
-- FROM clickstream_dev.restatement_audit
-- WHERE year=2024 AND month=10 AND day=15
-- ORDER BY cart_total_abs_delta DESC LIMIT 20;
