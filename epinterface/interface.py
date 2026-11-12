"""Interface for EnergyPlus IDF objects."""

from collections.abc import Iterable, Sequence
from logging import getLogger
from typing import Annotated, Any, ClassVar, Literal

import numpy as np
from idfkit import IDFDocument, IDFObject
from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from epinterface.schedules import HOURS_PER_YEAR, add_values_schedule

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self  # noqa: UP035

logger = getLogger(__name__)


# idfkit names fields after the schema; the classes below keep their long-standing
# (EnergyPlus-IDD style) names. Where the two differ beyond case, the candidates
# are tried in order and the first one the document's schema knows is used.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "Zone_or_ZoneList_Name": (
        "zone_or_zonelist_or_space_or_spacelist_name",
        "zone_or_zonelist_name",
    ),
    "Watts_per_Zone_Floor_Area": ("watts_per_floor_area", "watts_per_zone_floor_area"),
    "EndUse_Subcategory": ("end_use_subcategory", "enduse_subcategory"),
    "UFactor": ("u_factor",),
    **{
        f"{day}_ScheduleDay_Name": (f"{day.lower()}_schedule_day_name",)
        for day in (
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
            "Holiday",
            "SummerDesignDay",
            "WinterDesignDay",
            "CustomDay1",
            "CustomDay2",
        )
    },
}


def _idf_field_names(
    doc: IDFDocument, obj_type: str, names: Iterable[str]
) -> dict[str, str]:
    """Map class field names to the field names idfkit uses for `obj_type`."""
    known = set(doc.schema.get_all_field_names(obj_type)) if doc.schema else set()
    mapping: dict[str, str] = {}
    for name in names:
        candidates = (*_FIELD_ALIASES.get(name, ()), name.lower())
        mapping[name] = next((c for c in candidates if c in known), name.lower())
    return mapping


def _add_object(
    doc: IDFDocument, obj_type: str, data: dict[str, Any], **extra_fields: Any
) -> IDFObject:
    """Write one object; unset (None) fields are left blank.

    A type EnergyPlus allows only once (e.g. `Timestep`) replaces the object
    already in the document, so the result holds a single, current definition.
    """
    data = {k: v for k, v in data.items() if v is not None}
    name = data.pop("Name", "")
    mapping = _idf_field_names(doc, obj_type, data)
    fields = {mapping[k]: v for k, v in data.items()} | extra_fields
    obj_schema = doc.schema.get_object_schema(obj_type) if doc.schema else None
    if obj_schema and obj_schema.get("maxProperties") == 1:
        for existing in list(doc[obj_type]):
            doc.removeidfobject(existing)
    return doc.add(obj_type, name, fields)


class BaseObj(BaseModel):
    """Base class for EnergyPlus IDF objects.

    The class should be inherited by all EnergyPlus IDF objects. It provides
    methods to add and extract objects from an IDF document.
    """

    key: ClassVar[str]

    def add(self, doc: IDFDocument):
        """Add the object to the IDF document.

        Args:
            doc (IDFDocument): The IDF document to add the object to.

        Returns:
            doc (IDFDocument): The updated IDF document.
        """
        _add_object(doc, self.key, self.model_dump())
        return doc

    @classmethod
    def _from_idf_object(cls, doc: IDFDocument, obj: IDFObject) -> Self:
        """Build an instance from an idfkit object."""
        fields = [f for f in cls.model_fields if f != "Name"]
        values = obj.to_dict()
        data: dict[str, Any] = {}
        if "Name" in cls.model_fields:
            data["Name"] = obj.name
        for field, idf_name in _idf_field_names(doc, cls.key, fields).items():
            if values.get(idf_name) not in (None, ""):
                data[field] = values[idf_name]
        return cls(**data)

    @classmethod
    def extract(cls, doc: IDFDocument) -> Sequence[Self]:
        """Extract objects from an IDF document.

        Args:
            doc (IDFDocument): The IDF document to extract objects from.

        Returns:
            objs (list[BaseObj]): A list of objects extracted from the IDF document.
        """
        return [cls._from_idf_object(doc, obj) for obj in doc[cls.key]]


