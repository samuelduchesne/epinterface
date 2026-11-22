"""The mean fraction of a year schedule counts each month's real weekdays (UP-9)."""

import calendar
from datetime import date, timedelta

import pytest

from tests.sbem_helpers import WEEKDAYS, day, week, year


def _hourly_mean(schedule, y: int) -> float:
    """The schedule's mean value over every hour of year `y`, day by day."""
    total = 0.0
    start = date(y, 1, 1)
    days = 366 if calendar.isleap(y) else 365
    for n in range(days):
        d = start + timedelta(days=n)
        w = schedule.Weeks[d.month - 1]
        total += sum(getattr(w, WEEKDAYS[d.weekday()]).Values)
    return total / (days * 24)


@pytest.mark.parametrize("y", [2017, 2018, 2020, 2023])
@pytest.mark.parametrize("weekday", WEEKDAYS)
def test_one_weekday_on(weekday: str, y: int):
    """A schedule on only on one weekday averages to that weekday's share of the year."""
    on, off = day("on", [1.0] * 24), day("off", [0.0] * 24)
    sched = year("one_day", week("w", off, **{weekday: on}), "WaterUse")
    expected = _hourly_mean(sched, y)
    count = sum(
        1
        for n in range(366 if calendar.isleap(y) else 365)
        if (date(y, 1, 1) + timedelta(days=n)).weekday() == WEEKDAYS.index(weekday)
    )
    assert expected == pytest.approx(count / (366 if calendar.isleap(y) else 365))
    assert sched.fractional_year_sum(y) == pytest.approx(expected, abs=1e-12)


def test_weekday_profile():
    """A distinct value per weekday and hour gives the hour-by-hour mean."""
    days = {
        name: day(name, [(i + 1) * (h % 5) / 40 for h in range(24)])
        for i, name in enumerate(WEEKDAYS)
    }
    sched = year("profile", week("w", days["Monday"], **days), "WaterUse")
    assert sched.fractional_year_sum(2018) == pytest.approx(
        _hourly_mean(sched, 2018), abs=1e-12
    )
