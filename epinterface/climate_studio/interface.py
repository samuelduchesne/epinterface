"""A module for parsing climate studio data and generating EnergyPlus objects."""

import logging
import re
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar, cast

import numpy as np
import pandas as pd
from idfkit import IDFDocument, IDFObject
from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    Field,
    model_validator,
    validate_call,
)

from epinterface.document import add_construction, add_or_replace, field_name
from epinterface.interface import (
    HeatRecoveryTypeType,
    IdealLoadsLimitType,
    InfDesignFlowRateCalculationMethodType,
    OutdoorAirEconomizerTypeType,
    add_constant_schedule,
    zone_list_names,
)
from epinterface.schedules import HOURS_PER_YEAR, add_values_schedule

logger = logging.getLogger(__name__)


class ClimateStudioException(Exception):
    """A base exception for the climate studio library."""

    def __init__(self, message: str):
        """Initialize the exception with a message."""
        self.message = message
        super().__init__(self.message)


class ClimateStudioValueNotFound(ClimateStudioException):
    """An error raised when a value is not found in a climate studio library."""

    def __init__(self, obj_type: str, value: str):
        """Initialize the exception with a message.

        Args:
            obj_type (str): The type of object that was not found.
            value (str): The value that was not found.
        """
        self.obj_type = obj_type
        self.value = value
        self.message = f"Value not found in library: {obj_type}:{value}"
        super().__init__(self.message)


class ClimateStudioLibraryDuplicatesFound(ClimateStudioException):
    """An error raised when duplicates are found in a climate studio library."""

    def __init__(self, duplicate_field: str):
        """Initialize the exception with a message.

        Args:
            duplicate_field (str): The field with duplicates
        """
        self.duplicate_field = duplicate_field
        self.message = f"Duplicate objects found in library: {duplicate_field}"
        super().__init__(self.message)


class NotImplementedClimateStudioParameter(ClimateStudioException):
    """An error raised when a climate studio parameter is not implemented."""

    def __init__(self, parameter_name: str, obj_name: str, obj_type: str):
        """Initialize the exception with a message.

        Args:
            parameter_name (str): The name of the parameter.
            obj_name (str): The name of the object.
            obj_type (str): The type of the object.
        """
        self.parameter_name = parameter_name
        self.obj_name = obj_name
        self.obj_type = obj_type
        self.message = f"Parameter {parameter_name} not implemented for {obj_type.upper()}:{obj_name}"
        super().__init__(self.message)


class ScheduleParseError(ClimateStudioException):
    """An error raised when a schedule cannot be parsed."""

    def __init__(self, schedule_name: str):
        """Initialize the exception with a message.

        Args:
            schedule_name (str): The name of the schedule.
        """
        self.schedule_name = schedule_name
        super().__init__(f"Failed to parse schedule {schedule_name}")


def nan_to_none_or_str(v: Any) -> str | None | Any:
    """Converts NaN to None and leaves strings as is.

    Args:
        v (Any): Value to convert

    Returns:
        v (None | str | Any): Converted value
    """
    if isinstance(v, str):
        return v
    if v is None:
        return None
    if np.isnan(v):
        return None
    return v


def str_to_bool(v: str | bool) -> bool:
    """Converts a string to a boolean if necessary.

    Args:
        v (str | bool): Value to convert

    Returns:
        bool: Converted value
    """
    if isinstance(v, bool):
        return v
    elif v.lower() == "true":
        return True
    elif v.lower() == "false":
        return False
    else:
        return False


def str_to_float_list(v: str | list):
    """Converts a string to a list of floats.

    Args:
        v (str): String to convert

    Returns:
        vals (list[float]): List of floats
    """
    if v == "[]":
        return []
    if isinstance(v, str):
        # re should be used to parse the string -
        # check that it starts with "["  and ends with "]"
        # and the elements are separated by ", "
        # and the elements are all ints or floats

        if not re.match(r"^\[.*\]$", v):
            raise ValueError(f"STRING:NOT_LIST:{v}")
        v = v[1:-1]
        if not re.match(r"^[\-0-9\., ]*$", v):
            raise ValueError(f"STRING:NOT_LIST:{v}")
        v = v.replace(" ", "").split(",")
    return [float(x) for x in v]


NanStr = Annotated[str | None, BeforeValidator(nan_to_none_or_str)]
BoolStr = Annotated[bool, BeforeValidator(str_to_bool)]
FloatListStr = Annotated[list[float], BeforeValidator(str_to_float_list)]


class NamedObject(BaseModel):
    """A Named object (with a name field)."""

    Name: str = Field(..., title="Name of the object used in referencing.")


class EmbodiedCarbonData(BaseModel):
    """Embodied carbon data for a material or construction."""

    EmbodiedEnergy: float = Field(
        ...,
        title="Embodied energy [MJ/unit]",
        validation_alias=AliasChoices(
            "EmbodiedEnergy [MJ/Kg]",
            "EmbodiedEnergy",
            "EmbodiedEnergy [MJ/m²]",
            "EmbodiedEnergy [MJ/mÂ²]",
            "EmbodiedEnergy [MJ/mÃ‚Â²]",  # noqa: RUF001
        ),
    )
    EmbodiedEnergyStdDev: float = Field(
        0,
        title="Standard deviation of embodied energy [MJ/unit]",
        validation_alias="EmbodiedEnergyStdDev",
        ge=0,
    )
    EmbodiedCarbon: float = Field(
        ...,
        title="Embodied carbon [kgCO2eq/unit]",
        validation_alias=AliasChoices(
            "EmbodiedCarbon [kgCO2eq/Kg]",
            "EmbodiedCarbon",
            "EmbodiedCarbon [kgCO2eq/m²]",
            "EmbodiedCarbon [kgCO2eq/mÂ²]",
            "EmbodiedCarbon [kgCO2eq/mÃ‚Â²]",  # noqa: RUF001
        ),
    )
    EmbodiedCarbonStdDev: float = Field(
        0,
        title="Standard deviation of embodied carbon [kgCO2eq/unit]",
        validation_alias="EmbodiedCarbonStdDev",
        ge=0,
    )


class LifecycleData(BaseModel):
    """Lifecycle data for a material or construction."""

    Cost: float = Field(
        ...,
        title="Cost [$/unit]",
        # a superscript 3 looks like this:
        validation_alias=AliasChoices(
            "Cost [$/m³]",
            "Cost [$/m3]",
            "Cost [$/m²]",
            "Cost [$/m2]",
            "Cost [$/m]",
            "Cost [$/kg]",
            "Cost [$/mÂ²]",
            "Cost [$/mÃ‚Â²]",  # noqa: RUF001
        ),
        ge=0,
    )
    Life: float = Field(
        ...,
        title="Life [years]",
        validation_alias="Life [yr]",
        ge=0,
    )


class ClimateStudioMetadata(BaseModel):
    """Metadata for a climate studio table object."""

    Category: str = Field(..., title="Category of the object")
    Comment: NanStr = Field(..., title="Comment on the object")
    DataSource: NanStr = Field(..., title="Data source of the object")
    ClimateZone: str = Field(..., title="Climate zone of the object")
    Standard: str = Field(..., title="Standard of the object")
    Program: str = Field(..., title="Program of the object")
    Version: NanStr | None = Field(default=None, title="Version of the object")


class StandardMaterializedMetadata(
    EmbodiedCarbonData, LifecycleData, ClimateStudioMetadata
):
    """Standard metadata for a climate studio table."""

    pass


class MaterialWithThickness(BaseModel, populate_by_name=True):
    """Material with a thickness."""

    Thickness: float = Field(
        ...,
        title="Thickness of the material [m]",
        validation_alias="Thickness [m]",
        ge=0,
    )


