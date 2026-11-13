"""Responses of the observability endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DurationsResponse(_Model):
    p50: float = Field(description="Median, seconds.")
    p95: float = Field(description="95th percentile, seconds.")
    max: float = Field(description="Longest, seconds.")


class ProcessingStatsResponse(_Model):
    window_hours: int
    completed: int = Field(description="Events completed in the window.")
    end_to_end_seconds: DurationsResponse | None = Field(
        description="From the employee change to completion. Null when nothing completed."
    )
    processing_seconds: DurationsResponse | None = Field(
        description="Final attempt: from the last worker pickup to completion (the worker "
        "time of the successful attempt; excludes queueing and retry waits)."
    )


class OrganizationSummaryResponse(_Model):
    generated_at: datetime
    employees: dict[str, int] = Field(description="Not archived, by employment status.")
    workflows: dict[str, int] = Field(description="`active` and `total`.")
    connectors: dict[str, int] = Field(description="By status, plus `total`.")
    events: dict[str, int] = Field(description="By processing status.")
    dead_letters_open: int
    conflicts_open: dict[str, int] = Field(description="Open conflicts by severity, plus `total`.")
    processing: ProcessingStatsResponse


class ComponentInstanceResponse(_Model):
    instance: str = Field(description="host:pid of the process.")
    started_at: datetime
    last_seen_at: datetime
    seconds_since_seen: float
    healthy: bool


class SystemStatusResponse(_Model):
    generated_at: datetime
    healthy: bool
    problems: list[str]
    components: dict[str, list[ComponentInstanceResponse]] = Field(
        description="Heartbeats per component (`worker`, `relay`), most recent first."
    )
    outbox_unpublished: int
    outbox_oldest_unpublished_seconds: float | None
    events_by_status: dict[str, int]
    events_oldest_pending_seconds: float | None
    events_stuck_processing: int = Field(
        description="Events still marked processing after their lease ran out."
    )
    dead_letters_open: int
