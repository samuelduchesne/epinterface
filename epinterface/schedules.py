"""Writing hourly value schedules into idfkit documents."""

from collections.abc import Sequence

import numpy as np
from idfkit import IDFDocument, IDFObject

HOURS_PER_YEAR = 8760
DAYS_PER_YEAR = 365
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
    doc: IDFDocument, name: str, values: Sequence[float], type_limits: str
) -> IDFObject:
    """Add a `Schedule:Year` for 8760 hourly values, with its week/day objects.

    Naming and de-duplication follow archetypal's `to_year_week_day`: unique days
    become `d_{name}_NN`, unique weeks `w_{name}_NN`, and runs of identical weeks
    share one `Schedule:Year` block. Jan 1 is taken to be a Monday, so the final
    (365th) day sits alone in a partial last week.

    Raises:
        ValueError: If `values` does not hold exactly 8760 numbers.
    """
    arr = np.asarray(values, dtype=float)
    if arr.shape != (HOURS_PER_YEAR,):
        msg = f"Expected {HOURS_PER_YEAR} hourly values, got shape {arr.shape}."
        raise ValueError(msg)

    days = arr.reshape(DAYS_PER_YEAR, 24)
    unique_days, day_ids = np.unique(days, axis=0, return_inverse=True)
    day_ids = day_ids.reshape(-1)
    day_names = [f"d_{name}_{i:02d}" for i in range(len(unique_days))]
    for day_name, day_values in zip(day_names, unique_days, strict=True):
        fields: dict[str, str | float] = {"schedule_type_limits_name": type_limits}
        fields.update({f"hour_{h + 1}": float(v) for h, v in enumerate(day_values)})
        doc.add("Schedule:Day:Hourly", day_name, fields)

    # Pad the trailing partial week with its own last day.
    n_weeks = -(-DAYS_PER_YEAR // 7)
    padded = np.concatenate([
        day_ids,
        np.full(n_weeks * 7 - DAYS_PER_YEAR, day_ids[-1]),
    ]).reshape(n_weeks, 7)
    unique_weeks, week_ids = np.unique(padded, axis=0, return_inverse=True)
    week_ids = week_ids.reshape(-1)
    week_names = [f"w_{name}_{i:02d}" for i in range(len(unique_weeks))]
    for week_name, week_days in zip(week_names, unique_weeks, strict=True):
        # week_days runs Monday..Sunday; the object wants Sunday first.
        by_field = dict(
            zip(
                _WEEKDAY_FIELDS,
                (day_names[week_days[(i - 1) % 7]] for i in range(7)),
                strict=True,
            )
        )
        sunday, monday, tuesday = (
            by_field["sunday"],
            by_field["monday"],
            by_field["tuesday"],
        )
        doc.add(
            "Schedule:Week:Daily",
            week_name,
            **{f"{k}_schedule_day_name": v for k, v in by_field.items()},
            holiday_schedule_day_name=sunday,
            summerdesignday_schedule_day_name=monday,
            winterdesignday_schedule_day_name=monday,
            customday1_schedule_day_name=tuesday,
            customday2_schedule_day_name=sunday,
        )

    # Merge runs of identical weeks into Schedule:Year blocks.
    blocks: list[dict[str, str | int]] = []
    start_week = 0
    for week in range(1, n_weeks + 1):
        if week < n_weeks and week_ids[week] == week_ids[start_week]:
            continue
        start_month, start_day = _month_day(start_week * 7)
        end_month, end_day = _month_day(min(week * 7, DAYS_PER_YEAR) - 1)
        blocks.append({
            "schedule_week_name": week_names[week_ids[start_week]],
            "start_month": start_month,
            "start_day": start_day,
            "end_month": end_month,
            "end_day": end_day,
        })
        start_week = week
    return doc.add(
        "Schedule:Year",
        name,
        schedule_type_limits_name=type_limits,
        schedule_weeks=blocks,
    )


_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _month_day(day_of_year: int) -> tuple[int, int]:
    """Convert a zero-based day of a non-leap year to (month, day)."""
    remaining = day_of_year
    for month, length in enumerate(_MONTH_LENGTHS, start=1):
        if remaining < length:
            return month, remaining + 1
        remaining -= length
    msg = f"Day of year out of range: {day_of_year}"
    raise ValueError(msg)