class GasMaterial(
    NamedObject, MaterialWithThickness, StandardMaterializedMetadata, extra="forbid"
):
    """Gas Material object."""

    Model: Literal["Gas"] = Field(default="Gas", title="Model of the gas material")
    GasType1: str = Field(..., title="Type of the gas material")
    GasType2: str = Field(..., title="Type of the gas material")
    GasType3: str = Field(..., title="Type of the gas material")
    GasesInMix: int = Field(..., title="Number of gases in the mix", ge=1)
    Ratio1: float = Field(..., title="Ratio of the gas material", ge=0, le=1)
    Ratio2: float = Field(..., title="Ratio of the gas material", ge=0, le=1)
    Ratio3: float = Field(..., title="Ratio of the gas material", ge=0, le=1)
    ConductivityCoefficientA: float = Field(
        ..., title="Conductivity coefficient A", ge=0
    )
    ConductivityCoefficientB: float = Field(
        ..., title="Conductivity coefficient B", ge=0
    )
    ConductivityCoefficientC: float = Field(
        ..., title="Conductivity coefficient C", ge=0
    )
    MolecularWeight: float = Field(..., title="Molecular weight", ge=0)
    SpecificHeatCoefficientA: float = Field(
        ..., title="Specific heat coefficient A", ge=0
    )
    SpecificHeatCoefficientB: float = Field(
        ..., title="Specific heat coefficient B", ge=0
    )
    SpecificHeatCoefficientC: float = Field(
        ..., title="Specific heat coefficient C", ge=0
    )
    SpecificHeatRatio: float = Field(..., title="Specific heat ratio", ge=0)
    ViscosityCoefficientA: float = Field(..., title="Viscosity coefficient A", ge=0)
    ViscosityCoefficientB: float = Field(..., title="Viscosity coefficient B", ge=0)
    ViscosityCoefficientC: float = Field(..., title="Viscosity coefficient C", ge=0)


class ManufacturerData(BaseModel):
    """Manufacturer data for a construction."""

    Manufacturer: NanStr = Field(..., title="Manufacturer of the object")
    ProductName: NanStr = Field(..., title="Product name of the object")
    Appearance: NanStr = Field(..., title="Appearance of the glazing construction")


WindowType = Literal["Single", "Double", "Triple"]


