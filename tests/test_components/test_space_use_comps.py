"""Test the space use components."""

import pytest
from idfkit import IDFDocument
from prisma import Prisma

from epinterface.sbem.components.schedules import YearComponent
from epinterface.sbem.components.space_use import (
    DimmingTypeType,
    EquipmentComponent,
    LightingComponent,
    OccupancyComponent,
    ThermostatComponent,
    WaterUseComponent,
    ZoneSpaceUseComponent,
)
from epinterface.sbem.exceptions import NotImplementedParameter
from epinterface.sbem.prisma.client import deep_fetcher


@pytest.fixture(scope="function")
def schedule(preseeded_readonly_db: Prisma):
    """Get the schedule name for the default zone."""
    _year, year_comp = deep_fetcher.Year.get_deep_object(
        "Lights_Year", preseeded_readonly_db
    )
    return year_comp


@pytest.mark.parametrize("is_on", [True, False])
def test_add_lighting_to_idf_zone(
    doc: IDFDocument, schedule: YearComponent, is_on: bool
):
    """Test the add_lighting_to_idf_zone method."""
    component_name = "new_office"
    schedule_name = schedule.Name
    zone_name = "some_zone"
    expected_idf_obj_name = f"{zone_name}_{component_name}_LIGHTS"
    # expected_schedule_name = f"{expected_idf_obj_name}_YEAR_{schedule_name}"
    expected_schedule_name = schedule_name

    lighting = LightingComponent(
        Name=component_name,
        PowerDensity=10,
        Schedule=schedule,
        IsOn=is_on,
        DimmingType="Off",
    )
    assert not doc["Lights"]
    assert not doc["Schedule:Year"]
    doc = lighting.add_lights_to_idf_zone(doc, zone_name)
    if is_on:
        assert doc["Lights"]
        assert next(iter(doc["Lights"])).name == expected_idf_obj_name
        assert next(iter(doc["Lights"])).schedule_name == expected_schedule_name
        assert (
            next(iter(doc["Lights"])).zone_or_zonelist_or_space_or_spacelist_name
            == zone_name
        )
        assert doc["Schedule:Year"]
        assert next(iter(doc["Schedule:Year"])).name == expected_schedule_name
    else:
        assert not doc["Lights"]
        assert not doc["Schedule:Year"]


@pytest.mark.parametrize("dimming_type", ["Stepped", "Continuous"])
def test_add_lighting_to_idf_zone_with_dimming(
    doc: IDFDocument, schedule: YearComponent, dimming_type: DimmingTypeType
):
    """Test the add_lighting_to_idf_zone method with dimming."""
    lighting = LightingComponent(
        Name="new_office",
        PowerDensity=10,
        Schedule=schedule,
        IsOn=True,
        DimmingType=dimming_type,
    )
    with pytest.raises(NotImplementedParameter):
        lighting.add_lights_to_idf_zone(doc, "default_zone")


@pytest.mark.parametrize("is_on,density", [(True, 10), (False, 0)])
def test_add_people_to_idf_zone(
    doc: IDFDocument, schedule: YearComponent, is_on: bool, density: float
):
    """Test the add_people_to_idf_zone method."""
    component_name = "new_office"
    schedule.Name = "some_people_schedule"
    schedule_name = schedule.Name
    zone_name = "default_zone"
    expected_idf_obj_name = f"{zone_name}_{component_name}_PEOPLE"
    # expected_schedule_name = f"{expected_idf_obj_name}_YEAR_{schedule_name}"
    expected_schedule_name = schedule_name
    expected_activity_schedule_name = f"{expected_idf_obj_name}_Activity_Schedule"

    occupancy = OccupancyComponent(
        Name=component_name,
        PeopleDensity=density,
        Schedule=schedule,
        IsOn=is_on,
        MetabolicRate=1.3,
    )

    assert not doc["People"]
    assert not doc["Schedule:Year"]
    doc = occupancy.add_people_to_idf_zone(doc, zone_name)
    if is_on:
        assert doc["People"]
        assert next(iter(doc["People"])).name == expected_idf_obj_name
        assert next(iter(doc["People"])).people_per_floor_area == density
        assert (
            next(iter(doc["People"])).number_of_people_schedule_name
            == expected_schedule_name
        )
        assert (
            next(iter(doc["People"])).zone_or_zonelist_or_space_or_spacelist_name
            == zone_name
        )
        assert doc["Schedule:Year"]
        assert doc["Schedule:Year"].get(expected_activity_schedule_name) is not None
        assert doc["Schedule:Year"].get(expected_schedule_name) is not None
    else:
        assert not doc["People"]


