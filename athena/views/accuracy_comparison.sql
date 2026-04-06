-- =============================================================================
-- Athena View: Accuracy / Latency Comparison
-- =============================================================================
-- The core deliverable — side-by-side comparison of speed vs batch layers.
-- Run this after both layers have data for the same date.
--
-- This query powers the dashboard in src/dashboard/accuracy_latency_dashboard.py
-- =============================================================================

-- -------------------------------------------------------
-- 1. High-level summary (one row per date)
-- -------------------------------------------------------

WITH speed_summary AS (
    SELECT
        date_partition                              AS date,
        COUNT(DISTINCT session_id)                  AS rt_total_sessions,
        SUM(cart_total)                             AS rt_total_cart_value,
        SUM(conversion_value)                       AS rt_total_revenue,
        SUM(event_count)                            AS rt_total_events,
        COUNT(DISTINCT CASE WHEN converted THEN session_id END) AS rt_converted_sessions,
        AVG(duration_seconds)                       AS rt_avg_duration_seconds
    FROM realtime_sessions
    GROUP BY date_partition
),

batch_summary AS (
    SELECT
        session_date                                AS date,
        COUNT(DISTINCT batch_session_id)            AS batch_total_sessions,
        SUM(cart_total)                             AS batch_total_cart_value,
        SUM(conversion_value)                       AS batch_total_revenue,
        SUM(event_count)                            AS batch_total_events,
        COUNT(DISTINCT CASE WHEN converted THEN batch_session_id END) AS batch_converted_sessions,
        AVG(duration_seconds)                       AS batch_avg_duration_seconds,
        SUM(CASE WHEN had_restatement THEN 1 ELSE 0 END) AS sessions_restated,
        SUM(late_arrival_count)                     AS total_late_arrivals
    FROM batch_sessions_v
    GROUP BY session_date
)

SELECT
    COALESCE(s.date, CAST(b.date AS VARCHAR))       AS date,

    -- Session counts
    s.rt_total_sessions,
    b.batch_total_sessions,
    b.batch_total_sessions - s.rt_total_sessions    AS session_count_delta,

    -- Revenue
    ROUND(s.rt_total_revenue, 2)                    AS rt_revenue,
    ROUND(b.batch_total_revenue, 2)                 AS batch_revenue,
    ROUND(b.batch_total_revenue - s.rt_total_revenue, 2) AS revenue_delta,
    ROUND(
        ABS(b.batch_total_revenue - s.rt_total_revenue)
        / NULLIF(b.batch_total_revenue, 0) * 100, 2
    )                                               AS revenue_error_pct,

    -- Conversion rates
    ROUND(s.rt_converted_sessions * 1.0 / NULLIF(s.rt_total_sessions, 0) * 100, 2) AS rt_conversion_rate_pct,
    ROUND(b.batch_converted_sessions * 1.0 / NULLIF(b.batch_total_sessions, 0) * 100, 2) AS batch_conversion_rate_pct,

    -- Session duration
    ROUND(s.rt_avg_duration_seconds, 0)             AS rt_avg_duration_seconds,
    ROUND(b.batch_avg_duration_seconds, 0)          AS batch_avg_duration_seconds,

    -- Restatement analysis (the key insight)
    b.sessions_restated,
    ROUND(b.sessions_restated * 1.0 / NULLIF(b.batch_total_sessions, 0) * 100, 2) AS pct_sessions_restated,
    b.total_late_arrivals,

    -- Latency labels (for display purposes)
    '< 30 seconds'  AS speed_layer_latency,
    '~ 8 hours'     AS batch_layer_latency

FROM speed_summary s
FULL OUTER JOIN batch_summary b ON s.date = CAST(b.date AS VARCHAR)
ORDER BY date DESC
;


-- -------------------------------------------------------
-- 2. Per-session restatement detail (for deep-dives)
-- -------------------------------------------------------

-- Uncomment and run against a specific date to see individual session deltas:
/*
SELECT
    rs.session_id,
    ROUND(rs.cart_total, 2)         AS rt_cart_total,
    ROUND(bs.cart_total, 2)         AS batch_cart_total,
    ROUND(bs.cart_total - rs.cart_total, 2) AS cart_delta,
    rs.event_count                  AS rt_event_count,
    bs.event_count                  AS batch_event_count,
    bs.late_arrival_count,
    bs.had_restatement
FROM realtime_sessions rs
JOIN batch_sessions_v bs
    ON rs.session_id = ANY(bs.original_session_ids)
WHERE rs.date_partition = '2024-10-15'
  AND bs.had_restatement = TRUE
ORDER BY ABS(bs.cart_total - rs.cart_total) DESC
LIMIT 100
;
*/
