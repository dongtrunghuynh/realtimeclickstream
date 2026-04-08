"""
Local Report Generator — produces the accuracy/latency dashboard from local CSV data.

Use this BEFORE you have Athena set up, or to re-render results from a past run.
After running the pipeline, export results using the Athena queries in
athena/views/accuracy_comparison.sql, save as CSV, then run this script.

Usage:
    # Generate from CSVs exported from Athena
    python src/dashboard/local_report.py \
        --speed-csv  speed_layer_2024-10-15.csv \
        --batch-csv  batch_layer_2024-10-15.csv \
        --audit-csv  restatement_audit_2024-10-15.csv \
        --date       2024-10-15

    # Generate a sample report with placeholder numbers (for testing the output format)
    python src/dashboard/local_report.py --sample
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class LayerMetrics:
    total_sessions:     int   = 0
    total_revenue:      float = 0.0
    total_events:       int   = 0
    converted_sessions: int   = 0
    avg_duration_s:     float = 0.0
    latency_label:      str   = ""

    @property
    def conversion_rate_pct(self) -> float:
        if self.total_sessions == 0:
            return 0.0
        return self.converted_sessions / self.total_sessions * 100

    @property
    def avg_duration_label(self) -> str:
        m = int(self.avg_duration_s // 60)
        s = int(self.avg_duration_s % 60)
        return f"{m}m {s:02d}s"


@dataclass
class RestatementMetrics:
    total_compared:         int   = 0
    sessions_restated:      int   = 0
    avg_revenue_disc:       float = 0.0
    max_revenue_disc:       float = 0.0
    total_revenue_restated: float = 0.0
    avg_event_count_disc:   float = 0.0
    conversion_flips:       int   = 0

    @property
    def restatement_pct(self) -> float:
        if self.total_compared == 0:
            return 0.0
        return self.sessions_restated / self.total_compared * 100


# ─── CSV loaders ─────────────────────────────────────────────────────────────

def _f(d: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(d.get(key, default) or default)
    except (ValueError, TypeError):
        return default


def _i(d: dict, key: str, default: int = 0) -> int:
    try:
        return int(float(d.get(key, default) or default))
    except (ValueError, TypeError):
        return default


def load_speed_csv(path: str) -> LayerMetrics:
    with open(path) as f:
        row = next(csv.DictReader(f))
    return LayerMetrics(
        total_sessions     = _i(row, "total_sessions"),
        total_revenue      = _f(row, "total_revenue"),
        total_events       = _i(row, "total_events"),
        converted_sessions = _i(row, "converted_sessions"),
        avg_duration_s     = _f(row, "avg_session_duration_seconds"),
        latency_label      = "< 30 seconds",
    )


def load_batch_csv(path: str) -> LayerMetrics:
    with open(path) as f:
        row = next(csv.DictReader(f))
    return LayerMetrics(
        total_sessions     = _i(row, "total_sessions"),
        total_revenue      = _f(row, "total_revenue"),
        total_events       = _i(row, "total_events"),
        converted_sessions = _i(row, "converted_sessions"),
        avg_duration_s     = _f(row, "avg_session_duration_seconds"),
        latency_label      = "~ 8 hours",
    )


def load_audit_csv(path: str) -> RestatementMetrics:
    with open(path) as f:
        row = next(csv.DictReader(f))
    return RestatementMetrics(
        total_compared         = _i(row, "total_sessions_compared"),
        sessions_restated      = _i(row, "sessions_restated"),
        avg_revenue_disc       = _f(row, "avg_revenue_discrepancy"),
        max_revenue_disc       = _f(row, "max_revenue_discrepancy"),
        total_revenue_restated = _f(row, "total_revenue_restated"),
        avg_event_count_disc   = _f(row, "avg_event_count_discrepancy"),
        conversion_flips       = _i(row, "conversion_flips", 0),
    )


# ─── Sample data for --sample flag ───────────────────────────────────────────

def _sample_data() -> tuple[LayerMetrics, LayerMetrics, RestatementMetrics]:
    speed = LayerMetrics(
        total_sessions=18_432, total_revenue=284_120.50, total_events=921_600,
        converted_sessions=590, avg_duration_s=252, latency_label="< 30 seconds",
    )
    batch = LayerMetrics(
        total_sessions=17_891, total_revenue=291_445.25, total_events=947_200,
        converted_sessions=643, avg_duration_s=278, latency_label="~ 8 hours",
    )
    audit = RestatementMetrics(
        total_compared=18_432, sessions_restated=541,
        avg_revenue_disc=13.52, max_revenue_disc=299.00,
        total_revenue_restated=7_324.82, avg_event_count_disc=0.9,
        conversion_flips=53,
    )
    return speed, batch, audit


# ─── Renderer ────────────────────────────────────────────────────────────────

def render(
    speed: LayerMetrics,
    batch: LayerMetrics,
    audit: RestatementMetrics,
    date: str,
) -> str:
    W = 72  # total width
    rev_error_pct = (
        abs(batch.total_revenue - speed.total_revenue) / batch.total_revenue * 100
        if batch.total_revenue else 0.0
    )

    lines = [
        "",
        "═" * W,
        "  LAMBDA ARCHITECTURE — ACCURACY / LATENCY REPORT",
        f"  Date: {date}",
        "═" * W,
        f"  {'Metric':<32} {'Speed Layer':>16} {'Batch Layer':>16}",
        f"  {'':─<32} {'(DynamoDB)':>16} {'(Athena)':>16}",
        f"  {'Total Sessions':<32} {speed.total_sessions:>16,} {batch.total_sessions:>16,}",
        f"  {'Total Revenue':<32} {f'${speed.total_revenue:,.2f}':>16} {f'${batch.total_revenue:,.2f}':>16}",
        f"  {'Converted Sessions':<32} {speed.converted_sessions:>16,} {batch.converted_sessions:>16,}",
        f"  {'Conversion Rate':<32} {f'{speed.conversion_rate_pct:.2f}%':>16} {f'{batch.conversion_rate_pct:.2f}%':>16}",
        f"  {'Avg Session Duration':<32} {speed.avg_duration_label:>16} {batch.avg_duration_label:>16}",
        f"  {'Latency':<32} {speed.latency_label:>16} {batch.latency_label:>16}",
        "",
        "  RESTATEMENT ANALYSIS",
        f"  {'':─<68}",
        f"  Sessions restated:          {audit.sessions_restated:>10,}  ({audit.restatement_pct:.1f}% of total)",
        f"  Conversion flips:           {audit.conversion_flips:>10,}  (speed layer missed a purchase)",
        f"  Avg revenue discrepancy:    {f'${audit.avg_revenue_disc:>9,.2f}'}  per restated session",
        f"  Max revenue discrepancy:    {f'${audit.max_revenue_disc:>9,.2f}'}  single session",
        f"  Total revenue restated:     {f'${audit.total_revenue_restated:>9,.2f}'}",
        f"  Revenue error (speed layer):{f'{rev_error_pct:>9.2f}%'}  vs batch ground truth",
        "",
        "  INTERPRETATION",
        f"  {'':─<68}",
        f"  {100 - audit.restatement_pct:.1f}% of sessions were accurate in real-time — acceptable for",
        "  live dashboards, A/B testing, and operational monitoring.",
        f"  The {audit.restatement_pct:.1f}% restatement rate represents events that arrived",
        f"  late (>{120}s delay) and were held back by the LateArrivalInjector.",
        "  Use the Athena batch layer for financial reporting and billing.",
        "═" * W,
        "",
    ]
    return "\n".join(lines)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Local accuracy/latency report renderer")
    parser.add_argument("--date",       default="N/A")
    parser.add_argument("--speed-csv",  help="CSV exported from Athena speed layer query")
    parser.add_argument("--batch-csv",  help="CSV exported from Athena batch layer query")
    parser.add_argument("--audit-csv",  help="CSV exported from Athena restatement audit query")
    parser.add_argument("--sample",     action="store_true", help="Print a sample report with placeholder data")
    parser.add_argument("--output",     help="Save report to this text file")
    args = parser.parse_args()

    if args.sample:
        speed, batch, audit = _sample_data()
        date = args.date if args.date != "N/A" else "2024-10-15 (sample)"
    else:
        if not all([args.speed_csv, args.batch_csv, args.audit_csv]):
            print("Error: provide --speed-csv, --batch-csv, --audit-csv or use --sample")
            sys.exit(1)
        speed = load_speed_csv(args.speed_csv)
        batch = load_batch_csv(args.batch_csv)
        audit = load_audit_csv(args.audit_csv)
        date  = args.date

    report = render(speed, batch, audit, date)
    print(report)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Report saved to {args.output}")


if __name__ == "__main__":
    main()