@pytest.mark.parametrize("is_on", [True, False])
def test_add_equipment_to_idf_zone(
    doc: IDFDocument, schedule: YearComponent, is_on: bool
):
    """Test the add_equipment_to_idf_zone method."""
    component_name = "new_office"
    schedule.Name = "some_equip_schedule"
    schedule_name = schedule.Name
    zone_name = "default_zone"
    expected_idf_obj_name = f"{zone_name}_{component_name}_EQUIPMENT"
    # expected_schedule_name = f"{expected_idf_obj_name}_YEAR_{schedule_name}"
    expected_schedule_name = schedule_name
    equipment = EquipmentComponent(
        Name=component_name,
        PowerDensity=10,
        Schedule=schedule,
        IsOn=is_on,
    )
    assert not doc["ElectricEquipment"]
    assert not doc["Schedule:Year"]
    doc = equipment.add_equipment_to_idf_zone(doc, zone_name)
    if is_on:
        assert doc["ElectricEquipment"]
        assert next(iter(doc["ElectricEquipment"])).name == expected_idf_obj_name
        assert (
            next(iter(doc["ElectricEquipment"])).schedule_name == expected_schedule_name
        )
        assert (
            next(
                iter(doc["ElectricEquipment"])
            ).zone_or_zonelist_or_space_or_spacelist_name
            == zone_name
        )
        assert doc["Schedule:Year"]
        assert next(iter(doc["Schedule:Year"])).name == expected_schedule_name
    else:
        assert not doc["ElectricEquipment"]


@pytest.mark.skip(reason="Not implemented")
def test_add_thermostat_to_idf_zone(doc: IDFDocument):
    """Test the add_thermostat_to_idf_zone method."""
    pass


@pytest.mark.skip(reason="Not implemented")
def test_add_water_to_idf_zone(doc: IDFDocument):
    """Test the add_water_to_idf_zone method."""
    pass


