"""Tests for the legacy IDF object writers on idfkit documents."""

import idfkit
import numpy as np
import pytest

from epinterface.interface import (
    AirGapMaterial,
    Construction,
    ElectricEquipment,
    HVACTemplateThermostat,
    HVACTemplateZoneIdealLoadsAirSystem,
    InternalMass,
    Lights,
    NoMassMaterial,
    People,
    RunPeriod,
    ScheduleDayHourly,
    ScheduleTypeLimits,
    ScheduleWeekDaily,
    ScheduleYear,
    SimpleGlazingMaterial,
    SimulationControl,
    SiteGroundTemperature,
    SizingParameters,
    Timestep,
    WaterUseEquipment,
    ZoneInfiltrationDesignFlowRate,
    ZoneList,
    ZoneVentilationWindAndStackOpenArea,
    add_constant_schedule,
    add_default_schedules,
    add_default_sim_controls,
    stucco,
)


def test_add_returns_the_document(doc):
    """Writers hand back the document they were given."""
    assert ZoneList(Names=["A"], Name="L").add(doc) is doc


def test_zone_list_writes_object(doc):
    """Zone names land in the extensible zones, blanks dropped."""
    ZoneList(Names=["A", "B", ""], Name="L").add(doc)
    assert [z.zone_name for z in doc["ZoneList"]["L"].zones] == ["A", "B"]


def test_simulation_control_run_period_timestep(doc):
    """Nameless singleton objects are written with their fields."""
    SimulationControl(Do_Plant_Sizing_Calculation="No").add(doc)
    RunPeriod(
        Name="Year",
        Begin_Month=1,
        Begin_Day_of_Month=1,
        End_Month=12,
        End_Day_of_Month=31,
        Day_of_Week_for_Start_Day="Sunday",
    ).add(doc)
    Timestep(Number_of_Timesteps_per_Hour=4).add(doc)
    control = doc["SimulationControl"].first()
    assert control.do_zone_sizing_calculation == "Yes"
    assert control.do_plant_sizing_calculation == "No"
    period = doc["RunPeriod"]["Year"]
    assert (period.end_month, period.end_day_of_month) == (12, 31)
    assert period.day_of_week_for_start_day == "Sunday"
    assert doc["Timestep"].first().number_of_timesteps_per_hour == 4


def test_singleton_types_replace_existing_object(doc):
    """Minimal.idf already has Sizing:Parameters and ground temperatures."""
    SizingParameters(Heating_Sizing_Factor=1.3, Cooling_Sizing_Factor=1.4).add(doc)
    SiteGroundTemperature.FromValues(list(range(12))).add(doc)
    assert len(doc["Sizing:Parameters"]) == 1
    sizing = doc["Sizing:Parameters"].first()
    assert (sizing.heating_sizing_factor, sizing.cooling_sizing_factor) == (1.3, 1.4)
    assert len(doc["Site:GroundTemperature:BuildingSurface"]) == 1
    ground = doc["Site:GroundTemperature:BuildingSurface"].first()
    assert (ground.january_ground_temperature, ground.december_ground_temperature) == (
        0,
        11,
    )


def test_add_default_sim_controls(doc):
    """The default controls write all four objects."""
    assert add_default_sim_controls(doc) is doc
    assert (
        doc["SimulationControl"].first().maximum_number_of_hvac_sizing_simulation_passes
        == 2
    )
    assert doc["RunPeriod"]["Year"].begin_month == 1
    assert doc["Timestep"].first().number_of_timesteps_per_hour == 6
    assert doc["Sizing:Parameters"].first().heating_sizing_factor == 1.15


def test_construction_writes_layers_in_order(doc):
    """Layers are written as materials and referenced outside-in."""
    Construction(
        name="Wall",
        layers=[
            stucco.as_layer(0.03),
            AirGapMaterial(Name="Gap", Thermal_Resistance=0.18),
            NoMassMaterial(Name="Skin", Roughness="Smooth", Thermal_Resistance=1.0),
        ],
    ).add(doc)
    wall = doc["Construction"]["Wall"]
    assert [wall.outside_layer, wall.layer_2, wall.layer_3] == [
        "Stucco_0.03m",
        "Gap",
        "Skin",
    ]
    material = doc["Material"]["Stucco_0.03m"]
    assert material.thickness == 0.03
    assert material.conductivity == 0.721
    assert material.roughness == "MediumSmooth"
    assert doc["Material:AirGap"]["Gap"].thermal_resistance == 0.18
    assert doc["Material:NoMass"]["Skin"].roughness == "Smooth"