class ScheduleTypeLimits(BaseObj, extra="ignore"):
    """ScheduleTypeLimits object."""

    key: ClassVar[str] = "ScheduleTypeLimits"
    Name: str
    Lower_Limit_Value: float | None = None
    Upper_Limit_Value: float | None = None
    Numeric_Type: Literal["Continuous", "Discrete"] | None = None
    Unit_Type: (
        Literal[
            "Dimensionless",
            "Temperature",
            "DeltaTemperature",
            "PrecipitationRate",
            "Angle",
            "ConvectionCoefficient",
            "ActivityLevel",
            "Velocity",
            "Capacity",
            "Power",
            "Availability",
            "Percent",
            "Control",
            "Mode",
        ]
        | None
    ) = None


class SimulationControl(BaseObj, extra="ignore"):
    """SimulationControl object."""

    key: ClassVar[str] = "SimulationControl"
    Do_Zone_Sizing_Calculation: Literal["Yes", "No"] = "Yes"
    Do_System_Sizing_Calculation: Literal["Yes", "No"] = "Yes"
    Do_Plant_Sizing_Calculation: Literal["Yes", "No"] = "Yes"
    Run_Simulation_for_Sizing_Periods: Literal["Yes", "No"] = "Yes"
    Run_Simulation_for_Weather_File_Run_Periods: Literal["Yes", "No"] = "Yes"
    Do_HVAC_Sizing_Simulation_for_Sizing_Periods: Literal["Yes", "No"] = "Yes"
    Maximum_Number_of_HVAC_Sizing_Simulation_Passes: int = 1


class RunPeriod(BaseObj, extra="ignore"):
    """RunPeriod object."""

    key: ClassVar[str] = "RunPeriod"
    Name: str
    Begin_Month: int
    Begin_Day_of_Month: int
    Begin_Year: int | None = None
    End_Month: int
    End_Day_of_Month: int
    End_Year: int | None = None
    Day_of_Week_for_Start_Day: Literal[
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ] = "Sunday"
    Use_Weather_File_Daylight_Saving_Period: Literal["Yes", "No"] = "No"
    Use_Weather_File_Holidays_and_Special_Days: Literal["Yes", "No"] = "No"
    Apply_Weekend_Holiday_Rule: Literal["Yes", "No"] = "Yes"
    Use_Weather_File_Rain_Indicators: Literal["Yes", "No"] = "No"
    Use_Weather_File_Snow_Indicators: Literal["Yes", "No"] = "No"


class Timestep(BaseObj, extra="ignore"):
    """Timestep object."""

    key: ClassVar[str] = "Timestep"
    Number_of_Timesteps_per_Hour: int = 6


class SizingParameters(BaseObj, extra="ignore"):
    """SizingParameters object."""

    key: ClassVar[str] = "Sizing:Parameters"
    Heating_Sizing_Factor: float
    Cooling_Sizing_Factor: float


class SiteGroundTemperature(BaseObj, extra="ignore"):
    """GroundTemperature object."""

    key: ClassVar[str] = "Site:GroundTemperature:BuildingSurface"
    January_Ground_Temperature: float
    February_Ground_Temperature: float
    March_Ground_Temperature: float
    April_Ground_Temperature: float
    May_Ground_Temperature: float
    June_Ground_Temperature: float
    July_Ground_Temperature: float
    August_Ground_Temperature: float
    September_Ground_Temperature: float
    October_Ground_Temperature: float
    November_Ground_Temperature: float
    December_Ground_Temperature: float

    @classmethod
    def FromValues(cls, values: list[float]):
        """Create a new SiteGroundTemperature object from a list of 12 monthly values.

        Args:
            values (list[float]): A list of 12 monthly values.

        Returns:
            ground_temp (SiteGroundTemperature): The new SiteGroundTemperature object.
        """
        if len(values) != 12:
            raise ValueError(f"GROUNDTEMP:EXPECTED_12:RECEIVED_{len(values)}")
        return cls(
            January_Ground_Temperature=values[0],
            February_Ground_Temperature=values[1],
            March_Ground_Temperature=values[2],
            April_Ground_Temperature=values[3],
            May_Ground_Temperature=values[4],
            June_Ground_Temperature=values[5],
            July_Ground_Temperature=values[6],
            August_Ground_Temperature=values[7],
            September_Ground_Temperature=values[8],
            October_Ground_Temperature=values[9],
            November_Ground_Temperature=values[10],
            December_Ground_Temperature=values[11],
        )