class GlazingConstructionSimple(
    NamedObject,
    StandardMaterializedMetadata,
    ManufacturerData,
    extra="forbid",
    populate_by_name=True,
):
    """Simple glazing construction object."""

    SHGF: float = Field(..., title="Solar heat gain factor", ge=0, le=1)
    UValue: float = Field(
        ...,
        title="U-value [W/m²K]",
        validation_alias="UValue [W/m2-k]",
        ge=0,
    )
    TVis: float = Field(..., title="Visible transmittance", ge=0, le=1)
    Type: WindowType = Field(..., title="Type of the glazing construction")

    def add_to_idf(self, doc: IDFDocument) -> IDFDocument:
        """Adds the glazing construction to an IDF document.

        Args:
            doc (IDFDocument): The IDF document to add the construction to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        add_or_replace(
            doc,
            "WindowMaterial:SimpleGlazingSystem",
            self.Name,
            u_factor=self.UValue,
            solar_heat_gain_coefficient=self.SHGF,
            visible_transmittance=self.TVis,
        )
        add_construction(doc, self.Name, [self.Name])
        return doc


class CommonMaterialProperties(BaseModel):
    """Common material properties for glazing and opaque materials."""

    Conductivity: float = Field(
        ...,
        title="Conductivity [W/mK]",
        validation_alias="Conductivity [W/m.K]",
        ge=0,
    )
    Density: float = Field(
        ...,
        title="Density [kg/m3]",
        ge=0,
        validation_alias=AliasChoices(
            "Density [kg/m³]",
            "Density [kg/m3]",
        ),
    )


class GlazingMaterialProperties(CommonMaterialProperties):
    """Properties of a glazing material."""

    Optical: str = Field(..., title="Optical properties of the glazing material")
    OpticalDataName: NanStr = Field(
        ..., title="Optical data name of the glazing material"
    )
    NFRC_ID: int = Field(..., title="NFRC ID of the glazing material")
    Glazing_ID: int = Field(..., title="Glazing ID of the glazing material")
    CoatingSide: NanStr = Field(..., title="Coating side of the glazing material")
    SpectralDataPointWavelength: FloatListStr = Field(
        ...,
        title="Spectral data point wavelength",
        validation_alias="SpectralDataPointWavelength [Microns]",
    )
    SpectralDataPointTransmittance: FloatListStr = Field(
        ...,
        title="Spectral data point transmittance",
        validation_alias="SpectralDataPointTransmittance [0-1]",
    )
    SpectralDataPointFrontReflectance: FloatListStr = Field(
        ...,
        title="Spectral data point front reflectance",
        validation_alias="SpectralDataPointFrontReflectance [0-1]",
    )
    SpectralDataPointBackReflectance: FloatListStr = Field(
        ...,
        title="Spectral data point back reflectance",
        validation_alias="SpectralDataPointBackReflectance [0-1]",
    )
    SolarTransmittance: float = Field(
        ...,
        title="Solar transmittance of the glazing material",
        ge=0,
        le=1,
        validation_alias="SolarTransmittance [0-1]",
    )
    SolarReflectanceFront: float = Field(
        ...,
        title="Solar reflectance front of the glazing material",
        ge=0,
        le=1,
        validation_alias="SolarReflectanceFront [0-1]",
    )
    SolarReflectanceBack: float = Field(
        ...,
        title="Solar reflectance back of the glazing material",
        ge=0,
        le=1,
        validation_alias="SolarReflectanceBack [0-1]",
    )
    VisibleTransmittance: float = Field(
        ...,
        title="Visible transmittance of the glazing material",
        ge=0,
        le=1,
        validation_alias="VisibleTransmittance [0-1]",
    )
    VisibleReflectanceFront: float = Field(
        ...,
        title="Visible reflectance front of the glazing material",
        ge=0,
        le=1,
        validation_alias="VisibleReflectanceFront [0-1]",
    )
    VisibleReflectanceBack: float = Field(
        ...,
        title="Visible reflectance back of the glazing material",
        ge=0,
        le=1,
        validation_alias="VisibleReflectanceBack [0-1]",
    )
    IRTransmittance: float = Field(
        ...,
        title="IR transmittance of the glazing material",
        ge=0,
        le=1,
        validation_alias="IRTransmittance [0-1]",
    )
    IREmissivityFront: float = Field(
        ...,
        title="IR emissivity front of the glazing material",
        ge=0,
        le=1,
        validation_alias="IREmissivityFront [0-1]",
    )
    IREmissivityBack: float = Field(
        ...,
        title="IR emissivity back of the glazing material",
        ge=0,
        le=1,
        validation_alias="IREmissivityBack [0-1]",
    )
    DirtFactor: float = Field(
        ...,
        title="Dirt factor of the glazing material",
        ge=0,
        le=1,
        validation_alias="DirtFactor [0-1]",
    )
    Type: str = Field(..., title="Type of the glazing material")


class GlazingMaterial(
    GlazingMaterialProperties,
    MaterialWithThickness,
    StandardMaterializedMetadata,
    NamedObject,
    extra="forbid",
):
    """Glazing material object."""

    pass


OpaqueMaterialType = Literal[
    "Concrete",
    "Timber",
    "Screed",
    "Masonry",
    "Insulation",
    "Metal",
    "Boards",
    "Other",
    "Plaster",
    "Finishes",
    "Siding",
    "Sealing",
]


class OpaqueMaterialProperties(CommonMaterialProperties, populate_by_name=True):
    """Properties of an opaque material."""

    Roughness: str = Field(..., title="Roughness of the opaque material")
    SpecificHeat: float = Field(
        ...,
        title="Specific heat [J/kgK]",
        validation_alias="SpecificHeat [J/kg.K]",
        ge=0,
    )
    ThermalAbsorptance: float = Field(
        ...,
        title="Thermal absorptance",
        ge=0,
        le=1,
        validation_alias="ThermalAbsorptance [0-1]",
    )
    SolarAbsorptance: float = Field(
        ...,
        title="Solar absorptance",
        ge=0,
        le=1,
        validation_alias="SolarAbsorptance [0-1]",
    )
    VisibleAbsorptance: float = Field(
        ...,
        title="Visible absorptance",
        ge=0,
        le=1,
        validation_alias="VisibleAbsorptance [0-1]",
    )
    PhaseChange: BoolStr = Field(
        ...,
        title="Phase change",
        validation_alias="PhaseChange [Bool]",
    )
    VariableConductivity: BoolStr = Field(
        ...,
        title="Variable conductivity",
        validation_alias="VariableConductivity [Bool]",
    )
    TemperatureCoefficientThermalConductivity: float = Field(
        ...,
        # a superscript 2 looks like this:
        title="Temperature coefficient of thermal conductivity [W/m.K2²]",
        ge=0,
        validation_alias="TemperatureCoefficientThermalConductivity [W/m-K2]",
    )
    TemperatureArray: FloatListStr = Field(
        ...,
        title="Temperature array",
        validation_alias="TemperatureArray [C]",
    )
    EnthalpyArray: FloatListStr = Field(
        ...,
        title="Enthalpy array",
        validation_alias="EnthalpyArray [J/kg]",
    )
    VariableConductivityArray: FloatListStr = Field(
        ...,
        title="Variable conductivity array",
        validation_alias="VariableConductivityArray [W/m-K]",
    )
    Type: OpaqueMaterialType = Field(
        ..., title="Type of the opaque material", validation_alias="Type [enum]"
    )


class OpaqueMaterial(
    OpaqueMaterialProperties,
    StandardMaterializedMetadata,
    NamedObject,
    extra="forbid",
):
    """Opaque material object."""

    pass


class OpaqueConstructionLayer(MaterialWithThickness, NamedObject, extra="forbid"):
    """Layer of an opaque construction."""

    def add_material_to_idf(
        self, doc: IDFDocument, material_defs: dict[str, OpaqueMaterial]
    ) -> IDFObject:
        """Write the referenced material as a `Material` of this layer's thickness.

        An identical material already in the document is reused.

        Args:
            doc (IDFDocument): The IDF document to write to.
            material_defs (dict[str, OpaqueMaterial]): Opaque material definitions by name.

        Returns:
            IDFObject: The `Material` object, named `{Name}_{Thickness}`.
        """
        if self.Name not in material_defs:
            raise ClimateStudioValueNotFound("Material", self.Name)

        mat_def = material_defs[self.Name]
        return add_or_replace(
            doc,
            "Material",
            f"{self.Name}_{self.Thickness}",
            roughness=mat_def.Roughness,
            thickness=self.Thickness,
            conductivity=mat_def.Conductivity,
            density=mat_def.Density,
            specific_heat=mat_def.SpecificHeat,
            thermal_absorptance=mat_def.ThermalAbsorptance,
            solar_absorptance=mat_def.SolarAbsorptance,
            visible_absorptance=mat_def.VisibleAbsorptance,
        )


def str_to_opaque_layer_list(v: str | list):
    """Converts a string to a list of opaque construction layers."""
    if isinstance(v, list):
        return v
    if v == "[]":
        return []
    list_content = v[1:-1].split(", ")
    names = list_content[::2]
    thicknesses = list(map(float, list_content[1::2]))
    return [
        OpaqueConstructionLayer(Name=name, Thickness=thickness)
        for name, thickness in zip(names, thicknesses, strict=False)
    ]


LayerListStr = Annotated[
    list[OpaqueConstructionLayer], BeforeValidator(str_to_opaque_layer_list)
]


OpaqueConstructionType = Literal[
    "Roof",
    "Facade",
    "Slab",
    "Partition",
    "ExternalFloor",
    "ExteriorFloor",
    "GroundSlab",
    "GroundWall",
    "GroundFloor",
    "InternalMass",
    "InteriorFloor",
]


class OpaqueConstruction(
    NamedObject,
    StandardMaterializedMetadata,
    ManufacturerData,
    extra="forbid",
    populate_by_name=True,
):
    """Opaque construction object."""

    Layers: LayerListStr = Field(..., title="Layers of the opaque construction")
    VegetationLayer: NanStr = Field(
        ..., title="Vegetation layer of the opaque construction"
    )
    Type: OpaqueConstructionType = Field(..., title="Type of the opaque construction")

    def add_to_idf(
        self, doc: IDFDocument, material_defs: dict[str, OpaqueMaterial]
    ) -> IDFDocument:
        """Adds an opaque construction to an IDF document.

        Note that this will add the individual materials as well.

        Args:
            doc (IDFDocument): The IDF document to add the construction to.
            material_defs (list[OpaqueMaterial]): List of opaque material definitions.

        Returns:
            IDFDocument: The updated IDF document.
        """
        layer_names = [
            layer.add_material_to_idf(doc, material_defs).name for layer in self.Layers
        ]
        add_construction(doc, self.Name, layer_names)
        return doc


FuelType = Literal[
    "Electricity",
    "NaturalGas",
    "Propane",
    "FuelOil",
    "WoodPellets",
    "Coal",
    "Gasoline",
    "Diesel",
    "CustomFuel",
]


class ZoneConditioning(
    NamedObject, ClimateStudioMetadata, extra="forbid", populate_by_name=True
):
    """Zone conditioning object."""

    HeatingSetpoint: float = Field(
        ...,
        title="Heating setpoint [°C]",
        validation_alias="HeatingSetpoint [°C]",
        ge=0,
        le=100,
    )
    CoolingSetpoint: float = Field(
        ...,
        title="Cooling setpoint [°C]",
        validation_alias="CoolingSetpoint [°C]",
        ge=0,
        le=100,
    )
    # TODO: should we validate heating < cooling?
    HeatingSetpointConstant: BoolStr = Field(..., title="Heating setpoint constant")
    CoolingSetpointConstant: BoolStr = Field(..., title="Cooling setpoint constant")
    HeatingSetpointSchedule: str = Field(..., title="Heating setpoint schedule")
    CoolingSetpointSchedule: str = Field(..., title="Cooling setpoint schedule")
    MinFreshAirPerson: float = Field(
        ...,
        title="Minimum fresh air per person [L/s/p]",
        validation_alias="MinFreshAirPerson [L/s/p]",
        ge=0,
    )
    MinFreshAirArea: float = Field(
        ...,
        title="Minimum fresh air per area [L/s/m²]",
        validation_alias="MinFreshAirArea [L/s/m²]",
        ge=0,
    )
    CoolingCOP: float = Field(
        ...,
        title="Cooling Coefficient of Performance",
        ge=0,
    )
    HeatingCOP: float = Field(
        ...,
        title="Heating Coefficient of Performance",
        ge=0,
    )
    HeatIsOn: BoolStr = Field(..., title="Heat is on")
    CoolIsOn: BoolStr = Field(..., title="Cool is on")
    MechVentIsOn: BoolStr = Field(..., title="Mechanical ventilation is on")
    HumidistatIsOn: BoolStr = Field(
        ...,
        title="Humidistat is on",
        validation_alias="HumidistatIsOn [Bool]",
    )
    HeatingLimitType: IdealLoadsLimitType = Field(
        ...,
        title="Heating limit type",
        validation_alias="HeatingLimitType [enum]",
    )
    CoolingLimitType: IdealLoadsLimitType = Field(
        ...,
        title="Cooling limit type",
        validation_alias="CoolingLimitType [enum]",
    )
    MaxHeatingCapacity: float = Field(
        ...,
        title="Maximum heating capacity [W/m²]",
        validation_alias="MaxHeatingCapacity [W/m²]",
        ge=0,
    )
    MaxCoolingCapacity: float = Field(
        ...,
        title="Maximum cooling capacity [W/m²]",
        validation_alias="MaxCoolingCapacity [W/m²]",
        ge=0,
    )
    MaxHeatFlow: float = Field(
        ...,
        title="Maximum volumetric heat flow per flow area [m³/s/m²]",
        validation_alias="MaxHeatFlow [m³/s/m²]",
        ge=0,
    )
    MaxCoolFlow: float = Field(
        ...,
        title="Maximum volumetric cool flow per flow area [m³/s/m²]",
        validation_alias="MaxCoolFlow [m³/s/m²]",
        ge=0,
    )
    HeatingSchedule: str = Field(
        ...,
        title="Heating schedule",
        validation_alias="HeatingSchedule [Schedule name]",
    )
    CoolingSchedule: str = Field(
        ...,
        title="Cooling schedule",
        validation_alias="CoolingSchedule [Schedule name]",
    )
    MechVentSchedule: str = Field(
        ...,
        title="Mechanical ventilation schedule",
        validation_alias="MechVentSchedule [Schedule name]",
    )
    EconomizerType: OutdoorAirEconomizerTypeType = Field(
        ...,
        title="Economizer type",
        validation_alias="EconomizerType [enum]",
    )
    HeatRecoveryType: HeatRecoveryTypeType = Field(
        ...,
        title="Heat recovery type",
        validation_alias="HeatRecoveryType [enum]",
    )
    HeatRecoveryEfficiencySensible: float = Field(
        ...,
        title="Heat recovery efficiency sensible",
        ge=0,
        le=1,
        validation_alias="HeatRecoveryEfficiencySensible [0-1]",
    )
    HeatRecoveryEfficiencyLatent: float = Field(
        ...,
        title="Heat recovery efficiency latent",
        ge=0,
        le=1,
        validation_alias="HeatRecoveryEfficiencyLatent [0-1]",
    )
    MinHumidity: float = Field(
        ...,
        title="Minimum humidity [%]",
        ge=0,
        le=100,
        validation_alias="MinHumidity [RH%]",
    )
    MaxHumidity: float = Field(
        ...,
        title="Maximum humidity [%]",
        ge=0,
        le=100,
        validation_alias="MaxHumidity [RH%]",
    )
    EMSFanEnergyIsOn: BoolStr = Field(..., title="EMS fan energy is on")
    FanPressureRise: float = Field(
        ...,
        title="Fan pressure rise [Pa]",
        ge=0,
        validation_alias="FanPressureRise [Pa]",
    )
    MaxHeatSupplyAirTemp: float = Field(
        ...,
        title="Maximum heat supply air temperature [°C]",
        ge=0,
        validation_alias="MaxHeatSupplyAirTemp [°C]",
    )
    MinCoolSupplyAirTemp: float = Field(
        ...,
        title="Minimum cool supply air temperature [°C]",
        ge=0,
        validation_alias="MinCoolSupplyAirTemp [°C]",
    )
    HeatingSizingFactor: float = Field(
        ...,
        title="Heating sizing factor",
        ge=0,
        validation_alias="HeatingSizingFactor [Unitless]",
    )
    CoolingSizingFactor: float = Field(
        ...,
        title="Cooling sizing factor",
        ge=0,
        validation_alias="CoolingSizingFactor [Unitless]",
    )
    Autosize: BoolStr = Field(
        ...,
        title="Autosize",
        validation_alias="Autosize [Bool]",
    )
    HeatingFuelType: FuelType = Field(
        ...,
        title="Heating fuel type",
        validation_alias="HeatingFuelType [enum]",
    )
    CoolingFuelType: FuelType = Field(
        ...,
        title="Cooling fuel type",
        validation_alias="CoolingFuelType [enum]",
    )

    @property
    def schedule_names(self) -> set[str]:
        """Get the schedule names used in the object.

        Returns:
            set[str]: The schedule names.
        """
        cond_scheds = set()

        if self.HeatIsOn:
            cond_scheds.add(self.HeatingSchedule)

        if self.CoolIsOn:
            cond_scheds.add(self.CoolingSchedule)
        if not self.HeatingSetpointConstant and self.HeatIsOn:
            cond_scheds.add(self.HeatingSetpointSchedule)

        if not self.CoolingSetpointConstant and self.CoolIsOn:
            cond_scheds.add(self.CoolingSetpointSchedule)

        if self.MechVentIsOn:
            cond_scheds.add(self.MechVentSchedule)

        return cond_scheds

    def add_conditioning_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str
    ) -> IDFDocument:
        """Add conditioning to an IDF zone.

        This constructs HVAC template objects which get assigned to the zone.

        NB: currently, many of the climate studio parameters are ignored -
        particularly the ones related to humidity control.

        Args:
            doc (IDFDocument): The IDF document to add the conditioning to.
            target_zone_name (str): The name of the zone to add the conditioning to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        if self.HumidistatIsOn:
            raise NotImplementedClimateStudioParameter(
                "HumidistatIsOn",
                self.Name,
                "Conditioning",
            )

        if self.EMSFanEnergyIsOn:
            raise NotImplementedClimateStudioParameter(
                "EMSFanEnergyIsOn",
                self.Name,
                "Conditioning",
            )

        # TODO: better handling of alwayson/off schedule names
        # TODO: better handling of mech vent schedule
        logger.warning(
            f"Mechanical ventilation schedule is being ignored in zone {target_zone_name}."
        )
        thermostat = add_or_replace(
            doc,
            "HVACTemplate:Thermostat",
            f"{self.Name}_{target_zone_name}_Thermostat",
            heating_setpoint_schedule_name=(
                self.HeatingSetpointSchedule
                if not self.HeatingSetpointConstant
                else None
            ),
            constant_heating_setpoint=(
                self.HeatingSetpoint if self.HeatingSetpointConstant else None
            ),
            cooling_setpoint_schedule_name=(
                self.CoolingSetpointSchedule
                if not self.CoolingSetpointConstant
                else None
            ),
            constant_cooling_setpoint=(
                self.CoolingSetpoint if self.CoolingSetpointConstant else None
            ),
        )
        # The template has no name, so it is always added (never reused).
        add_or_replace(
            doc,
            "HVACTemplate:Zone:IdealLoadsAirSystem",
            "",
            zone_name=target_zone_name,
            template_thermostat_name=thermostat.name,
            system_availability_schedule_name="AlwaysOn",
            maximum_heating_supply_air_temperature=self.MaxHeatSupplyAirTemp,
            minimum_cooling_supply_air_temperature=self.MinCoolSupplyAirTemp,
            maximum_heating_supply_air_humidity_ratio=0.0156,
            minimum_cooling_supply_air_humidity_ratio=0.0077,
            heating_limit=self.HeatingLimitType,
            maximum_heating_air_flow_rate=self.MaxHeatFlow
            if not self.Autosize
            else "autosize",
            maximum_sensible_heating_capacity=self.MaxHeatingCapacity
            if not self.Autosize
            else "autosize",
            cooling_limit=self.CoolingLimitType,
            maximum_cooling_air_flow_rate=self.MaxCoolFlow
            if not self.Autosize
            else "autosize",
            maximum_total_cooling_capacity=self.MaxCoolingCapacity
            if not self.Autosize
            else "autosize",
            heating_availability_schedule_name=(
                self.HeatingSchedule if self.HeatIsOn else "AlwaysOff"
            ),
            cooling_availability_schedule_name=(
                self.CoolingSchedule if self.CoolIsOn else None
            ),
            dehumidification_control_type="None",
            cooling_sensible_heat_ratio=0.7,
            dehumidification_setpoint=60.0,
            humidification_control_type="None",
            humidification_setpoint=30.0,
            outdoor_air_method="Sum" if self.MechVentIsOn else "None",
            outdoor_air_flow_rate_per_person=self.MinFreshAirPerson
            / 1000,  # convert to m3
            outdoor_air_flow_rate_per_zone_floor_area=self.MinFreshAirArea
            / 1000,  # convert to m3
            outdoor_air_flow_rate_per_zone=0.0,
            demand_controlled_ventilation_type="None",
            outdoor_air_economizer_type=self.EconomizerType,
            heat_recovery_type=self.HeatRecoveryType,
            sensible_heat_recovery_effectiveness=self.HeatRecoveryEfficiencySensible,
            latent_heat_recovery_effectiveness=self.HeatRecoveryEfficiencyLatent,
        )
        if self.Autosize:
            add_or_replace(
                doc,
                "Sizing:Parameters",
                heating_sizing_factor=self.HeatingSizingFactor,
                cooling_sizing_factor=self.CoolingSizingFactor,
            )
        return doc


