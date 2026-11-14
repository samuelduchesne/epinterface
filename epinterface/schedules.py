"""Writing hourly value schedules into idfkit documents."""

import re
from collections.abc import Sequence
from typing import Any, Literal

import numpy as np
from idfkit import IDFObject
from numpy.typing import NDArray

from epinterface.document import EPDocument, add_or_replace

HOURS_PER_YEAR = 8760
DAYS_PER_YEAR = 365
WEEKS_PER_YEAR = 52
# Schedule:Week:Daily day fields, Sunday first as EnergyPlus orders them.
_WEEKDAY_FIELDS = (
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)


def add_values_schedule(
    doc: EPDocument,
    name: str,
    values: Sequence[float] | NDArray[np.floating],
    type_limits: str,
    first_weekday: Literal["monday", "sunday"] = "monday",
) -> IDFObject:
    """Add a `Schedule:Year` for 8760 hourly values, with its week/day objects.

    Reproduces archetypal's `to_year_week_day`: unique days become
    `d_{name}_NN`, unique weeks (the first 52, so day 365 is not part of any
    week) `w_{name}_NN`, and runs of identical weeks share one `Schedule:Year`
    block, the last of which is stretched to Dec 31.

    `first_weekday` is the weekday of series day 0 (Jan 1). The default,
    "monday", is archetypal's own default (`start_day_of_the_week=0`, which
    epinterface never overrides): the first day of each week lands in the
    Monday field, whatever weekday EnergyPlus's RunPeriod starts on.
    "sunday" puts it in the Sunday field instead.

    Writing a name again is safe: an identical existing schedule (year, weeks
    and days) is returned untouched; a different one is replaced, together
    with the `d_`/`w_` objects generated for that name (also when only some
    of them are left over).

    Raises:
        ValueError: If `values` does not hold exactly 8760 numbers.
    """
    arr = np.asarray(values, dtype=float)
    if arr.shape != (HOURS_PER_YEAR,):
        msg = f"Expected {HOURS_PER_YEAR} hourly values, got shape {arr.shape}."
        raise ValueError(msg)

    planned: list[tuple[str, str, dict[str, Any]]] = []
    days = arr.reshape(DAYS_PER_YEAR, 24)
    unique_days, day_ids = np.unique(days, axis=0, return_inverse=True)
    day_ids = day_ids.reshape(-1)
    day_names = [f"d_{name}_{i:02d}" for i in range(len(unique_days))]
    # Weeks are the first 52 x 7 days; day 365 belongs to no week (as archetypal).
    weeks = day_ids[: WEEKS_PER_YEAR * 7].reshape(WEEKS_PER_YEAR, 7)
    unique_weeks, week_ids = np.unique(weeks, axis=0, return_inverse=True)
    week_ids = week_ids.reshape(-1)
    week_names = [f"w_{name}_{i:02d}" for i in range(len(unique_weeks))]
    # Only days used by a week are written (numbering keeps the gaps, as archetypal).
    for i in sorted({int(d) for d in unique_weeks.reshape(-1)}):
        fields: dict[str, str | float] = {"schedule_type_limits_name": type_limits}
        fields.update({f"hour_{h + 1}": float(v) for h, v in enumerate(unique_days[i])})
        planned.append(("Schedule:Day:Hourly", day_names[i], fields))
    # Index into the Sunday-first field list of the week's first day.
    offset = 1 if first_weekday == "monday" else 0
    for week_name, week_days in zip(week_names, unique_weeks, strict=True):
        by_position = [day_names[d] for d in week_days]
        by_field = {
            field: by_position[(k - offset) % 7]
            for k, field in enumerate(_WEEKDAY_FIELDS)
        }
        week_fields: dict[str, Any] = {
            f"{k}_schedule_day_name": v for k, v in by_field.items()
        }
        # The special days follow the weekday fields (as archetypal's week did):
        # holidays and custom day 2 the Sunday field, the design days the Monday
        # field and custom day 1 the Tuesday field, whatever `first_weekday` is.
        week_fields |= {
            "holiday_schedule_day_name": by_field["sunday"],
            "summerdesignday_schedule_day_name": by_field["monday"],
            "winterdesignday_schedule_day_name": by_field["monday"],
            "customday1_schedule_day_name": by_field["tuesday"],
            "customday2_schedule_day_name": by_field["sunday"],
        }
        planned.append(("Schedule:Week:Daily", week_name, week_fields))

    # Merge runs of identical weeks into Schedule:Year blocks.
    blocks: list[dict[str, str | int]] = []
    start_week = 0
    for week in range(1, WEEKS_PER_YEAR + 1):
        if week < WEEKS_PER_YEAR and week_ids[week] == week_ids[start_week]:
            continue
        start_month, start_day = _month_day(start_week * 7)
        end_month, end_day = (
            (12, 31) if week == WEEKS_PER_YEAR else _month_day(week * 7 - 1)
        )
        blocks.append({
            "schedule_week_name": week_names[week_ids[start_week]],
            "start_month": start_month,
            "start_day": start_day,
            "end_month": end_month,
            "end_day": end_day,
        })
        start_week = week
    year_fields: dict[str, Any] = {
        "schedule_type_limits_name": type_limits,
        "schedule_weeks": blocks,
    }
    planned.append(("Schedule:Year", name, year_fields))

    if all(_is_unchanged(doc, *item) for item in planned):
        return doc["Schedule:Year"][name]
    _remove_generated(doc, name)
    for obj_type, obj_name, fields in planned:
        doc.add(obj_type, obj_name, fields)
    return doc["Schedule:Year"][name]