def test_add_space_use_to_idf_zone(doc: IDFDocument, schedule: YearComponent):
    """Test the add_loads_to_idf_zone method."""
    zone_name = "default_zone"

    space_use_name = "new_dense_office_controlled"

    lighting_component_name = "new_office"
    equipment_component_name = "office"
    occupancy_component_name = "dense_office"
    thermostat_component_name = "new_office_controlled"
    water_component_name = "new_office"

    expected_equip_name = f"{zone_name}_{equipment_component_name}_EQUIPMENT"
    expected_lighting_name = f"{zone_name}_{lighting_component_name}_LIGHTS"
    expected_occupancy_name = f"{zone_name}_{occupancy_component_name}_PEOPLE"

    equip_schedule_name = "some_equip_schedule"
    lighting_schedule_name = "some_light_schedule"
    occupancy_schedule_name = "some_occupancy_schedule"
    water_schedule_name = "some_water_schedule"
    heating_schedule_name = "some_heating_schedule"
    cooling_schedule_name = "some_cooling_schedule"

    equip_schedule = schedule.model_copy(
        deep=True, update={"Name": equip_schedule_name}
    )
    light_schedule = schedule.model_copy(
        deep=True, update={"Name": lighting_schedule_name}
    )
    occupancy_schedule = schedule.model_copy(
        deep=True, update={"Name": occupancy_schedule_name}
    )
    heating_schedule = schedule.model_copy(
        deep=True, update={"Name": heating_schedule_name}
    )
    cooling_schedule = schedule.model_copy(
        deep=True, update={"Name": cooling_schedule_name}
    )
    water_schedule = schedule.model_copy(
        deep=True, update={"Name": water_schedule_name}
    )

    # expected_lighting_schedule_name = (
    #     f"{expected_lighting_name}_YEAR_{lighting_schedule_name}"
    # )
    # expected_equipment_schedule_name = (
    #     f"{expected_equip_name}_YEAR_{equip_schedule_name}"
    # )
    # expected_occupancy_schedule_name = (
    #     f"{expected_occupancy_name}_YEAR_{occupancy_schedule_name}"
    # )
    # _expected_heating_schedule_name = (
    #     f"{expected_thermostat_name}_YEAR_{heating_schedule_name}"
    # )
    # _expected_cooling_schedule_name = (
    #     f"{expected_thermostat_name}_YEAR_{cooling_schedule_name}"
    # )
    # _expected_water_schedule_name = f"{expected_water_name}_YEAR_{water_schedule_name}"
    expected_lighting_schedule_name = lighting_schedule_name
    expected_equipment_schedule_name = equip_schedule_name
    expected_occupancy_schedule_name = occupancy_schedule_name
    # expected_heating_schedule_name = heating_schedule_name
    # expected_cooling_schedule_name = cooling_schedule_name
    # expected_water_schedule_name = water_schedule_name

    lighting = LightingComponent(
        Name=lighting_component_name,
        PowerDensity=10,
        Schedule=light_schedule,
        IsOn=True,
        DimmingType="Off",
    )
    equipment = EquipmentComponent(
        Name=equipment_component_name,
        PowerDensity=10,
        Schedule=equip_schedule,
        IsOn=True,
    )
    occupancy = OccupancyComponent(
        Name=occupancy_component_name,
        PeopleDensity=10,
        Schedule=occupancy_schedule,
        IsOn=True,
        MetabolicRate=1.3,
    )
    thermostat = ThermostatComponent(
        Name=thermostat_component_name,
        HeatingSetpoint=20,
        CoolingSetpoint=25,
        HeatingSchedule=heating_schedule,
        CoolingSchedule=cooling_schedule,
        IsOn=True,
    )
    water = WaterUseComponent(
        Name=water_component_name,
        FlowRatePerPerson=0.001,
        Schedule=water_schedule,
    )
    space_use = ZoneSpaceUseComponent(
        Name=space_use_name,
        Lighting=lighting,
        Equipment=equipment,
        Occupancy=occupancy,
        Thermostat=thermostat,
        WaterUse=water,
    )

    assert not doc["Lights"]
    assert not doc["ElectricEquipment"]
    assert not doc["People"]
    assert not doc["HVACTemplate:Thermostat"]
    assert not doc["Schedule:Year"]
    assert not doc["WaterUse:Equipment"]

    doc = space_use.add_loads_to_idf_zone(doc, zone_name)

    assert doc["Lights"]
    assert doc["ElectricEquipment"]
    assert doc["People"]
    assert doc["Schedule:Year"]

    lights_obj = doc["Lights"].get(expected_lighting_name)
    equip_obj = doc["ElectricEquipment"].get(expected_equip_name)
    occupancy_obj = doc["People"].get(expected_occupancy_name)
    assert lights_obj is not None
    assert lights_obj.name == expected_lighting_name
    assert lights_obj.schedule_name == expected_lighting_schedule_name
    assert equip_obj is not None
    assert equip_obj.name == expected_equip_name
    assert equip_obj.schedule_name == expected_equipment_schedule_name
    assert occupancy_obj is not None
    assert occupancy_obj.name == expected_occupancy_name
    assert (
        occupancy_obj.number_of_people_schedule_name == expected_occupancy_schedule_name
    )

    assert doc["Schedule:Year"].get(expected_lighting_schedule_name) is not None
    assert doc["Schedule:Year"].get(expected_equipment_schedule_name) is not None
    assert doc["Schedule:Year"].get(expected_occupancy_schedule_name) is not None


# TODO: test with spaces/invalid chars in names
# TODO: test with incorrect schedule types


def test_shared_schedule_across_zones_does_not_duplicate(
    doc: IDFDocument, schedule: YearComponent
):
    """Two zones using one schedule reuse its year/week/day/limits objects."""
    lighting = LightingComponent(
        Name="shared",
        PowerDensity=10,
        Schedule=schedule,
        IsOn=True,
        DimmingType="Off",
    )
    doc = lighting.add_lights_to_idf_zone(doc, "zone_a")
    n_days = len(doc["Schedule:Day:Hourly"])
    doc = lighting.add_lights_to_idf_zone(doc, "zone_b")

    assert len(doc["Lights"]) == 2
    assert len(doc["Schedule:Year"]) == 1
    assert len(doc["Schedule:Day:Hourly"]) == n_days
    assert len(doc["ScheduleTypeLimits"]) == len({
        lim.name for lim in doc["ScheduleTypeLimits"]
    })
