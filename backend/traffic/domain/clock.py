"""
Clock abstraction for deterministic testing.
Pure Python — no framework dependencies.
"""
from datetime import datetime, timezone


class Clock:
    """Abstract clock interface for injectable time."""

    def now(self) -> datetime:
        raise NotImplementedError


class SystemClock(Clock):
    """Production clock using system time."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock(Clock):
    """Test clock with manually settable time."""

    def __init__(self, initial: datetime = None):
        self._now = initial or datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime):
        self._now = dt

    def advance(self, seconds: float):
        from datetime import timedelta
        self._now = self._now + timedelta(seconds=seconds)