class ZoneConstruction(
    NamedObject, ClimateStudioMetadata, extra="forbid", populate_by_name=True
):
    """Zone construction object."""

    RoofConstruction: str = Field(..., title="Roof construction object name")
    FacadeConstruction: str = Field(..., title="Facade construction object name")
    SlabConstruction: str = Field(..., title="Slab construction object name")
    PartitionConstruction: str = Field(..., title="Partition construction object name")
    ExternalFloorConstruction: str = Field(
        ..., title="External floor construction object name"
    )
    GroundSlabConstruction: str = Field(
        ..., title="Ground slab construction object name"
    )
    GroundWallConstruction: str = Field(
        ..., title="Ground wall construction object name"
    )
    InternalMassConstruction: str = Field(
        ..., title="Internal mass construction object name"
    )
    InternalMassIsOn: BoolStr = Field(..., title="Internal mass is on")
    InternalMassExposedAreaPerArea: float = Field(
        ...,
        title="Internal mass exposed area per area [m²/m²]",
        validation_alias="InternalMassExposedAreaPerArea [area / floor (m2/m2)]",
    )
    GroundIsAdiabatic: BoolStr = Field(..., title="Ground is adiabatic")
    RoofIsAdiabatic: BoolStr = Field(..., title="Roof is adiabatic")
    FacadeIsAdiabatic: BoolStr = Field(..., title="Facade is adiabatic")
    SlabIsAdiabatic: BoolStr = Field(..., title="Slab is adiabatic")
    PartitionIsAdiabatic: BoolStr = Field(..., title="Partition is adiabatic")


class ZoneDefinition(NamedObject, extra="forbid"):
    """Zone definition object."""

    Loads: str = Field(..., title="Loads object name")
    Conditioning: str = Field(..., title="Conditioning object name")
    NaturalVentilation: str = Field(..., title="Natural ventilation object name")
    Constructions: str = Field(..., title="Construction object name")
    HotWater: str = Field(..., title="Hot water object name")
    Infiltration: str = Field(..., title="Infiltration object name")
    DataSource: NanStr = Field(
        ..., title="Data source of the object", validation_alias="Data Source"
    )


