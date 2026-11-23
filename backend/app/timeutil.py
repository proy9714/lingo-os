"""Time helpers. The database stores UTC ISO-8601 strings; days are the laptop's local days."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    """Aware datetime → '2026-11-23T18:04:05.123Z'. Naive values are treated as local time."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def local_day(value: str) -> date:
    """The local calendar day of a stored UTC timestamp."""
    return from_iso(value).astimezone().date()


def local_month(value: str) -> str:
    return from_iso(value).astimezone().strftime("%Y-%m")


def local_today() -> date:
    return datetime.now().date()


def local_midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time(0, 0)).astimezone(timezone.utc)


def local_noon_utc(day: date) -> datetime:
    return datetime.combine(day, time(12, 0)).astimezone(timezone.utc)


def minutes(seconds: int | float) -> int:
    return int(round(seconds / 60))


def hours(seconds: int | float, digits: int = 1) -> float:
    return round(seconds / 3600, digits)


__all__ = [
    "date",
    "datetime",
    "timedelta",
    "utc_now",
    "to_iso",
    "from_iso",
    "local_day",
    "local_month",
    "local_today",
    "local_midnight_utc",
    "local_noon_utc",
    "minutes",
    "hours",
]
