"""The backend's clock, replaced in tests."""

from datetime import UTC, datetime


def now() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


def stamp() -> str:
    """Return the current time as an ISO string."""
    return now().isoformat(timespec="seconds")
