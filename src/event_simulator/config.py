"""Simulator configuration — reads from env vars with CLI arg overrides."""

import os
from dataclasses import dataclass


@dataclass
class SimulatorConfig:
    stream_name: str
    region: str
    rate: int
    duration: int
    late_arrival_pct: float
    csv_path: str
    enable_cloudwatch: bool = True   # Set False in unit tests / CI to skip metric publishing
    limit: int | None = None          # Max events to read from CSV (None = all)

    @classmethod
    def from_args(cls, args) -> "SimulatorConfig":
        return cls(
            stream_name=args.stream_name or os.environ.get("KINESIS_STREAM_NAME", "clickstream-events-dev"),
            region=args.region or os.environ.get("AWS_REGION", "us-east-1"),
            rate=args.rate,
            duration=args.duration,
            late_arrival_pct=args.late_arrival_pct,
            csv_path=args.csv_path,
            enable_cloudwatch=not getattr(args, "no_cloudwatch", False),
            limit=getattr(args, "limit", None),
        )
