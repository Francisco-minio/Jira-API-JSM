from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import holidays


def chile_holidays(years: list[int]) -> set[date]:
    return set(holidays.country_holidays("CL", years=years).keys())


def chile_holiday_names(years: list[int]) -> dict[date, str]:
    return {day: str(name) for day, name in holidays.country_holidays("CL", years=years).items()}


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def business_days_between(start: date, end: date) -> list[date]:
    holiday_set = chile_holidays(list(range(start.year, end.year + 1)))
    days: list[date] = []
    for current in daterange(start, end):
        if current.weekday() < 5 and current not in holiday_set:
            days.append(current)
    return days


def expected_capacity_hours(start: date, end: date, daily_hours: int = 8) -> float:
    return float(len(business_days_between(start, end)) * daily_hours)


def to_tz_aware(dt: datetime | None, tz_name: str) -> datetime | None:
    if dt is None:
        return None
    tz = ZoneInfo(tz_name)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)