def test_simple_glazing_material(doc):
    """UFactor maps onto the schema's u_factor."""
    SimpleGlazingMaterial(
        Name="Glz",
        UFactor=2.7,
        Solar_Heat_Gain_Coefficient=0.6,
        Visible_Transmittance=0.7,
    ).add(doc)
    glazing = doc["WindowMaterial:SimpleGlazingSystem"]["Glz"]
    assert glazing.u_factor == 2.7
    assert glazing.solar_heat_gain_coefficient == 0.6
    assert glazing.visible_transmittance == 0.7


def test_construction_extract_round_trips(doc):
    """Constructions read back with their layer definitions."""
    glazing = SimpleGlazingMaterial(
        Name="Glz",
        UFactor=2.7,
        Solar_Heat_Gain_Coefficient=0.6,
        Visible_Transmittance=0.7,
    )
    original = Construction(name="Wall", layers=[stucco.as_layer(0.03)])
    original.add(doc)
    Construction(name="Window", layers=[glazing]).add(doc)
    extracted = {c.name: c for c in Construction.extract(doc)}
    assert extracted["Wall"].layers == original.layers
    assert extracted["Window"].layers == [glazing]
    assert extracted["Wall"].r_value == pytest.approx(original.r_value)


def test_extract_reads_objects_back(doc):
    """BaseObj.extract returns the class instances for every object of its type."""
    lights = Lights(
        Name="Lt",
        Zone_or_ZoneList_Name="Z",
        Schedule_Name="S",
        Watts_per_Zone_Floor_Area=4.0,
    )
    lights.add(doc)
    assert list(Lights.extract(doc)) == [lights]


def test_internal_mass(doc):
    """InternalMass writes its zone, construction and area."""
    InternalMass(
        Name="Mass", Zone_or_ZoneList_Name="Z", Construction_Name="C", Surface_Area=12.5
    ).add(doc)
    mass = doc["InternalMass"]["Mass"]
    assert mass.construction_name == "C"
    assert mass.surface_area == 12.5


def test_people_writes_zone_and_density(doc):
    """People maps the long zone field and sets the density."""
    People(
        Name="People",
        Zone_or_ZoneList_Name="L",
        Number_of_People_Schedule_Name="Occ",
        Activity_Level_Schedule_Name="Act",
        Number_of_People_Calculation_Method="People/Area",
        People_per_Floor_Area=0.05,
    ).add(doc)
    people = doc["People"]["People"]
    assert people.zone_or_zonelist_or_space_or_spacelist_name == "L"
    assert people.number_of_people_schedule_name == "Occ"
    assert people.activity_level_schedule_name == "Act"
    assert people.people_per_floor_area == 0.05
    assert people.number_of_people is None


def test_lights_and_equipment_use_floor_area_field(doc):
    """Watts/Area loads land in watts_per_floor_area (EnergyPlus >= 24)."""
    Lights(
        Name="Lt",
        Zone_or_ZoneList_Name="L",
        Schedule_Name="S",
        Watts_per_Zone_Floor_Area=4,
    ).add(doc)
    ElectricEquipment(
        Name="Eq",
        Zone_or_ZoneList_Name="L",
        Schedule_Name="S",
        Watts_per_Zone_Floor_Area=9,
    ).add(doc)
    lights = doc["Lights"]["Lt"]
    assert lights.zone_or_zonelist_or_space_or_spacelist_name == "L"
    assert lights.watts_per_floor_area == 4
    assert lights.fraction_radiant == 0.42
    equipment = doc["ElectricEquipment"]["Eq"]
    assert equipment.watts_per_floor_area == 9
    assert equipment.fraction_radiant == 0.2


def test_infiltration(doc):
    """Infiltration writes the method and the coefficients."""
    ZoneInfiltrationDesignFlowRate(
        Name="Inf",
        Zone_or_ZoneList_Name="L",
        Schedule_Name="On",
        Design_Flow_Rate_Calculation_Method="AirChanges/Hour",
        Air_Changes_per_Hour=0.5,
    ).add(doc)
    inf = doc["ZoneInfiltration:DesignFlowRate"]["Inf"]
    assert inf.design_flow_rate_calculation_method == "AirChanges/Hour"
    assert inf.air_changes_per_hour == 0.5
    assert inf.constant_term_coefficient == 1


def test_ventilation_wind_and_stack(doc):
    """The ventilation object keeps its name and open area."""
    ZoneVentilationWindAndStackOpenArea(
        Name="Vent",
        Zone_or_Space_Name="Z",
        Opening_Area=1.5,
        Opening_Area_Fraction_Schedule_Name="On",
        Height_Difference=2,
    ).add(doc)
    vent = doc["ZoneVentilation:WindandStackOpenArea"]["Vent"]
    assert vent.opening_area == 1.5
    assert vent.maximum_wind_speed == 40


