"""Holiday and design-day slots in WeekComponent (UP-2)."""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from epinterface.document import EPDocument, minimal_document
from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.schedules import WeekComponent
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import day, load_zone, small_model, week, year

ON = day("on", [1.0] * 24)
OFF = day("off", [0.0] * 24)
HALF = day("half", [0.5] * 24)
# 4 July 2018 is a Wednesday (the results calendar is 2018)
HOLIDAY_MONTH, HOLIDAY_DAY = 7, 4


@pytest.fixture(scope="module")
def zone() -> ZoneComponent:
    """The seed's default zone definition."""
    return load_zone()


def test_slots_default_to_unset():
    """Older weeks load; their special days are unset."""
    w = week("w", ON)
    assert w.Holiday is None
    assert w.SummerDesignDay is None
    assert w.WinterDesignDay is None
    assert len(w.Days) == 7


def test_slot_types_must_match():
    """A special day must have the week's type limits."""
    with pytest.raises(ValidationError, match="Type limits"):
        week("w", ON, Holiday=day("t", [20.0] * 24, "Temperature"))


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="writing needs an EnergyPlus version",
)
def test_week_writes_its_slots():
    """Set slots fill the week; unset ones keep the former fallbacks."""
    doc = minimal_document(energyplus_settings.version_tuple)
    w = week("special", ON, Holiday=OFF, SummerDesignDay=HALF)
    w.add_week_to_idf(doc, None, winter_design_day_sch_name="caller_winter")
    obj = doc["Schedule:Week:Daily"]["special"]
    assert obj.holiday_schedule_day_name == "off"
    assert obj.summerdesignday_schedule_day_name == "half"
    assert obj.winterdesignday_schedule_day_name == "caller_winter"

    doc = minimal_document(energyplus_settings.version_tuple)
    week("plain", ON, Sunday=HALF).add_week_to_idf(doc, None)
    obj = doc["Schedule:Week:Daily"]["plain"]
    assert obj.holiday_schedule_day_name == "half"  # Sunday's
    assert obj.summerdesignday_schedule_day_name == "on"  # Monday's


def test_week_round_trips_through_json():
    """The slots survive serialisation."""
    w = week("special", ON, Holiday=OFF, WinterDesignDay=HALF)
    assert WeekComponent.model_validate_json(w.model_dump_json()) == w


def _holiday_lights(zone: ZoneComponent) -> ZoneComponent:
    z = zone.model_copy(deep=True)
    z.Operations.SpaceUse.Lighting.Schedule = year(
        "lights_with_holiday", week("lights_week", ON, Holiday=OFF)
    )
    return z


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="simulating needs EnergyPlus",
)
def test_simulated_holiday_turns_lights_off(zone: ZoneComponent, tmp_path: Path):
    """On a holiday the lights follow the Holiday slot, on other days Monday's."""

    def add_holiday(doc: EPDocument) -> EPDocument:
        doc["RunPeriodControl:SpecialDays"].add(
            "Independence Day",
            start_date=f"{HOLIDAY_MONTH}/{HOLIDAY_DAY}",
            duration=1,
            special_day_type="Holiday",
        )
        return doc

    model = small_model(_holiday_lights(zone))
    result = model.run(eplus_parent_dir=tmp_path, post_geometry_callback=add_holiday)
    try:
        lights = result.hourly_timeseries(["InteriorLights:Electricity"]).iloc[:, 0]
        index = lights.index
        holiday = (index.month == HOLIDAY_MONTH) & (index.day == HOLIDAY_DAY)
        assert np.all(lights.to_numpy()[holiday] == 0)
        assert np.all(lights.to_numpy()[~holiday] > 0)
    finally:
        result.sql.close()
