"""Tests for the interface helpers, material library and literal types."""

import idfkit
import idfkit.schedules
import numpy as np
import pytest
from pydantic import TypeAdapter

from epinterface.document import add_construction
from epinterface.interface import (
    DefaultMaterialLibrary,
    HeatRecoveryTypeType,
    IdealLoadsLimitType,
    InfDesignFlowRateCalculationMethodType,
    add_constant_schedule,
    add_default_schedules,
    add_default_sim_controls,
    add_site_ground_temperature,
    add_zone_list,
    ensure_fraction_type_limits,
    stucco,
    zone_list_names,
)


def test_zone_list_writes_object(doc):
    """Zone names land in the extensible zones, blanks dropped."""
    zone_list = add_zone_list(doc, "L", ["A", "B", ""])
    assert doc["ZoneList"]["L"] is zone_list
    assert [z.zone_name for z in zone_list.zones] == ["A", "B"]
    assert zone_list_names(zone_list) == ["A", "B"]


def test_add_default_sim_controls(doc):
    """The default controls write all four objects with their values."""
    assert add_default_sim_controls(doc) is doc
    control = doc["SimulationControl"].first()
    assert control.do_zone_sizing_calculation == "Yes"
    assert control.do_plant_sizing_calculation == "No"
    assert control.maximum_number_of_hvac_sizing_simulation_passes == 2
    period = doc["RunPeriod"]["Year"]
    assert (period.begin_month, period.begin_day_of_month) == (1, 1)
    assert (period.end_month, period.end_day_of_month) == (12, 31)
    assert period.day_of_week_for_start_day == "Sunday"
    assert period.apply_weekend_holiday_rule == "Yes"
    assert period.use_weather_file_holidays_and_special_days == "No"
    assert doc["Timestep"].first().number_of_timesteps_per_hour == 6
    sizing = doc["Sizing:Parameters"].first()
    assert (sizing.heating_sizing_factor, sizing.cooling_sizing_factor) == (1.15, 1.15)


def test_add_default_sim_controls_replaces_singletons(doc):
    """Writing the controls twice keeps one of each object."""
    add_default_sim_controls(doc)
    add_default_sim_controls(doc)
    for obj_type in ("SimulationControl", "Timestep", "Sizing:Parameters"):
        assert len(doc[obj_type]) == 1
    assert len(doc["RunPeriod"]) == 1


def test_site_ground_temperature_replaces_existing_object(doc):
    """The minimal document's ground temperatures are replaced, not duplicated."""
    add_site_ground_temperature(doc, [float(v) for v in range(12)])
    assert len(doc["Site:GroundTemperature:BuildingSurface"]) == 1
    ground = doc["Site:GroundTemperature:BuildingSurface"].first()
    assert (ground.january_ground_temperature, ground.december_ground_temperature) == (
        0,
        11,
    )


def test_site_ground_temperature_writes_plain_numbers(doc):
    """Numpy values are written as plain numbers."""
    add_site_ground_temperature(doc, list(np.linspace(10.0, 21.0, 12)))
    ground = doc["Site:GroundTemperature:BuildingSurface"].first()
    assert type(ground.january_ground_temperature) is float
    january = next(
        line
        for line in idfkit.write_idf(doc).splitlines()
        if "January Ground Temperature" in line
    )
    assert january.split(",")[0].strip() == "10"


@pytest.mark.parametrize("count", [11, 13])
def test_site_ground_temperature_needs_12_values(doc, count):
    """Anything but 12 monthly values is rejected."""
    with pytest.raises(ValueError, match=f"GROUNDTEMP:EXPECTED_12:RECEIVED_{count}"):
        add_site_ground_temperature(doc, [10.0] * count)


def test_material_library_layer(doc):
    """A library material is written as a Material of the given thickness."""
    material = DefaultMaterialLibrary().stucco.add_layer_to_idf(doc, 0.03)
    assert material.name == "Stucco_0.03m" == stucco.layer_name(0.03)
    assert material.thickness == 0.03
    assert material.conductivity == 0.721
    assert material.density == 1865
    assert material.specific_heat == 878
    assert material.roughness == "MediumSmooth"
    assert material.thermal_absorptance in (None, "")