# InfCalculationMethodType = Literal["FlowExtArea", "ACH"]


class ZoneInfiltration(
    NamedObject, ClimateStudioMetadata, extra="forbid", populate_by_name=True
):
    """Zone infiltration object."""

    InfiltrationIsOn: BoolStr = Field(..., title="Infiltration is on")
    InfiltrationConstantCoefficient: float = Field(
        ...,
        title="Infiltration constant coefficient",
    )
    InfiltrationTemperatureCoefficient: float = Field(
        ...,
        title="Infiltration temperature coefficient",
    )
    InfiltrationWindVelocityCoefficient: float = Field(
        ...,
        title="Infiltration wind velocity coefficient",
    )
    InfiltrationWindVelocitySquaredCoefficient: float = Field(
        ...,
        title="Infiltration wind velocity squared coefficient",
    )
    AFN_AirMassFlowCoefficient_Crack: float = Field(
        ...,
        title="AFN air mass flow coefficient crack",
    )

    InfiltrationAch: float = Field(
        ...,
        title="Infiltration air changes per hour",
        ge=0,
        validation_alias="InfiltrationAch [ACH]",
    )
    InfiltrationFlowPerExteriorSurfaceArea: float = Field(
        ...,
        title="Infiltration flow per exterior surface area",
        ge=0,
        validation_alias="InfiltrationFlowPerExteriorSurfaceArea [m3/s/m2]",
    )
    CalculationMethod: InfDesignFlowRateCalculationMethodType = Field(
        ...,
        title="Calculation method",
    )

    def add_infiltration_to_idf_zone(
        self, doc: IDFDocument, target_zone_or_zone_list_name: str
    ):
        """Add infiltration to an IDF zone.

        Args:
            doc (IDFDocument): The IDF document to add the infiltration to.
            target_zone_or_zone_list_name (str): The name of the zone or zone list to add the infiltration to.

        Returns:
            doc (IDFDocument): The updated IDF document.
        """
        if not self.InfiltrationIsOn:
            return doc

        infiltration_schedule_name = (
            f"{target_zone_or_zone_list_name}_{self.Name}_Infiltration_Schedule"
        )
        inf_schedule = add_constant_schedule(
            doc, infiltration_schedule_name, 1, "Fraction"
        )
        add_or_replace(
            doc,
            "ZoneInfiltration:DesignFlowRate",
            f"{target_zone_or_zone_list_name}_{self.Name}_Infiltration",
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            schedule_name=inf_schedule.name,
            design_flow_rate_calculation_method=self.CalculationMethod,
            flow_rate_per_exterior_surface_area=self.InfiltrationFlowPerExteriorSurfaceArea,
            air_changes_per_hour=self.InfiltrationAch,
            constant_term_coefficient=self.InfiltrationConstantCoefficient,
            temperature_term_coefficient=self.InfiltrationTemperatureCoefficient,
            velocity_term_coefficient=self.InfiltrationWindVelocityCoefficient,
            velocity_squared_term_coefficient=self.InfiltrationWindVelocitySquaredCoefficient,
        )
        return doc


class WindowDefinition(NamedObject, ClimateStudioMetadata, extra="ignore"):
    """Window definition object."""

    Construction: str = Field(..., title="Construction object name")

    @property
    def schedule_names(self) -> set[str]:
        """Get the schedule names used in the object.

        Returns:
            set[str]: The schedule names.
        """
        return set()


class Foundation(BaseModel, extra="ignore"):
    """Foundation object."""

    pass


class OtherSettings(BaseModel, extra="ignore"):
    """Other settings object."""

    pass


class ZoneEnvelope(NamedObject, ClimateStudioMetadata, extra="forbid"):
    """Zone envelope object."""

    Constructions: ZoneConstruction
    Infiltration: ZoneInfiltration
    WindowDefinition: WindowDefinition | None
    WWR: float | None = Field(
        default=0.1, description="Window to wall ratio", ge=0, le=1
    )
    Foundation: Foundation | None
    OtherSettings: OtherSettings | None
    BuildingType: str | int = Field(..., title="Building type")

    # TODO: add envelope to idf zone
    # (currently in builder)

    @property
    def schedule_names(self) -> set[str]:
        """Get the schedule names used in the object.

        Returns:
            set[str]: The schedule names.
        """
        win_sch = (
            self.WindowDefinition.schedule_names if self.WindowDefinition else set()
        )
        return win_sch


DimmingTypeType = Literal["Off", "Stepped", "Continuous"]


class ZoneLoad(
    NamedObject, ClimateStudioMetadata, extra="forbid", populate_by_name=True
):
    """Zone load object."""

    BuildingType: str | int = Field(..., title="Building type")
    PeopleDensity: float = Field(
        ...,
        title="People density [people/m²]",
        ge=0,
        validation_alias="PeopleDensity [P/m²]",
    )
    MetabolicRate: float = Field(
        ...,
        title="Metabolic rate [met]",
        ge=0,
        validation_alias="MetabolicRate [met]",
    )
    AirspeedSchedule: str = Field(
        ..., title="Airspeed schedule", validation_alias="AirspeedSchedule [m/s]"
    )
    EquipmentPowerDensity: float = Field(
        ...,
        title="Equipment power density [W/m²]",
        ge=0,
        validation_alias="EquipmentPowerDensity [W/m²]",
    )
    LightingPowerDensity: float = Field(
        ...,
        title="Lighting power density [W/m²]",
        ge=0,
        validation_alias="LightingPowerDensity [W/m²]",
    )
    IlluminanceTarget: float = Field(
        ...,
        title="Illuminance target [lux]",
        ge=0,
        validation_alias="IlluminanceTarget [Lux]",
    )
    OccupancySchedule: str = Field(..., title="Occupancy schedule")
    EquipmentAvailabilitySchedule: str = Field(
        ...,
        title="Equipment availability schedule",
        validation_alias="EquipmentAvailibilitySchedule",  # known typo in cs
    )
    LightsAvailabilitySchedule: str = Field(
        ...,
        title="Lighting availability schedule",
        validation_alias="LightsAvailibilitySchedule",  # known typo in cs
    )
    DimmingType: DimmingTypeType = Field(
        ...,
        title="Dimming type",
    )
    PeopleIsOn: BoolStr = Field(..., title="People are on")
    EquipmentIsOn: BoolStr = Field(..., title="Equipment is on")
    LightsIsOn: BoolStr = Field(..., title="Lights are on")

    @property
    def schedule_names(self) -> set[str]:
        """Get the schedule names used in the object.

        Returns:
            set[str]: The schedule names.
        """
        return {
            # self.AirspeedSchedule,
            self.OccupancySchedule,
            self.EquipmentAvailabilitySchedule,
            self.LightsAvailabilitySchedule,
        }

    @property
    def MetabolicRate_W(self):
        """Get the metabolic rate in Watts."""
        avg_human_weight_kg = 80
        conversion_factor = 1.162  # W/kg
        return self.MetabolicRate * avg_human_weight_kg * conversion_factor

    def add_lights_to_idf_zone(
        self, doc: IDFDocument, target_zone_or_zone_list_name: str
    ) -> IDFDocument:
        """Add lights to an IDF zone.

        Note that this makes some assumptions about the fraction visible/radiant/replaceable.

        Args:
            doc (IDFDocument): The IDF document to add the lights to.
            target_zone_or_zone_list_name (str): The name of the zone or zone list to add the lights to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        if not self.LightsIsOn:
            return doc

        if self.DimmingType != "Off":
            raise NotImplementedClimateStudioParameter(
                "DimmingType:On", self.Name, "Lights"
            )

        logger.warning(
            f"Adding lights to zone with schedule {self.LightsAvailabilitySchedule}.  Make sure this schedule exists."
        )

        logger.warning(
            f"Ignoring IlluminanceTarget for zone(s) {target_zone_or_zone_list_name}."
        )
        add_or_replace(
            doc,
            "Lights",
            f"{target_zone_or_zone_list_name}_{self.Name.join('_')}_Lights",
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            schedule_name=self.LightsAvailabilitySchedule,
            design_level_calculation_method="Watts/Area",
            **{
                field_name(
                    doc, "Lights", "watts_per_floor_area", "watts_per_zone_floor_area"
                ): self.LightingPowerDensity
            },
            return_air_fraction=0.0,
            fraction_radiant=0.42,
            fraction_visible=0.18,
            fraction_replaceable=1.0,
        )
        return doc

    def add_people_to_idf_zone(
        self, doc: IDFDocument, target_zone_or_zone_list_name: str
    ) -> IDFDocument:
        """Add people to an IDF zone.

        Args:
            doc (IDFDocument): The IDF document to add the people to.
            target_zone_or_zone_list_name (str): The name of the zone or zone list to add the people to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        if not self.PeopleIsOn:
            return doc

        activity_sch_name = (
            f"{target_zone_or_zone_list_name}_{self.Name}_Activity_Schedule"
        )
        if "AnyNumber" not in doc["ScheduleTypeLimits"]:
            add_or_replace(
                doc,
                "ScheduleTypeLimits",
                "AnyNumber",
                numeric_type="Continuous",
                unit_type="Dimensionless",
            )
        activity_sch_year = add_constant_schedule(
            doc, activity_sch_name, self.MetabolicRate_W, "AnyNumber"
        )

        logger.warning(
            f"Adding people to zone with schedule {self.OccupancySchedule}.  Make sure this schedule exists."
        )
        logger.warning(
            f"Ignoring AirspeedSchedule for zone(s) {target_zone_or_zone_list_name}."
        )
        add_or_replace(
            doc,
            "People",
            f"{target_zone_or_zone_list_name}_{self.Name.join('_')}_People",
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            number_of_people_schedule_name=self.OccupancySchedule,
            number_of_people_calculation_method="People/Area",
            people_per_floor_area=self.PeopleDensity,
            fraction_radiant=0.3,
            sensible_heat_fraction="autocalculate",
            activity_level_schedule_name=activity_sch_year.name,
            enable_ashrae_55_comfort_warnings="No",
        )
        return doc

    def add_equipment_to_idf_zone(
        self, doc: IDFDocument, target_zone_or_zone_list_name: str
    ) -> IDFDocument:
        """Add equipment to an IDF zone.

        Args:
            doc (IDFDocument): The IDF document to add the equipment to.
            target_zone_or_zone_list_name (str): The name of the zone or zone list to add the equipment to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        if not self.EquipmentIsOn:
            return doc

        logger.warning(
            f"Adding equipment to zone with schedule {self.EquipmentAvailabilitySchedule}.  Make sure this schedule exists."
        )

        add_or_replace(
            doc,
            "ElectricEquipment",
            f"{target_zone_or_zone_list_name}_{self.Name.join('_')}_Equipment",
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            schedule_name=self.EquipmentAvailabilitySchedule,
            design_level_calculation_method="Watts/Area",
            **{
                field_name(
                    doc,
                    "ElectricEquipment",
                    "watts_per_floor_area",
                    "watts_per_zone_floor_area",
                ): self.EquipmentPowerDensity
            },
            fraction_latent=0.0,
            fraction_radiant=0.2,
            fraction_lost=0.0,
        )
        return doc

    def add_loads_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str
    ) -> IDFDocument:
        """Add the loads to an IDF zone.

        This will add the people, equipment, and lights to the zone.

        nb: remember to add the schedules.

        Args:
            doc (IDFDocument): The IDF document to add the loads to.
            target_zone_name (str): The name of the zone to add the loads to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        doc = self.add_lights_to_idf_zone(doc, target_zone_name)
        doc = self.add_people_to_idf_zone(doc, target_zone_name)
        doc = self.add_equipment_to_idf_zone(doc, target_zone_name)
        return doc