def test_water_use_equipment(doc):
    """Water use equipment keeps its flow and schedule."""
    WaterUseEquipment(
        Name="DHW",
        Peak_Flow_Rate=0.0001,
        Flow_Rate_Fraction_Schedule_Name="On",
        EndUse_Subcategory="Hot water",
    ).add(doc)
    water = doc["WaterUse:Equipment"]["DHW"]
    assert water.peak_flow_rate == 0.0001
    assert water.end_use_subcategory == "Hot water"


def test_hvac_template_objects(doc):
    """Thermostat and ideal loads templates write their setpoints and zone."""
    thermostat = HVACTemplateThermostat(
        Name="Tstat", Constant_Heating_Setpoint=19, Constant_Cooling_Setpoint=24
    )
    thermostat.add(doc)
    HVACTemplateZoneIdealLoadsAirSystem(
        Zone_Name="Z", Template_Thermostat_Name=thermostat.Name
    ).add(doc)
    stat = doc["HVACTemplate:Thermostat"]["Tstat"]
    assert (stat.constant_heating_setpoint, stat.constant_cooling_setpoint) == (19, 24)
    ideal = doc["HVACTemplate:Zone:IdealLoadsAirSystem"].first()
    assert ideal.zone_name == "Z"
    assert ideal.template_thermostat_name == "Tstat"
    assert ideal.heat_recovery_type == "None"
    assert ideal.maximum_heating_supply_air_temperature == 30


def test_schedule_objects(doc):
    """Type limits, day, week and year schedules reference each other."""
    ScheduleTypeLimits(
        Name="Lim", Lower_Limit_Value=0, Upper_Limit_Value=10, Numeric_Type="Continuous"
    ).add(doc)
    ScheduleDayHourly(
        Name="Day",
        Schedule_Type_Limits_Name="Lim",
        **{f"Hour_{h}": h for h in range(1, 25)},
    ).add(doc)
    ScheduleWeekDaily(
        Name="Week",
        Monday_ScheduleDay_Name="Day",
        Tuesday_ScheduleDay_Name="Day",
        Wednesday_ScheduleDay_Name="Day",
        Thursday_ScheduleDay_Name="Day",
        Friday_ScheduleDay_Name="Day",
        Saturday_ScheduleDay_Name="Day",
        Sunday_ScheduleDay_Name="Day",
    ).add(doc)
    ScheduleYear(
        Name="Year",
        Schedule_Type_Limits_Name="Lim",
        ScheduleWeek_Name_1="Week",
        Start_Month_1=1,
        Start_Day_1=1,
        End_Month_1=6,
        End_Day_1=30,
        ScheduleWeek_Name_2="Week",
        Start_Month_2=7,
        Start_Day_2=1,
        End_Month_2=12,
        End_Day_2=31,
    ).add(doc)
    assert doc["ScheduleTypeLimits"]["Lim"].upper_limit_value == 10
    day = doc["Schedule:Day:Hourly"]["Day"]
    assert (day.hour_1, day.hour_24) == (1, 24)
    week = doc["Schedule:Week:Daily"]["Week"]
    assert week.monday_schedule_day_name == "Day"
    assert week.summerdesignday_schedule_day_name == "Day"
    assert week.holiday_schedule_day_name == "Day"
    year = doc["Schedule:Year"]["Year"]
    assert [(w["schedule_week_name"], w["end_month"]) for w in year.schedule_weeks] == [
        ("Week", 6),
        ("Week", 12),
    ]
    assert np.allclose(
        idfkit.schedules.values(year, year=2018, document=doc),
        np.tile(np.arange(1, 25), 365),
    )


def test_constant_schedule_uses_archetypal_object_names(doc):
    """A constant schedule is a Year/Week/Day chain with the legacy names."""
    year = add_constant_schedule(doc, "Always_On", 1)
    assert year.schedule_type_limits_name == "Fraction"
    assert doc["Schedule:Week:Daily"]["w_Always_On_00"] is not None
    assert doc["Schedule:Day:Hourly"]["d_Always_On_00"].hour_12 == 1
    values = idfkit.schedules.values(year, year=2018, document=doc)
    assert np.all(np.asarray(values) == 1)


def test_add_default_schedules_names(doc):
    """The ten protected on/off schedules exist with their values."""
    returned, scheds = add_default_schedules(doc)
    assert returned is doc
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
