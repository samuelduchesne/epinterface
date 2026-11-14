"""EnergyPlus literal types, a small material library and document helpers.

Objects are written with idfkit directly (`doc.add`, or
`epinterface.document.add_or_replace` for shared objects), using idfkit's
snake_case field names.
"""

from typing import Annotated, Any, Literal

import numpy as np
from idfkit import IDFObject, create_schedule_type_limits
from pydantic import BaseModel, BeforeValidator, Field

from epinterface.document import EPDocument, add_or_replace
from epinterface.schedules import HOURS_PER_YEAR, add_values_schedule

IdealLoadsLimitType = Literal[
    "NoLimit", "LimitFlowRate", "LimitCapacity", "LimitFlowRateAndCapacity"
]


DehumidificationControlTypeType = Literal[
    "ConstantSensibleHeatRatio", "Humidistat", "None", "ConstantSupplyHumidityRatio"
]


HumidificationControlTypeType = Literal[
    "None", "Humidistat", "ConstantSupplyHumidityRatio"
]


OutdoorAirMethodType = Literal[
    "None",
    "Flow/Person",
    "Flow/Area",
    "Flow/Zone",
    "Sum",
    "Maximum",
    "DetailedSpecification",
]


DemandControlledVentilationTypeType = Literal[
    "None", "OccupancySchedule", "CO2Setpoint"
]
OutdoorAirEconomizerTypeType = Literal[
    "NoEconomizer", "DifferentialDryBulb", "DifferentialEnthalpy"
]


HeatRecoveryTypeType = Annotated[
    Literal["None", "Sensible", "Enthalpy"],
    BeforeValidator(
        lambda x: (
            x
            if isinstance(x, str)
            else ("None" if x is None else ("None" if np.isnan(x) else x))
        )
    ),
]

ThermostatType = Literal[
    "SingleHeating", "SingleCooling", "SingleHeatingOrCooling", "DualSetpoint"
]


DesignLevelCalculationMethodType = Literal["Watts/Area", "Watts/Person", "Watts"]


InfDesignFlowRateCalculationMethodType = Literal[
    "Flow/Zone",
    "Flow/Area",
    "Flow/ExteriorArea",
    "Flow/ExteriorWallArea",
    "AirChanges/Hour",
]
VentDesignFlowRateCalculationMethodType = Literal[
    "Flow/Zone", "Flow/Area", "Flow/Person", "AirChanges/Hour"
]

VentilationType = Literal["Natural", "Exhaust", "Intake", "Balanced"]


NumberOfPeopleCalculationMethodType = Literal["People", "People/Area", "Area/Person"]


class BaseMaterial(BaseModel, extra="ignore", populate_by_name=True):
    """A base material object for storing material definitions.

    Note that this is not an EnergyPlus object: it is library data, written as a
    `Material` object once given a thickness (see `add_layer_to_idf`).
    """

    Name: str
    Roughness: str
    Conductivity: float = Field(..., ge=0, validation_alias="Conductivity [W/m.K]")
    Density: float = Field(..., ge=0, validation_alias="Density [kg/m3]")
    Specific_Heat: float = Field(..., ge=0, validation_alias="SpecificHeat [J/kg.K]")
    Thermal_Absorptance: float | None = Field(
        default=None, validation_alias="ThermalAbsorptance [0-1]", ge=0, le=1
    )
    Solar_Absorptance: float | None = Field(
        default=None, validation_alias="SolarAbsorptance [0-1]", ge=0, le=1
    )
    Visible_Absorptance: float | None = Field(
        default=None, validation_alias="VisibleAbsorptance [0-1]", ge=0, le=1
    )

    def layer_name(self, thickness: float) -> str:
        """The name of this material's `Material` object at `thickness` [m]."""
        return f"{self.Name}_{thickness}m"

    def add_layer_to_idf(self, doc: EPDocument, thickness: float) -> IDFObject:
        """Write this material as a `Material` object of the given thickness.

        An identical layer already in the document is reused (see
        `epinterface.document.add_or_replace`).

        Args:
            doc (EPDocument): The IDF document to write to.
            thickness (float): The thickness of the layer [m].

        Returns:
            IDFObject: The `Material` object, named `layer_name(thickness)`.
        """
        return add_or_replace(
            doc,
            "Material",
            self.layer_name(thickness),
            roughness=self.Roughness,
            thickness=thickness,
            conductivity=self.Conductivity,
            density=self.Density,
            specific_heat=self.Specific_Heat,
            thermal_absorptance=self.Thermal_Absorptance,
            solar_absorptance=self.Solar_Absorptance,
            visible_absorptance=self.Visible_Absorptance,
        )


