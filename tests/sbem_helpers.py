"""Small SBEM objects shared by the tests of the fork's added fields."""

from pathlib import Path

from epinterface.data import DefaultEPWZipPath
from epinterface.geometry import ShoeboxGeometry
from epinterface.sbem.archetype import AtticAssumptions, BasementAssumptions
from epinterface.sbem.builder import Model
from epinterface.sbem.components.schedules import (
    DayComponent,
    ScheduleTypeLimitType,
    WeekComponent,
    YearComponent,
    YearScheduleCategory,
)
from epinterface.sbem.components.zones import ZoneComponent

ZONE_PATH = Path(__file__).parent / "data" / "sbem_zone.json"
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def load_zone() -> ZoneComponent:
    """The seed's default zone definition."""
    return ZoneComponent.model_validate_json(ZONE_PATH.read_text())


def day(name: str, values: list[float], kind: ScheduleTypeLimitType = "Fraction"):
    """A day schedule from 24 hourly values."""
    assert len(values) == 24
    return DayComponent(
        Name=name, Type=kind, **{f"Hour_{h:02d}": v for h, v in enumerate(values)}
    )


def year(
    name: str,
    week: WeekComponent,
    category: YearScheduleCategory = "Lighting",
) -> YearComponent:
    """A year with the same week every month."""
    return YearComponent(Name=name, Type=category, **dict.fromkeys(MONTHS, week))


def week(name: str, every_day: DayComponent, **slots: DayComponent) -> WeekComponent:
    """A week with the same day every weekday, overridden or extended by `slots`."""
    return WeekComponent(Name=name, **{**dict.fromkeys(WEEKDAYS, every_day), **slots})


def small_model(zone: ZoneComponent) -> Model:
    """A one-zone, one-storey shoebox of a zone definition."""
    return Model(
        geometry=ShoeboxGeometry(
            x=0, y=0, w=12, d=8, h=3, wwr=0.3, num_stories=1, zoning="by_storey"
        ),
        Zone=zone,
        Attic=AtticAssumptions(UseFraction=None, Conditioned=False),
        Basement=BasementAssumptions(UseFraction=None, Conditioned=False),
        Weather=DefaultEPWZipPath,
    )
