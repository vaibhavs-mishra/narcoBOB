"""Identifiers and timestamps."""

from __future__ import annotations

from datetime import UTC, datetime

from ulid import ULID


def new_id() -> str:
    """A new ULID string (sortable by creation time)."""
    return str(ULID())


def iso(dt: datetime) -> str:
    """ISO-8601 UTC with a trailing Z, second precision: `2026-09-28T10:15:00Z`."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_now() -> str:
    return iso(datetime.now(UTC))


def parse_ts(value: str) -> datetime:
    """Parse an ISO timestamp; naive values are treated as UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