wood = BaseMaterial(
    # also see:
    # https://www.engineersedge.com/heat_transfer/thermal_properties_13785.htm
    # https://www.researchgate.net/figure/Specific-heat-and-density-of-the-wood-stud-composite-layer-advanced-framing_tbl5_332911394
    # https://thermalenvelope.ca/pdf/material_data_sheet_8.6.2.pdf?version=v1.7.3
    Name="Wood",
    Roughness="MediumSmooth",
    Density=540,
    Conductivity=0.12,
    Specific_Heat=1210,
    Thermal_Absorptance=0.9,
    Solar_Absorptance=0.7,
    Visible_Absorptance=0.7,
)
gypsum = BaseMaterial(
    Name="Gypsum",
    Roughness="Rough",
    Conductivity=0.15862,
    Density=640,
    Specific_Heat=1129.6,
    Thermal_Absorptance=0.9,
    Solar_Absorptance=0.4,
    Visible_Absorptance=0.1,
)
drywall = BaseMaterial(
    Name="Drywall",
    Roughness="MediumSmooth",
    Conductivity=0.16009,
    Density=800,
    Specific_Heat=1087.8,
)
osb = BaseMaterial(
    Name="OSB",
    Roughness="MediumSmooth",
    Conductivity=0.1163,
    Density=544,
    Specific_Heat=1213,
)
concrete = BaseMaterial(
    Name="Concrete",
    Roughness="Rough",
    Conductivity=1.312098,
    Density=2242,
    Specific_Heat=465.2,
)
insulation = BaseMaterial(
    Name="Insulation",
    Roughness="MediumRough",
    Conductivity=0.04,
    Density=32,
    Specific_Heat=836,
    Thermal_Absorptance=0.9,
    Solar_Absorptance=0.7,
    Visible_Absorptance=0.7,
)
stucco = BaseMaterial(
    Name="Stucco",
    Roughness="MediumSmooth",
    Conductivity=0.721,
    Density=1865,
    Specific_Heat=878,
)


class DefaultMaterialLibrary(BaseModel):
    """Default material library for storing some common material defs."""

    wood: BaseMaterial = wood
    gypsum: BaseMaterial = gypsum
    drywall: BaseMaterial = drywall
    osb: BaseMaterial = osb
    concrete: BaseMaterial = concrete
    insulation: BaseMaterial = insulation
    stucco: BaseMaterial = stucco


# The defaults epinterface writes for `HVACTemplate:Zone:IdealLoadsAirSystem`
# (those of the former `HVACTemplateZoneIdealLoadsAirSystem` model).
_IDEAL_LOADS_TEMPLATE_DEFAULTS: dict[str, float | str] = {
    "maximum_heating_supply_air_temperature": 30.0,
    "minimum_cooling_supply_air_temperature": 18.0,
    "maximum_heating_supply_air_humidity_ratio": 0.0156,
    "minimum_cooling_supply_air_humidity_ratio": 0.0077,
    "heating_limit": "NoLimit",
    "cooling_limit": "NoLimit",
    "dehumidification_control_type": "None",
    "cooling_sensible_heat_ratio": 0.7,
    "dehumidification_setpoint": 60.0,
    "humidification_control_type": "None",
    "humidification_setpoint": 30.0,
    "outdoor_air_method": "None",
    "outdoor_air_flow_rate_per_person": 0.00944,
    "outdoor_air_flow_rate_per_zone_floor_area": 0.00025,
    "outdoor_air_flow_rate_per_zone": 0.0,
    "demand_controlled_ventilation_type": "None",
    "outdoor_air_economizer_type": "NoEconomizer",
    "heat_recovery_type": "None",
    "sensible_heat_recovery_effectiveness": 0.7,
    "latent_heat_recovery_effectiveness": 0.65,
}


def add_ideal_loads_template(
    doc: EPDocument, zone_name: str, thermostat_name: str, **fields: Any
) -> IDFObject:
    """Write a `HVACTemplate:Zone:IdealLoadsAirSystem` for a zone.

    Fields not given take epinterface's defaults; a field given as None is left
    blank. The template has no name, so it is always added (never reused).

    Args:
        doc (EPDocument): The IDF document to write to.
        zone_name (str): The zone the template conditions.
        thermostat_name (str): The `HVACTemplate:Thermostat` it uses.
        **fields (Any): Fields that override the defaults, by idfkit name.

    Returns:
        IDFObject: The `HVACTemplate:Zone:IdealLoadsAirSystem` object.
    """
    return add_or_replace(
        doc,
        "HVACTemplate:Zone:IdealLoadsAirSystem",
        "",
        zone_name=zone_name,
        template_thermostat_name=thermostat_name,
        **(_IDEAL_LOADS_TEMPLATE_DEFAULTS | fields),
    )