class ZoneHotWater(
    NamedObject, ClimateStudioMetadata, extra="ignore", populate_by_name=True
):
    """Zone Hot Water object."""

    DomHotWaterCOP: float = Field(
        ...,
        title="Domestic hot water coefficient of performance",
        ge=0,
    )
    WaterTemperatureInlet: float = Field(
        ...,
        title="Water temperature inlet [°C]",
        ge=0,
        le=100,
    )
    WaterSupplyTemperature: float = Field(
        ...,
        title="Water supply temperature [°C]",
        ge=0,
        le=100,
    )
    WaterSchedule: str = Field(..., title="Water schedule")
    FlowRatePerPerson: float = Field(
        ..., title="Flow rate per person [m3/hr/p]", ge=0, le=0.1
    )
    IsOn: BoolStr = Field(..., title="Is on")
    HotWaterFuelType: FuelType = Field(..., title="Hot water fuel type")

    @model_validator(mode="before")
    def validate_supply_greater_than_inlet(cls, values: dict[str, Any]):
        """Validate that the supply temperature is greater than the inlet temperature."""
        if values["WaterSupplyTemperature"] <= values["WaterTemperatureInlet"]:
            msg = "Water supply temperature must be greater than the inlet temperature."
            raise ValueError(msg)
        return values

    @property
    def schedule_names(self) -> set[str]:
        """Get the schedule names used in the object.

        Returns:
            set[str]: The schedule names.
        """
        return {self.WaterSchedule} if self.IsOn else set()

    def add_water_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str, total_ppl: float
    ) -> IDFDocument:
        """Add the hot water to an IDF zone.

        Args:
            doc (IDFDocument): The IDF document to add the hot water to.
            target_zone_name (str): The name of the zone to add the hot water to.
            total_ppl (float): The total number of people in the zone.

        Returns:
            IDFDocument: The updated IDF document.
        """
        if not self.IsOn:
            return doc

        total_flow_rate = self.FlowRatePerPerson * total_ppl  # m3/hr
        total_flow_rate_per_s = total_flow_rate / 3600  # m3/s

        if "Temperature" not in doc["ScheduleTypeLimits"]:
            add_or_replace(
                doc,
                "ScheduleTypeLimits",
                "Temperature",
                lower_limit_value=-60.0,
                upper_limit_value=200.0,
                numeric_type="Continuous",
                unit_type="Dimensionless",
            )

        target_temperature_yr_schedule = add_constant_schedule(
            doc,
            f"{target_zone_name}_{self.Name}_TargetWaterTemperatureSch",
            self.WaterSupplyTemperature,
            "Temperature",
        )
        inlet_temperature_yr_schedule = add_constant_schedule(
            doc,
            f"{target_zone_name}_{self.Name}_InletWaterTemperatureSch",
            self.WaterTemperatureInlet,
            "Temperature",
        )

        add_or_replace(
            doc,
            "WaterUse:Equipment",
            f"{target_zone_name}_{self.Name}_HotWater",
            end_use_subcategory="Domestic Hot Water",
            peak_flow_rate=float(total_flow_rate_per_s),
            flow_rate_fraction_schedule_name=self.WaterSchedule,
            target_temperature_schedule_name=target_temperature_yr_schedule.name,
            hot_water_supply_temperature_schedule_name=target_temperature_yr_schedule.name,
            cold_water_supply_temperature_schedule_name=inlet_temperature_yr_schedule.name,
            zone_name=target_zone_name,
        )
        return doc