def test_construction_writes_layers_in_order(doc):
    """Layers are referenced outside-in."""
    names = [
        stucco.add_layer_to_idf(doc, 0.03).name,
        DefaultMaterialLibrary().insulation.add_layer_to_idf(doc, 0.15).name,
    ]
    wall = add_construction(doc, "Wall", names)
    assert [wall.outside_layer, wall.layer_2] == ["Stucco_0.03m", "Insulation_0.15m"]


def test_constructions_share_a_layer_material(doc):
    """A second construction reusing a layer does not duplicate the material."""
    add_construction(doc, "A", [stucco.add_layer_to_idf(doc, 0.03).name])
    add_construction(
        doc,
        "B",
        [
            stucco.add_layer_to_idf(doc, 0.03).name,
            stucco.add_layer_to_idf(doc, 0.05).name,
        ],
    )
    assert len(doc["Material"]) == 2
    assert doc["Construction"]["B"].outside_layer == "Stucco_0.03m"
    assert doc["Construction"]["B"].layer_2 == "Stucco_0.05m"


def test_same_name_different_construction_replaces(doc):
    """Re-adding a construction name with new layers replaces it, as archetypal did."""
    add_construction(doc, "A", [stucco.add_layer_to_idf(doc, 0.03).name])
    add_construction(doc, "A", [stucco.add_layer_to_idf(doc, 0.05).name])
    assert len(doc["Construction"]) == 1
    assert doc["Construction"]["A"].outside_layer == "Stucco_0.05m"


def test_constant_schedule_uses_archetypal_object_names(doc):
    """A constant schedule is a Year/Week/Day chain with the legacy names."""
    year = add_constant_schedule(doc, "Always_On", 1)
    assert year.schedule_type_limits_name == "Fraction"
    _assert_fraction_limits(doc)
    assert doc["Schedule:Week:Daily"]["w_Always_On_00"] is not None
    assert doc["Schedule:Day:Hourly"]["d_Always_On_00"].hour_12 == 1
    values = idfkit.schedules.values(year, year=2018, document=doc)
    assert np.all(np.asarray(values) == 1)


def test_add_default_schedules_names(doc):
    """The ten protected on/off schedules exist with their values."""
    returned, scheds = add_default_schedules(doc)
    assert returned is doc
    _assert_fraction_limits(doc)
    assert set(scheds) == {
        "Always_On",
        "Always_Off",
        "Always On",
        "Always Off",
        "On",
        "Off",
        "AllOn",
        "AllOff",
        "AlwaysOn",
        "AlwaysOff",
    }
    for name, sched in scheds.items():
        assert doc["Schedule:Year"][name] is sched
        expected = 0 if "ff" in name else 1
        values = np.asarray(idfkit.schedules.values(sched, year=2018, document=doc))
        assert np.all(values == expected)


def _assert_fraction_limits(doc):
    limits = doc["ScheduleTypeLimits"]["Fraction"]
    assert len(doc["ScheduleTypeLimits"]) == 1
    assert (limits.lower_limit_value, limits.upper_limit_value) == (0, 1)
    assert limits.numeric_type == "Continuous"
    assert limits.unit_type == "Dimensionless"


def test_ensure_fraction_type_limits_is_idempotent(doc):
    """Asking twice yields the one object."""
    first = ensure_fraction_type_limits(doc)
    assert ensure_fraction_type_limits(doc) is first
    assert len(doc["ScheduleTypeLimits"]) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Sensible", "Sensible"), (None, "None"), (float("nan"), "None")],
)
def test_heat_recovery_type_reads_missing_as_none(value, expected):
    """Missing heat recovery (None or NaN from a spreadsheet) means "None"."""
    assert TypeAdapter(HeatRecoveryTypeType).validate_python(value) == expected


def test_literal_types_validate():
    """The literal types used by the domain models accept their values only."""
    assert (
        TypeAdapter(IdealLoadsLimitType).validate_python("LimitCapacity")
        == "LimitCapacity"
    )
    adapter = TypeAdapter(InfDesignFlowRateCalculationMethodType)
    assert adapter.validate_python("AirChanges/Hour") == "AirChanges/Hour"
    with pytest.raises(ValueError):
        adapter.validate_python("Flow/Parsec")
