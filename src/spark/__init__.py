"""
Spark jobs package — batch processing layer.

Jobs:
    session_stitcher.py     — Nightly re-sessionization including late arrivals
    late_arrival_handler.py — Per-session restatement audit (delta speed vs batch)

Submitting to EMR Serverless:
    bash scripts/submit_spark_job.sh session_stitcher 2024-10-15
    bash scripts/submit_spark_job.sh late_arrival_handler 2024-10-15

Local testing (requires pyspark):
    pip install pyspark==3.5.0
    python src/spark/session_stitcher.py \
        --date 2024-10-15 \
        --raw-path s3://your-bucket/events/ \
        --output-path s3://your-bucket/corrected-sessions/

Viewing logs after submission:
    aws logs tail /aws/emr-serverless/clickstream-reconciler-dev --follow
"""