class ZoneUse(
    NamedObject, ClimateStudioMetadata, extra="forbid", populate_by_name=True
):
    """Zone use object."""

    Conditioning: ZoneConditioning
    Loads: ZoneLoad
    HotWater: ZoneHotWater

    def add_loads_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str
    ) -> IDFDocument:
        """Add the loads to an IDF zone.

        This will add the people, equipment, and lights to the zone.

        nb: remember to add the schedules.

        Args:
            doc (IDFDocument): The IDF document to add the loads to.
            target_zone_name (str): The name of the zone to add the loads to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        doc = self.Loads.add_loads_to_idf_zone(doc, target_zone_name)
        return doc

    def add_conditioning_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str
    ) -> IDFDocument:
        """Add the conditioning to an IDF zone.

        Args:
            doc (IDFDocument): The IDF document to add the conditioning to.
            target_zone_name (str): The name of the zone to add the conditioning to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        doc = self.Conditioning.add_conditioning_to_idf_zone(doc, target_zone_name)
        return doc

    def add_hot_water_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str, zone_area: float
    ) -> IDFDocument:
        """Add the hot water to an IDF zone.

        Args:
            doc (IDFDocument): The IDF document to add the hot water to.
            target_zone_name (str): The name of the zone to add the hot water to.
            zone_area (float): The area of the zone.

        Returns:
            doc (IDFDocument): The updated IDF document.

        """
        total_people = self.Loads.PeopleDensity * zone_area
        doc = self.HotWater.add_water_to_idf_zone(
            doc, target_zone_name, total_ppl=total_people
        )
        return doc

    def add_space_use_to_idf_zone(
        self, doc: IDFDocument, target_zone: str | IDFObject
    ) -> IDFDocument:
        """Add the use to an IDF zone.

        This will add the loads and conditioning to the zone.

        Args:
            doc (IDFDocument): The IDF document to add the use to.
            target_zone (str | IDFObject): The name of the zone, or the `ZoneList`, to add the use to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        loads_target = target_zone if isinstance(target_zone, str) else target_zone.name
        doc = self.add_loads_to_idf_zone(doc, loads_target)
        if isinstance(target_zone, str):
            doc = self.add_conditioning_to_idf_zone(doc, target_zone)
        else:
            for zone in zone_list_names(target_zone):
                doc = self.add_conditioning_to_idf_zone(doc, zone)
        return doc

    @property
    def schedule_names(self) -> set[str]:
        """Get the schedule names used in the object.

        Returns:
            set[str]: The schedule names.
        """
        return (
            self.Loads.schedule_names
            | self.Conditioning.schedule_names
            | self.HotWater.schedule_names
        )


NamedType = TypeVar("NamedType", bound=NamedObject)


class LibraryScheduleTypeLimits(BaseModel):
    """The type limits of a library schedule (as stored in library JSON files)."""

    Name: str
    LowerLimit: float | None = None
    UpperLimit: float | None = None
    NumericType: Literal["Continuous", "Discrete"] | None = "Continuous"
    UnitType: str = "Dimensionless"

    def add_to_idf(self, doc: IDFDocument) -> IDFObject:
        """Write the `ScheduleTypeLimits` object (an identical one is kept as is).

        Args:
            doc (IDFDocument): The IDF document to add the type limits to.

        Returns:
            IDFObject: The `ScheduleTypeLimits` object.
        """
        return add_or_replace(
            doc,
            "ScheduleTypeLimits",
            self.Name,
            lower_limit_value=self.LowerLimit,
            upper_limit_value=self.UpperLimit,
            numeric_type=self.NumericType,
            unit_type=self.UnitType,
        )


class LibrarySchedule(BaseModel):
    """An hourly year schedule of a climate studio library."""

    Name: str
    Type: LibraryScheduleTypeLimits
    Values: list[float]

    def add_to_idf(self, doc: IDFDocument) -> IDFObject:
        """Write the schedule as `Schedule:Year` (with week/day objects) and its type limits.

        Args:
            doc (IDFDocument): The IDF document to add the schedule to.

        Returns:
            IDFObject: The `Schedule:Year` object.
        """
        self.Type.add_to_idf(doc)
        return add_values_schedule(doc, self.Name, self.Values, self.Type.Name)


class ClimateStudioLibraryV2(BaseModel):
    """Climate Studio library object."""

    SpaceUses: dict[str, ZoneUse]
    Envelopes: dict[str, ZoneEnvelope]
    GlazingConstructions: dict[str, GlazingConstructionSimple]
    OpaqueConstructions: dict[str, OpaqueConstruction]
    OpaqueMaterials: dict[str, OpaqueMaterial]
    Schedules: dict[str, LibrarySchedule]


class ClimateStudioLibraryV1(BaseModel):
    """Climate Studio library object."""

    # DaySchedules: dict[str, DaySchedule]
    # DomHotWater: dict[str, DomHotWater]
    # WindowSettings: dict[str, WindowSettings]
    # NaturalVentilation: dict[str, NaturalVentilation] ?
    GasMaterials: dict[str, GasMaterial]
    GlazingConstructionSimple: dict[str, GlazingConstructionSimple]
    GlazingMaterials: dict[str, GlazingMaterial]
    OpaqueMaterials: dict[str, OpaqueMaterial]
    OpaqueConstructions: dict[str, OpaqueConstruction]
    ZoneConditioning: dict[str, ZoneConditioning]
    ZoneConstruction: dict[str, ZoneConstruction]
    ZoneDefinition: dict[str, ZoneDefinition]
    ZoneInfiltration: dict[str, ZoneInfiltration]
    ZoneLoad: dict[str, ZoneLoad]
    Schedules: dict[str, LibrarySchedule]

    @classmethod
    @validate_call
    def Load(cls, base_path: Path):
        """Load a Climate Studio library from a directory.

        The directory should have all the necessary named files.

        Args:
            base_path (Path): The base path to the library directory.

        Returns:
            lib (ClimateStudioLibrary): The Climate Studio library object.
        """
        if isinstance(base_path, str):
            base_path = Path(base_path)

        gas_materials = cls.LoadObjects(base_path, GasMaterial, pluralize=True)
        glass_consts_simple = cls.LoadObjects(base_path, GlazingConstructionSimple)
        glazing_materials = cls.LoadObjects(base_path, GlazingMaterial, pluralize=True)
        opaque_materials = cls.LoadObjects(base_path, OpaqueMaterial, pluralize=True)
        opaque_consts = cls.LoadObjects(base_path, OpaqueConstruction, pluralize=True)
        zone_constructions = cls.LoadObjects(base_path, ZoneConstruction)
        zone_definitions = cls.LoadObjects(base_path, ZoneDefinition)
        zone_conditioning = cls.LoadObjects(base_path, ZoneConditioning)
        zone_infiltrations = cls.LoadObjects(base_path, ZoneInfiltration)
        zone_loads = cls.LoadObjects(base_path, ZoneLoad)

        year_schs = pd.read_csv(base_path / "YearSchedules.csv", dtype=str)
        sch_names = year_schs.columns
        schedules_list = [extract_sch(year_schs, sch_name) for sch_name in sch_names]
        schedules = {sch.Name: sch for sch in schedules_list}
        if len(schedules) != len(schedules_list):
            raise ClimateStudioLibraryDuplicatesFound("Schedules")

        return cls(
            GasMaterials=gas_materials,
            GlazingConstructionSimple=glass_consts_simple,
            GlazingMaterials=glazing_materials,
            OpaqueMaterials=opaque_materials,
            OpaqueConstructions=opaque_consts,
            ZoneConditioning=zone_conditioning,
            ZoneConstruction=zone_constructions,
            ZoneDefinition=zone_definitions,
            ZoneInfiltration=zone_infiltrations,
            ZoneLoad=zone_loads,
            Schedules=schedules,
        )

    @classmethod
    def LoadObjects(
        cls, base_path: Path, obj_class: type[NamedType], pluralize: bool = False
    ) -> dict[str, NamedType]:
        """Handles deserializing a ClimateStudio CSV to the appropriate class.

        Args:
            base_path (Path): The base path to the library directory.
            obj_class (Type[NamedObject]): The class to deserialize to.
            pluralize (bool, optional): Whether to pluralize the filename. Defaults to False.

        Returns:
            dict[str, NamedObject]: The deserialized objects.
        """
        df = pd.read_csv(
            base_path / f"{obj_class.__name__}{'s' if pluralize else ''}.csv"
        )
        data = df.to_dict(orient="records")
        obj_list = [obj_class.model_validate(d) for d in data]
        obj_dict = {obj.Name: obj for obj in obj_list}
        if len(obj_dict) != len(obj_list):
            raise ClimateStudioLibraryDuplicatesFound(obj_class.__name__)
        return obj_dict


def _type_limits_for(sched_type: str) -> LibraryScheduleTypeLimits:
    """The type limits of a climate studio schedule type (as archetypal resolved them)."""
    lowered = sched_type.lower()
    if lowered in ("any number", "anynumber"):
        return LibraryScheduleTypeLimits(Name=sched_type)
    if lowered == "temperature":
        return LibraryScheduleTypeLimits(
            Name="Temperature", LowerLimit=-100, UpperLimit=100
        )
    if lowered == "on/off":
        return LibraryScheduleTypeLimits(
            Name="On/Off",
            LowerLimit=0,
            UpperLimit=1,
            NumericType="Discrete",
            UnitType="Availability",
        )
    return LibraryScheduleTypeLimits(Name="Fraction", LowerLimit=0, UpperLimit=1)


def extract_sch(year_schedules: pd.DataFrame, schedule_name: str) -> LibrarySchedule:
    """Extract a schedule from a climate studio schedule dataframe.

    Args:
        year_schedules (pd.DataFrame): Dataframe of year schedules
        schedule_name (str): Name of the schedule

    Returns:
        LibrarySchedule: Extracted schedule
    """
    sched_meta = year_schedules.head(5)
    sched_meta.index = pd.Index([
        "Type",
        "Periodicity",
        "Category",
        "Data Source",
        "Comment",
    ])
    meta = sched_meta[schedule_name]
    sched_type = cast(str, meta["Type"])
    last_ix = (
        8760
        if meta["Periodicity"] == "FullYear"
        else (
            24 * 7
            if meta["Periodicity"] == "RepeatingWeek"
            else (24 if meta["Periodicity"] == "RepeatingDay" else 1)
        )
    )
    sched = year_schedules[schedule_name]
    sched_vals = sched.iloc[5:]
    sched_vals = np.array(sched_vals[:last_ix].astype(float).values)
    if len(sched_vals) not in [1, 24, 24 * 7, 8760]:
        raise ScheduleParseError(schedule_name)
    if sched_type.lower() not in [
        "fraction",
        "temperature",
        "any number",
        "anynumber",
        "on/off",
    ]:
        raise ScheduleParseError(f"{schedule_name}:{meta['Type']}")
    n_repeats_needed = HOURS_PER_YEAR // len(sched_vals) + 1
    repeated_schedule = np.tile(sched_vals, n_repeats_needed)[:HOURS_PER_YEAR]
    return LibrarySchedule(
        Name=schedule_name,
        Values=repeated_schedule.tolist(),
        Type=_type_limits_for(sched_type),
    )


if __name__ == "__main__":
    from pathlib import Path

    import pandas as pd

    base_path = Path("D:/climatestudio/default")

    lib = ClimateStudioLibraryV1.Load(base_path)


class SurfaceHandler(BaseModel):
    """A handler for filtering and adding surfaces to a model."""

    boundary_condition: str | None
    original_construction_name: str | None
    original_surface_type: str | None
    surface_group: Literal["glazing", "opaque"]

    def assign_srfs(
        self, doc: IDFDocument, lib: ClimateStudioLibraryV2, construction_name: str
    ) -> IDFDocument:
        """Adds a construction (and its materials) to an IDF and assigns it to matching surfaces.

        Args:
            doc (IDFDocument): The IDF model to add the construction to.
            lib (ClimateStudioLibraryV2): The library of constructions.
            construction_name (str): The name of the construction to add.
        """
        srf_key = (
            "FenestrationSurface:Detailed"
            if self.surface_group == "glazing"
            else "BuildingSurface:Detailed"
        )
        if self.boundary_condition is not None and self.surface_group == "glazing":
            raise NotImplementedClimateStudioParameter(
                "BoundaryCondition", self.surface_group, "Glazing"
            )

        srfs = [srf for srf in doc[srf_key] if self.check_srf(srf)]
        construction_lib = (
            lib.OpaqueConstructions
            if self.surface_group != "glazing"
            else lib.GlazingConstructions
        )
        if construction_name not in construction_lib:
            raise KeyError(
                f"MISSING_CONSTRUCTION:{construction_name}:TARGET={self.__repr__()}"
            )
        construction = construction_lib[construction_name]
        doc = (
            construction.add_to_idf(doc)
            if isinstance(construction, GlazingConstructionSimple)
            else construction.add_to_idf(doc, lib.OpaqueMaterials)
        )
        for srf in srfs:
            srf.construction_name = construction.Name
        return doc

    def check_srf(self, srf: IDFObject):
        """Check if the surface matches the filters.

        Args:
            srf (IDFObject): The surface to check.

        Returns:
            match (bool): True if the surface matches the filters.
        """
        return (
            self.check_construction_type(srf)
            and self.check_boundary(srf)
            and self.check_construction_name(srf)
        )

    def check_construction_type(self, srf: IDFObject):
        """Check if the surface matches the construction type.

        Args:
            srf (IDFObject): The surface to check.

        Returns:
            match (bool): True if the surface matches the construction type.
        """
        if self.surface_group == "glazing":
            # Ignore the construction type check for windows
            return True
        if self.original_surface_type is None:
            # Ignore the construction type check when filter not provided
            return True
        # Check the construction type
        return self.original_surface_type.lower() == (srf.surface_type or "").lower()

    def check_boundary(self, srf: IDFObject):
        """Check if the surface matches the boundary condition.

        Args:
            srf (IDFObject): The surface to check.

        Returns:
            match (bool): True if the surface matches the boundary condition.
        """
        if self.surface_group == "glazing":
            # Ignore the bc filter check for windows
            return True
        if self.boundary_condition is None:
            # Ignore the bc filter when filter not provided
            return True
        # Check the boundary condition
        return (
            srf.outside_boundary_condition or ""
        ).lower() == self.boundary_condition.lower()

    def check_construction_name(self, srf: IDFObject):
        """Check if the surface matches the original construction name.

        Args:
            srf (IDFObject): The surface to check.

        Returns:
            match (bool): True if the surface matches the original construction name.
        """
        if self.original_construction_name is None:
            # Ignore the original construction name check when filter not provided
            return True
        # Check the original construction name
        return (
            srf.construction_name or ""
        ).lower() == self.original_construction_name.lower()


class SurfaceHandlers(BaseModel):
    """A collection of surface handlers for different surface types."""

    Roof: SurfaceHandler
    Facade: SurfaceHandler
    Slab: SurfaceHandler
    Ceiling: SurfaceHandler
    Partition: SurfaceHandler
    GroundSlab: SurfaceHandler
    GroundWall: SurfaceHandler
    Window: SurfaceHandler

    @classmethod
    def Default(cls):
        """Get the default surface handlers."""
        roof_handler = SurfaceHandler(
            boundary_condition="outdoors",
            original_construction_name=None,
            original_surface_type="roof",
            surface_group="opaque",
        )
        facade_handler = SurfaceHandler(
            boundary_condition="outdoors",
            original_construction_name=None,
            original_surface_type="wall",
            surface_group="opaque",
        )
        partition_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="wall",
            surface_group="opaque",
        )
        ground_wall_handler = SurfaceHandler(
            boundary_condition="ground",
            original_construction_name=None,
            original_surface_type="wall",
            surface_group="opaque",
        )
        slab_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="floor",
            surface_group="opaque",
        )
        ceiling_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="ceiling",
            surface_group="opaque",
        )
        ground_slab_handler = SurfaceHandler(
            boundary_condition="ground",
            original_construction_name=None,
            original_surface_type="floor",
            surface_group="opaque",
        )
        window_handler = SurfaceHandler(
            boundary_condition=None,
            original_construction_name=None,
            original_surface_type=None,
            surface_group="glazing",
        )

        return cls(
            Roof=roof_handler,
            Facade=facade_handler,
            Slab=slab_handler,
            Ceiling=ceiling_handler,
            Partition=partition_handler,
            GroundSlab=ground_slab_handler,
            GroundWall=ground_wall_handler,
            Window=window_handler,
        )

    def handle_envelope(
        self,
        doc: IDFDocument,
        lib: ClimateStudioLibraryV2,
        constructions: ZoneConstruction,
        window: WindowDefinition | None,
    ):
        """Assign the envelope to the IDF model.

        Note that this will add a "reversed" construction for the floorsystem slab/ceiling

        Args:
            doc (IDFDocument): The IDF model to add the envelope to.
            lib (ClimateStudioLibraryV2): The library of constructions.
            constructions (ZoneConstruction): The construction names for the envelope.
            window (WindowDefinition | None): The window definition.

        Returns:
            doc (IDFDocument): The updated IDF model.
        """

        # outside walls are the ones with outdoor boundary condition and vertical orientation
        def make_reversed(const: OpaqueConstruction):
            new_const = const.model_copy(deep=True)
            new_const.Layers = new_const.Layers[::-1]
            new_const.Name = f"{const.Name}_Reversed"
            return new_const

        def reverse_construction(const_name: str, lib: ClimateStudioLibraryV2):
            const = lib.OpaqueConstructions[const_name]
            new_const = make_reversed(const)
            return new_const

        slab_reversed = reverse_construction(constructions.SlabConstruction, lib)
        lib.OpaqueConstructions[slab_reversed.Name] = slab_reversed

        doc = self.Roof.assign_srfs(
            doc=doc, lib=lib, construction_name=constructions.RoofConstruction
        )
        doc = self.Facade.assign_srfs(
            doc=doc, lib=lib, construction_name=constructions.FacadeConstruction
        )
        doc = self.Partition.assign_srfs(
            doc=doc, lib=lib, construction_name=constructions.PartitionConstruction
        )
        doc = self.Slab.assign_srfs(
            doc=doc, lib=lib, construction_name=slab_reversed.Name
        )
        doc = self.Ceiling.assign_srfs(
            doc=doc, lib=lib, construction_name=constructions.SlabConstruction
        )
        doc = self.GroundSlab.assign_srfs(
            doc=doc, lib=lib, construction_name=constructions.GroundSlabConstruction
        )
        doc = self.GroundWall.assign_srfs(
            doc=doc, lib=lib, construction_name=constructions.GroundWallConstruction
        )
        if window:
            doc = self.Window.assign_srfs(
                doc=doc, lib=lib, construction_name=window.Construction
            )
        return doc