def _is_unchanged(
    doc: EPDocument, obj_type: str, name: str, fields: dict[str, Any]
) -> bool:
    """Whether `doc` already holds `obj_type` `name` with exactly these fields."""
    existing = doc[obj_type].get(name)
    if existing is None:
        return False
    stored = {
        k: v
        for k, v in existing.to_dict().items()
        if k != "name" and v not in (None, "")
    }
    return stored == {k: v for k, v in fields.items() if v not in (None, "")}


def _remove_generated(doc: EPDocument, name: str) -> None:
    """Remove the `Schedule:Year` `name` and the day/week objects generated for it."""
    generated = re.compile(rf"[dw]_{re.escape(name)}_\d{{2,}}", re.IGNORECASE)
    if name in doc["Schedule:Year"]:
        doc.removeidfobject(doc["Schedule:Year"][name])
    for obj_type in ("Schedule:Week:Daily", "Schedule:Day:Hourly"):
        for obj in list(doc[obj_type]):
            if generated.fullmatch(obj.name):
                doc.removeidfobject(obj)


NON_LEAP_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
"""The number of days in each month of a non-leap year, January first."""


def _month_day(day_of_year: int) -> tuple[int, int]:
    """Convert a zero-based day of a non-leap year to (month, day)."""
    remaining = day_of_year
    for month, length in enumerate(NON_LEAP_MONTH_LENGTHS, start=1):
        if remaining < length:
            return month, remaining + 1
        remaining -= length
    msg = f"Day of year out of range: {day_of_year}"
    raise ValueError(msg)


def add_day_hourly_schedule(
    doc: EPDocument, name: str, type_limits: str, values: Sequence[float]
) -> IDFObject:
    """Write a `Schedule:Day:Hourly` of 24 values, the first for hour 1.

    An identical schedule is reused and a different one of the same name
    replaced (see `epinterface.document.add_or_replace`).

    Raises:
        ValueError: If `values` does not hold exactly 24 numbers.
    """
    if len(values) != 24:
        msg = f"Expected 24 hourly values, got {len(values)}."
        raise ValueError(msg)
    return add_or_replace(
        doc,
        "Schedule:Day:Hourly",
        name,
        schedule_type_limits_name=type_limits,
        **{f"hour_{h + 1}": v for h, v in enumerate(values)},
    )