class InternalMass(BaseObj, extra="ignore"):
    """InternalMass object."""

    key: ClassVar[str] = "InternalMass"
    Name: str
    Zone_or_ZoneList_Name: str
    Construction_Name: str
    Surface_Area: float


class BaseMaterial(BaseModel, extra="ignore", populate_by_name=True):
    """A base material object for storing material definitions.

    Note that this is not an EnergyPlus object, but a base class for creating new
    material objects which can be turned into EP objects once assigned thicknesses.
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

    def as_layer(self, thickness: float):
        """Create a new material object with a given thickness.

        Args:
            thickness (float): The thickness of the material.

        Returns:
            mat (Material): The new material object with the given thickness.
        """
        name = f"{self.Name}_{thickness}m"
        return Material(
            Name=name, Thickness=thickness, **self.model_dump(exclude={"Name"})
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


class Material(BaseObj, BaseMaterial, extra="ignore"):
    """Material object."""

    key: ClassVar[str] = "Material"
    Name: str
    Thickness: float

    @field_validator("Thermal_Absorptance", mode="before")
    def str_cast(cls, v):
        """Cast the value to a float if it is a string or empty.

        Args:
            v (Any): The value to cast.

        Returns:
            v (float): The casted value.
        """
        if v == "" or v is None:
            return None
        return float(v)

    @property
    def r(self):
        """Return the R of the material."""
        return self.Thickness / self.Conductivity


class SimpleGlazingMaterial(BaseObj, extra="ignore"):
    """SimpleGlazingMaterial object."""

    key: ClassVar[str] = "WindowMaterial:SimpleGlazingSystem"
    Name: str
    UFactor: float
    Solar_Heat_Gain_Coefficient: float
    Visible_Transmittance: float


class AirGapMaterial(BaseObj, extra="ignore"):
    """AirGapMaterial object."""

    key: ClassVar[str] = "Material:AirGap"
    Name: str
    Thermal_Resistance: float


class NoMassMaterial(BaseObj, extra="ignore"):
    """NoMassMaterial object."""

    key: ClassVar[str] = "Material:NoMass"
    Name: str
    Roughness: str
    Thermal_Resistance: float


class Construction(BaseObj, extra="ignore"):
    """Construction object."""

    key: ClassVar[str] = "Construction"
    name: str
    layers: Sequence[Material | AirGapMaterial | SimpleGlazingMaterial | NoMassMaterial]

    @property
    def r_value(self):
        """Return the R-value of the construction.

        Computed using the formula: R = sum(thickness_i / conductivity_i)

        Returns:
            r (float): The R-value of the construction (units: m^2.K/W).
        """
        return (
            sum([layer.r for layer in self.layers if isinstance(layer, Material)])
            + sum([
                layer.Thermal_Resistance
                for layer in self.layers
                if isinstance(layer, AirGapMaterial)
            ])
            + sum([
                layer.Thermal_Resistance
                for layer in self.layers
                if isinstance(layer, NoMassMaterial)
            ])
            + sum([
                1 / layer.UFactor
                for layer in self.layers
                if isinstance(layer, SimpleGlazingMaterial)
            ])
        )

    @classmethod
    def extract(cls, doc: IDFDocument):
        """Extract constructions (and their layer materials) from an IDF document.

        Args:
            doc (IDFDocument): The IDF document to extract objects from.

        Returns:
            constructions (list[Construction]): A list of objects extracted from the IDF document.
        """
        layer_types = (Material, AirGapMaterial, SimpleGlazingMaterial, NoMassMaterial)
        res: list[Construction] = []
        for construction in doc["Construction"]:
            layer_names = [
                name
                for field, name in construction.to_dict().items()
                if field != "name" and isinstance(name, str) and name
            ]
            layers: list[
                Material | AirGapMaterial | SimpleGlazingMaterial | NoMassMaterial
            ] = []
            for layer_name in layer_names:
                for layer_type in layer_types:
                    material = doc[layer_type.key].get(layer_name)
                    if material is not None:
                        layers.append(layer_type._from_idf_object(doc, material))
                        break
            if len(layers) != len(layer_names):
                logger.warning(
                    f"Construction {construction.name} has missing layers. "
                    f"Expected {len(layer_names)} layers, got {len(layers)}."
                    f"Skipping construction extraction."
                )
                continue
            res.append(cls(name=construction.name, layers=layers))
        return res

    def add(self, doc: IDFDocument):
        """Add the object to the IDF document.

        Args:
            doc (IDFDocument): The IDF document to add the object to.

        Returns:
            doc (IDFDocument): The updated IDF document.
        """
        for layer in self.layers:
            doc = layer.add(doc)
        doc.add(
            self.key,
            self.name,
            {
                (f"layer_{i + 1}" if i != 0 else "outside_layer"): layer.Name
                for i, layer in enumerate(self.layers)
            },
        )
        return doc


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

# TODO: convert templates into BaseObjs?
# TODO: Schedule referencing more richly?

ThermostatType = Literal[
    "SingleHeating", "SingleCooling", "SingleHeatingOrCooling", "DualSetpoint"
]


class HVACTemplateThermostat(BaseModel):
    """HVACTemplateThermostat object."""

    Name: str
    Heating_Setpoint_Schedule_Name: str | None = None
    Constant_Heating_Setpoint: float | None = 21
    Cooling_Setpoint_Schedule_Name: str | None = None
    Constant_Cooling_Setpoint: float | None = 24

    def add(self, doc: IDFDocument):
        """Add the object to the IDF document.

        Args:
            doc (IDFDocument): The IDF document to add the object to.

        Returns:
            doc (IDFDocument): The updated IDF document
        """
        _add_object(doc, "HVACTemplate:Thermostat", self.model_dump())
        return doc


class HVACTemplateZoneIdealLoadsAirSystem(BaseModel):
    """HVACTemplateZoneIdealLoadsAirSystem object."""

    Zone_Name: str
    Template_Thermostat_Name: str
    System_Availability_Schedule_Name: str | None = None
    Heating_Availability_Schedule_Name: str | None = None
    Cooling_Availability_Schedule_Name: str | None = None
    Maximum_Heating_Supply_Air_Temperature: float = 30
    Minimum_Cooling_Supply_Air_Temperature: float = 18
    Maximum_Heating_Supply_Air_Humidity_Ratio: float = 0.0156
    Minimum_Cooling_Supply_Air_Humidity_Ratio: float = 0.0077
    Heating_Limit: IdealLoadsLimitType = "NoLimit"
    Maximum_Heating_Air_Flow_Rate: float | None | Literal["autosize"] = None
    Maximum_Sensible_Heating_Capacity: float | None | Literal["autosize"] = None
    Cooling_Limit: IdealLoadsLimitType = "NoLimit"
    Maximum_Cooling_Air_Flow_Rate: float | None | Literal["autosize"] = None
    Maximum_Total_Cooling_Capacity: float | None | Literal["autosize"] = None
    Dehumidification_Control_Type: DehumidificationControlTypeType = "None"
    Cooling_Sensible_Heat_Ratio: float = 0.7
    Dehumidification_Setpoint: float = 60
    Humidification_Control_Type: HumidificationControlTypeType = "None"
    Humidification_Setpoint: float = 30
    Outdoor_Air_Method: OutdoorAirMethodType = "None"
    Outdoor_Air_Flow_Rate_per_Person: float = 0.00944
    Outdoor_Air_Flow_Rate_per_Zone_Floor_Area: float = 0.00025
    Outdoor_Air_Flow_Rate_per_Zone: float = 0.0
    # Design_Specification_Outdoor_Air_Object_Name: Optional[str] = None
    Demand_Controlled_Ventilation_Type: DemandControlledVentilationTypeType = "None"
    Outdoor_Air_Economizer_Type: OutdoorAirEconomizerTypeType = "NoEconomizer"
    Heat_Recovery_Type: HeatRecoveryTypeType = "None"
    Sensible_Heat_Recovery_Effectiveness: float = 0.7
    Latent_Heat_Recovery_Effectiveness: float = 0.65

    def add(self, doc: IDFDocument):
        """Add the object to the IDF document.

        Args:
            doc (IDFDocument): The IDF document to add the object to.

        Returns:
            doc (IDFDocument): The updated IDF document
        """
        _add_object(doc, "HVACTemplate:Zone:IdealLoadsAirSystem", self.model_dump())
        return doc


DesignLevelCalculationMethodType = Literal["Watts/Area", "Watts/Person", "Watts"]


# TODO: add water mains?
class WaterUseEquipment(BaseObj, extra="ignore"):
    """WaterUseEquipment object."""

    key: ClassVar[str] = "WaterUse:Equipment"
    Name: str
    EndUse_Subcategory: str | None = None
    Peak_Flow_Rate: float
    Flow_Rate_Fraction_Schedule_Name: str | None = None
    Target_Temperature_Schedule_Name: str | None = None
    Hot_Water_Supply_Temperature_Schedule_Name: str | None = None
    Cold_Water_Supply_Temperature_Schedule_Name: str | None = None
    Zone_Name: str | None = None
    Sensible_Fraction_Schedule_Name: str | None = None
    Latent_Fraction_Schedule_Name: str | None = None


class ElectricEquipment(BaseObj, extra="ignore"):
    """ElectricEquipment object."""

    key: ClassVar[str] = "ElectricEquipment"
    Name: str
    Zone_or_ZoneList_Name: str
    Schedule_Name: str
    Design_Level_Calculation_Method: DesignLevelCalculationMethodType = "Watts/Area"
    Design_Level: float | None = None
    Watts_per_Zone_Floor_Area: float | None = None
    Watts_per_Person: float | None = None
    Fraction_Latent: float = 0.00
    Fraction_Radiant: float = 0.2
    Fraction_Lost: float = 0
    EndUse_Subcategory: str | None = None


class Lights(BaseObj, extra="ignore"):
    """Lights object."""

    key: ClassVar[str] = "Lights"
    Name: str
    Zone_or_ZoneList_Name: str
    Schedule_Name: str
    Design_Level_Calculation_Method: DesignLevelCalculationMethodType = "Watts/Area"
    Lighting_Level: float | None = None
    Watts_per_Zone_Floor_Area: float | None = None
    Watts_per_Person: float | None = None
    Return_Air_Fraction: float = 0
    Fraction_Radiant: float = 0.42
    Fraction_Visible: float = 0.18
    Fraction_Replaceable: float | None = 1
    EndUse_Subcategory: str | None = None


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


class ZoneVentilationWindAndStackOpenArea(BaseObj, extra="ignore"):
    """ZoneVentilationWindAndStackOpenArea object."""

    key: ClassVar[str] = "ZoneVentilation:WindandStackOpenArea"
    Name: str
    Zone_or_Space_Name: str
    Opening_Area: float
    Opening_Area_Fraction_Schedule_Name: str
    Opening_Effectiveness: str = "AutoCalculate"
    Effective_Angle: float = 0
    Height_Difference: float
    Discharge_Coefficient_for_Opening: str = "AutoCalculate"
    Minimum_Indoor_Temperature: float | None = None
    Minimum_Indoor_Temperature_Schedule_Name: str | None = None
    Maximum_Indoor_Temperature: float | None = None
    Maximum_Indoor_Temperature_Schedule_Name: str | None = None
    Delta_Temperature: float | None = None
    Delta_Temperature_Schedule_Name: str | None = None
    Minimum_Outdoor_Temperature: float | None = None
    Minimum_Outdoor_Temperature_Schedule_Name: str | None = None
    Maximum_Outdoor_Temperature: float | None = None
    Maximum_Outdoor_Temperature_Schedule_Name: str | None = None
    Maximum_Wind_Speed: float = 40


class ZoneInfiltrationDesignFlowRate(BaseObj, extra="ignore"):
    """ZoneInfiltrationDesignFlowRate object."""

    key: ClassVar[str] = "ZoneInfiltration:DesignFlowRate"
    Name: str
    Zone_or_ZoneList_Name: str
    Schedule_Name: str
    Design_Flow_Rate_Calculation_Method: InfDesignFlowRateCalculationMethodType
    Design_Flow_Rate: float | None = None
    Flow_Rate_per_Floor_Area: float | None = None
    Flow_Rate_per_Exterior_Surface_Area: float | None = None
    Air_Changes_per_Hour: float | None = None
    # Constant_Term_Coefficient: float = 0.606
    # Temperature_Term_Coefficient: float = 3.6359996e-2
    # Velocity_Term_Coefficient: float = 0.117765
    Constant_Term_Coefficient: float = 1  # updated to assume that we have the actual infiltration values - the more detailed coefficient methodology would likely overestimate the infiltration rate, as there are many days where the tmperature deltas exceeds 10 degrees.
    Temperature_Term_Coefficient: float = 0
    Velocity_Term_Coefficient: float = 0
    Velocity_Squared_Term_Coefficient: float = (
        0  # updated as we don't make assumptions about the wind velocity
    )


NumberOfPeopleCalculationMethodType = Literal["People", "People/Area", "Area/Person"]


class People(BaseObj, extra="ignore"):
    """People object."""

    key: ClassVar[str] = "People"
    Name: str
    Zone_or_ZoneList_Name: str
    Number_of_People_Schedule_Name: str
    Number_of_People_Calculation_Method: NumberOfPeopleCalculationMethodType
    Number_of_People: float | None = None
    People_per_Floor_Area: float | None = None
    Floor_Area_per_Person: float | None = None
    Fraction_Radiant: float = 0.3
    Sensible_Heat_Fraction: float | Literal["autocalculate"] = "autocalculate"
    Activity_Level_Schedule_Name: str
    # Carbon_Dioxide_Generation_Rate: Optional[float] = None
    Enable_ASHRAE_55_Comfort_Warnings: Literal["Yes", "No"] = "No"
    # Cold_Stress_Temperature_Threshold: float = 15.56
    # Heat_Stress_Temperature_Threshold: float = 30.0
    # Mean_Radiant_Temperature_Calculation_Type: Literal["ZoneAveraged", "EnclosureAveraged"]
    # Surface_Name_Angle_Factor_List_Name: str
    # Work_Efficiency_Schedule_Name: str
    # Clothing_Insulation_Calculation_Method: str
    # Clothing_Insulation_Calculation_Method_Schedule_Name: str
    # Clothing_Insulation_Schedule_Name: str
    # Air_Velocity_Schedule_Name: str
    # Thermal_Comfort_Model_Type: str


class ScheduleDayHourly(BaseObj, extra="ignore"):
    """ScheduleDayHourly object."""

    key: ClassVar[str] = "Schedule:Day:Hourly"
    Name: str
    Schedule_Type_Limits_Name: str
    Hour_1: float
    Hour_2: float
    Hour_3: float
    Hour_4: float
    Hour_5: float
    Hour_6: float
    Hour_7: float
    Hour_8: float
    Hour_9: float
    Hour_10: float
    Hour_11: float
    Hour_12: float
    Hour_13: float
    Hour_14: float
    Hour_15: float
    Hour_16: float
    Hour_17: float
    Hour_18: float
    Hour_19: float
    Hour_20: float
    Hour_21: float
    Hour_22: float
    Hour_23: float
    Hour_24: float


class ScheduleWeekDaily(BaseObj, extra="ignore"):
    """ScheduleWeekDaily object."""

    key: ClassVar[str] = "Schedule:Week:Daily"
    Name: str
    Monday_ScheduleDay_Name: str
    Tuesday_ScheduleDay_Name: str
    Wednesday_ScheduleDay_Name: str
    Thursday_ScheduleDay_Name: str
    Friday_ScheduleDay_Name: str
    Saturday_ScheduleDay_Name: str
    Sunday_ScheduleDay_Name: str
    SummerDesignDay_ScheduleDay_Name: str | None = None
    WinterDesignDay_ScheduleDay_Name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_design_day_schedules(cls, data):
        if data.get("SummerDesignDay_ScheduleDay_Name") is None:
            data["SummerDesignDay_ScheduleDay_Name"] = data["Monday_ScheduleDay_Name"]
        if data.get("WinterDesignDay_ScheduleDay_Name") is None:
            data["WinterDesignDay_ScheduleDay_Name"] = data["Monday_ScheduleDay_Name"]
        return data

    @computed_field
    @property
    def CustomDay1_ScheduleDay_Name(self) -> str:
        """Automatically set additional day schedules."""
        return self.Monday_ScheduleDay_Name

    @computed_field
    @property
    def CustomDay2_ScheduleDay_Name(self) -> str:
        """Automatically set additional day schedules."""
        return self.Monday_ScheduleDay_Name

    @computed_field
    @property
    def Holiday_ScheduleDay_Name(self) -> str:
        """Automatically set additional day schedules."""
        return self.Sunday_ScheduleDay_Name


class ScheduleYear(BaseObj, extra="ignore"):
    """ScheduleYear object."""

    key: ClassVar[str] = "Schedule:Year"
    Name: str
    Schedule_Type_Limits_Name: str

    ScheduleWeek_Name_1: str
    Start_Month_1: int
    Start_Day_1: int
    End_Month_1: int
    End_Day_1: int

    ScheduleWeek_Name_2: str | None = None
    Start_Month_2: int | None = None
    Start_Day_2: int | None = None
    End_Month_2: int | None = None
    End_Day_2: int | None = None

    ScheduleWeek_Name_3: str | None = None
    Start_Month_3: int | None = None
    Start_Day_3: int | None = None
    End_Month_3: int | None = None
    End_Day_3: int | None = None

    ScheduleWeek_Name_4: str | None = None
    Start_Month_4: int | None = None
    Start_Day_4: int | None = None
    End_Month_4: int | None = None
    End_Day_4: int | None = None

    ScheduleWeek_Name_5: str | None = None
    Start_Month_5: int | None = None
    Start_Day_5: int | None = None
    End_Month_5: int | None = None
    End_Day_5: int | None = None

    ScheduleWeek_Name_6: str | None = None
    Start_Month_6: int | None = None
    Start_Day_6: int | None = None
    End_Month_6: int | None = None
    End_Day_6: int | None = None

    ScheduleWeek_Name_7: str | None = None
    Start_Month_7: int | None = None
    Start_Day_7: int | None = None
    End_Month_7: int | None = None
    End_Day_7: int | None = None

    ScheduleWeek_Name_8: str | None = None
    Start_Month_8: int | None = None
    Start_Day_8: int | None = None
    End_Month_8: int | None = None
    End_Day_8: int | None = None

    ScheduleWeek_Name_9: str | None = None
    Start_Month_9: int | None = None
    Start_Day_9: int | None = None
    End_Month_9: int | None = None
    End_Day_9: int | None = None

    ScheduleWeek_Name_10: str | None = None
    Start_Month_10: int | None = None
    Start_Day_10: int | None = None
    End_Month_10: int | None = None
    End_Day_10: int | None = None

    ScheduleWeek_Name_11: str | None = None
    Start_Month_11: int | None = None
    Start_Day_11: int | None = None
    End_Month_11: int | None = None
    End_Day_11: int | None = None

    ScheduleWeek_Name_12: str | None = None
    Start_Month_12: int | None = None
    Start_Day_12: int | None = None
    End_Month_12: int | None = None
    End_Day_12: int | None = None

    def add(self, doc: IDFDocument):
        """Add the object to the IDF document.

        Args:
            doc (IDFDocument): The IDF document to add the object to.

        Returns:
            doc (IDFDocument): The updated IDF document.
        """
        data = self.model_dump()
        weeks = [
            {
                "schedule_week_name": data[f"ScheduleWeek_Name_{i}"],
                "start_month": data[f"Start_Month_{i}"],
                "start_day": data[f"Start_Day_{i}"],
                "end_month": data[f"End_Month_{i}"],
                "end_day": data[f"End_Day_{i}"],
            }
            for i in range(1, 13)
            if data[f"ScheduleWeek_Name_{i}"] is not None
        ]
        doc.add(
            self.key,
            self.Name,
            schedule_type_limits_name=self.Schedule_Type_Limits_Name,
            schedule_weeks=weeks,
        )
        return doc


class ZoneList(BaseModel, extra="ignore"):
    """ZoneList object."""

    Name: str
    Names: list[str]

    def add(self, doc: IDFDocument):
        """Add the object to the IDF document.

        Args:
            doc (IDFDocument): The IDF document to add the object to.

        Returns:
            doc (IDFDocument): The updated IDF document.
        """
        doc.add(
            "ZoneList",
            self.Name,
            zones=[{"zone_name": zone} for zone in self.Names if zone],
        )
        return doc


def add_default_sim_controls(doc: IDFDocument) -> IDFDocument:
    """Helper to add default simulation controls to the IDF model.

    Args:
        doc (IDFDocument): The IDF model to add the simulation controls to.

    Returns:
        IDFDocument: The IDF model with the added simulation controls.
    """
    # Configure simulation
    sim_control = SimulationControl(
        Do_Zone_Sizing_Calculation="Yes",
        Do_System_Sizing_Calculation="Yes",
        Do_Plant_Sizing_Calculation="No",
        Run_Simulation_for_Sizing_Periods="Yes",
        Run_Simulation_for_Weather_File_Run_Periods="Yes",
        Do_HVAC_Sizing_Simulation_for_Sizing_Periods="Yes",
        Maximum_Number_of_HVAC_Sizing_Simulation_Passes=2,
    )
    sim_control.add(doc)

    # Configure run period
    run_period = RunPeriod(
        Name="Year",
        Use_Weather_File_Daylight_Saving_Period="No",
        Use_Weather_File_Rain_Indicators="No",
        Use_Weather_File_Snow_Indicators="No",
        Use_Weather_File_Holidays_and_Special_Days="No",
        Begin_Month=1,
        Begin_Day_of_Month=1,
        End_Month=12,
        End_Day_of_Month=31,
        Day_of_Week_for_Start_Day="Sunday",
    )
    run_period.add(doc)

    # configure timestep
    timestep = Timestep(
        Number_of_Timesteps_per_Hour=6,
    )
    timestep.add(doc)

    sizing = SizingParameters(
        Heating_Sizing_Factor=1.15,
        Cooling_Sizing_Factor=1.15,
    )
    sizing.add(doc)

    return doc


def add_constant_schedule(
    doc: IDFDocument, name: str, value: float, type_limits: str = "Fraction"
) -> IDFObject:
    """Add a constant schedule as `Schedule:Year`/`Week:Daily`/`Day:Hourly` objects.

    Args:
        doc (IDFDocument): The IDF document to add the schedule to.
        name (str): The name of the `Schedule:Year`.
        value (float): The value held all year.
        type_limits (str): The name of an existing `ScheduleTypeLimits`.

    Returns:
        IDFObject: The `Schedule:Year` object.
    """
    return add_values_schedule(doc, name, [value] * HOURS_PER_YEAR, type_limits)


DEFAULT_CONSTANT_SCHEDULE_PAIRS = (
    ("Always_On", "Always_Off"),
    ("Always On", "Always Off"),
    ("On", "Off"),
    ("AllOn", "AllOff"),
    ("AlwaysOn", "AlwaysOff"),
)


def add_default_schedules(doc: IDFDocument) -> tuple[IDFDocument, dict[str, IDFObject]]:
    """Helper to add default schedules to the IDF model.

    Args:
        doc (IDFDocument): The IDF model to add the schedules to.

    Returns:
        doc (IDFDocument): The IDF model with the added schedules.
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
