"""
src/stream_processor/models.py
──────────────────────────────────────────────────────────────────────────────
Pydantic v2 models that define the clickstream event schema.

These models are the single source of truth for:
  - Inbound validation (from Kinesis records)
  - Outbound serialisation (to S3 as NDJSON)
  - Schema documentation (referenced in CLAUDE.md)

Any schema change here MUST be reflected in CLAUDE.md and will trigger
a Glue crawler re-run to update the Athena catalog.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    PAGE_VIEW     = "page_view"
    CLICK         = "click"
    PURCHASE      = "purchase"
    SEARCH        = "search"
    SESSION_START = "session_start"
    SESSION_END   = "session_end"
    ADD_TO_CART   = "add_to_cart"
    REMOVE_FROM_CART = "remove_from_cart"


class DeviceType(str, Enum):
    DESKTOP = "desktop"
    MOBILE  = "mobile"
    TABLET  = "tablet"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Nested models
# ---------------------------------------------------------------------------

class PageContext(BaseModel):
    """URL and referrer context for the page where the event occurred."""

    model_config = ConfigDict(extra="ignore")

    url:      str
    referrer: str | None = None
    title:    str | None = None
    path:     str | None = None    # extracted from url for partitioning convenience

    @field_validator("url")
    @classmethod
    def url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("url must not be empty")
        return v.strip()


class DeviceContext(BaseModel):
    """Client device metadata."""

    model_config = ConfigDict(extra="ignore")

    type:       DeviceType = DeviceType.UNKNOWN
    os:         str | None = None
    browser:    str | None = None
    user_agent: str | None = None


class GeoContext(BaseModel):
    """Geo-enrichment fields. Populated by the Lambda transformer, not the client."""

    model_config = ConfigDict(extra="ignore")

    country_code: str | None = Field(None, min_length=2, max_length=2)
    region:       str | None = None
    city:         str | None = None

    @field_validator("country_code")
    @classmethod
    def upper_country_code(cls, v: str | None) -> str | None:
        return v.upper() if v else None


# ---------------------------------------------------------------------------
# Root event model — inbound (from Kinesis / API Gateway)
# ---------------------------------------------------------------------------

class ClickstreamEvent(BaseModel):
    """
    Validated inbound clickstream event.

    Producers (web/mobile SDK) must conform to this schema.
    Unknown extra fields are silently ignored to allow SDK version skew.
    """

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    event_id:     UUID
    event_type:   EventType
    session_id:   UUID
    user_id:      str = Field(..., min_length=1, max_length=256)
    anonymous_id: str | None = Field(None, max_length=256)
    timestamp:    datetime

    page:   PageContext
    device: DeviceContext = Field(default_factory=DeviceContext)
    geo:    GeoContext    = Field(default_factory=GeoContext)

    # Flexible catch-all for event-type-specific properties
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        """Normalise all timestamps to UTC regardless of input timezone."""
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_purchase_has_properties(self) -> "ClickstreamEvent":
        """Purchase events must include amount and currency in properties."""
        if self.event_type == EventType.PURCHASE:
            required = {"amount", "currency"}
            missing = required - self.properties.keys()
            if missing:
                raise ValueError(
                    f"purchase events must include {required} in properties. Missing: {missing}"
                )
        return self


# ---------------------------------------------------------------------------
# Processed event model — outbound (written to S3)
# ---------------------------------------------------------------------------

class ProcessedEvent(BaseModel):
    """
    Enriched and normalised event written to S3.

    Extends ClickstreamEvent with processing metadata added by the Lambda.
    This is what Athena/Glue sees.
    """

    model_config = ConfigDict(extra="ignore")

    # All original event fields
    event_id:     str     # serialised UUID (Athena string)
    event_type:   str
    session_id:   str
    user_id:      str
    anonymous_id: str | None
    timestamp:    str     # ISO-8601 UTC string

    page:       PageContext
    device:     DeviceContext
    geo:        GeoContext
    properties: dict[str, Any]

    # Processing metadata — added by Lambda
    processed_at:      str   # ISO-8601 UTC
    environment:       str
    kinesis_sequence:  str
    schema_version:    str = "1.0"

    # Hive partition columns — duplicated at top level for Athena performance
    partition_event_type: str
    partition_year:       str
    partition_month:      str
    partition_day:        str

    @classmethod
    def from_event(
        cls,
        event: ClickstreamEvent,
        *,
        kinesis_sequence: str,
        environment: str,
    ) -> "ProcessedEvent":
        """Construct a ProcessedEvent from a validated ClickstreamEvent."""
        now = datetime.now(timezone.utc)
        ts  = event.timestamp

        return cls(
            event_id     = str(event.event_id),
            event_type   = event.event_type.value,
            session_id   = str(event.session_id),
            user_id      = event.user_id,
            anonymous_id = event.anonymous_id,
            timestamp    = ts.isoformat(),
            page         = event.page,
            device       = event.device,
            geo          = event.geo,
            properties   = event.properties,

            processed_at     = now.isoformat(),
            environment      = environment,
            kinesis_sequence = kinesis_sequence,

            partition_event_type = event.event_type.value,
            partition_year       = f"{ts.year:04d}",
            partition_month      = f"{ts.month:02d}",
            partition_day        = f"{ts.day:02d}",
        )