def add_default_sim_controls(doc: EPDocument) -> EPDocument:
    """Helper to add default simulation controls to the IDF model.

    Writes (replacing any existing ones) `SimulationControl`, a `RunPeriod`
    named "Year" over the whole year starting on a Sunday, a 6 per hour
    `Timestep` and 1.15 heating/cooling `Sizing:Parameters`.

    Args:
        doc (EPDocument): The IDF model to add the simulation controls to.

    Returns:
        EPDocument: The IDF model with the added simulation controls.
    """
    add_or_replace(
        doc,
        "SimulationControl",
        do_zone_sizing_calculation="Yes",
        do_system_sizing_calculation="Yes",
        do_plant_sizing_calculation="No",
        run_simulation_for_sizing_periods="Yes",
        run_simulation_for_weather_file_run_periods="Yes",
        do_hvac_sizing_simulation_for_sizing_periods="Yes",
        maximum_number_of_hvac_sizing_simulation_passes=2,
    )
    add_or_replace(
        doc,
        "RunPeriod",
        "Year",
        begin_month=1,
        begin_day_of_month=1,
        end_month=12,
        end_day_of_month=31,
        day_of_week_for_start_day="Sunday",
        use_weather_file_holidays_and_special_days="No",
        use_weather_file_daylight_saving_period="No",
        apply_weekend_holiday_rule="Yes",
        use_weather_file_rain_indicators="No",
        use_weather_file_snow_indicators="No",
    )
    add_or_replace(doc, "Timestep", number_of_timesteps_per_hour=6)
    add_or_replace(
        doc,
        "Sizing:Parameters",
        heating_sizing_factor=1.15,
        cooling_sizing_factor=1.15,
    )
    return doc


_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def add_site_ground_temperature(doc: EPDocument, values: list[float]) -> IDFObject:
    """Write `Site:GroundTemperature:BuildingSurface` from 12 monthly values.

    The document holds one such object; an existing one is replaced.

    Args:
        doc (EPDocument): The IDF document to write to.
        values (list[float]): The ground temperatures [degC], January first.

    Returns:
        IDFObject: The `Site:GroundTemperature:BuildingSurface` object.

    Raises:
        ValueError: If `values` does not hold exactly 12 values.
    """
    if len(values) != 12:
        raise ValueError(f"GROUNDTEMP:EXPECTED_12:RECEIVED_{len(values)}")
    return add_or_replace(
        doc,
        "Site:GroundTemperature:BuildingSurface",
        **{
            f"{month}_ground_temperature": float(value)
            for month, value in zip(_MONTHS, values, strict=True)
        },
    )


def add_zone_list(doc: EPDocument, name: str, zone_names: list[str]) -> IDFObject:
    """Write a `ZoneList` of the (non-empty) `zone_names`.

    Args:
        doc (EPDocument): The IDF document to write to.
        name (str): The name of the zone list.
        zone_names (list[str]): The zones in the list; empty names are skipped.

    Returns:
        IDFObject: The `ZoneList` object.
    """
    return add_or_replace(
        doc, "ZoneList", name, zones=[{"zone_name": z} for z in zone_names if z]
    )


def zone_list_names(zone_list: IDFObject) -> list[str]:
    """The zone names of a `ZoneList` object, in order."""
    return [group["zone_name"] for group in zone_list.to_dict().get("zones", [])]


def ensure_fraction_type_limits(doc: EPDocument) -> IDFObject:
    """Return the `Fraction` ScheduleTypeLimits, creating it (0 to 1) if missing.

    archetypal wrote this object together with every schedule that used it.
    """
    if "Fraction" in doc["ScheduleTypeLimits"]:
        return doc["ScheduleTypeLimits"]["Fraction"]
    return create_schedule_type_limits(
        doc, "Fraction", 0, 1, "Continuous", "Dimensionless"
    )


def add_constant_schedule(
    doc: EPDocument, name: str, value: float, type_limits: str = "Fraction"
) -> IDFObject:
    """Add a constant schedule as `Schedule:Year`/`Week:Daily`/`Day:Hourly` objects.

    Args:
        doc (EPDocument): The IDF document to add the schedule to.
        name (str): The name of the `Schedule:Year`.
        value (float): The value held all year.
        type_limits (str): The name of an existing `ScheduleTypeLimits`.

    Returns:
        IDFObject: The `Schedule:Year` object.
    """
    if type_limits == "Fraction":
        ensure_fraction_type_limits(doc)
    return add_values_schedule(doc, name, [value] * HOURS_PER_YEAR, type_limits)


DEFAULT_CONSTANT_SCHEDULE_PAIRS = (
    ("Always_On", "Always_Off"),
    ("Always On", "Always Off"),
    ("On", "Off"),
    ("AllOn", "AllOff"),
    ("AlwaysOn", "AlwaysOff"),
)


def add_default_schedules(doc: EPDocument) -> tuple[EPDocument, dict[str, IDFObject]]:
    """Helper to add default schedules to the IDF model.

    Args:
        doc (EPDocument): The IDF model to add the schedules to.

    Returns:
        doc (EPDocument): The IDF model with the added schedules.
        scheds (dict[str, IDFObject]): The added `Schedule:Year` objects by name.
    """
    all_scheds: dict[str, IDFObject] = {}
    for on_name, off_name in DEFAULT_CONSTANT_SCHEDULE_PAIRS:
        all_scheds[on_name] = add_constant_schedule(doc, on_name, 1)
        all_scheds[off_name] = add_constant_schedule(doc, off_name, 0)
    return doc, all_scheds


PROTECTED_SCHEDULE_NAMES = {
    "Always_On",
    "Always_Off",
    "Always On",
    "Always Off",
    "AlwaysOn",
    "AlwaysOff",
    "On",
    "Off",
    "AllOn",
    "AllOff",
}
