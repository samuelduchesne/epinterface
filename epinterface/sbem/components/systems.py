"""Systems components for the SBEM library."""

from typing import Literal, cast

import numpy as np
from pydantic import Field, model_validator

from epinterface.constants import assumed_constants
from epinterface.document import EPDocument
from epinterface.sbem.common import BoolStr, MetadataMixin, NamedObject
from epinterface.sbem.components.schedules import YearComponent

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
    "Steam",
    "ChilledWater",
]
HeatingSystemType = Literal[
    "ElectricResistance", "GasBoiler", "GasFurnace", "ASHP", "GSHP"
]
CoolingSystemType = Literal["DX", "EvapCooling"]
DistributionType = Literal["Hydronic", "Air", "Steam"]


class ThermalSystemComponent(NamedObject, MetadataMixin, extra="forbid"):
    """A thermal system object in the SBEM library."""

    ConditioningType: Literal["Heating", "Cooling", "HeatingAndCooling"]
    Fuel: FuelType
    SystemCOP: float = Field(
        ...,
        title="System COP",
        ge=0,
    )
    DistributionCOP: float = Field(..., title="Distribution COP", ge=0)
    EIRTemperatureSlope: float = Field(
        default=0.0,
        title="Slope of the energy input ratio with outdoor temperature [1/K]",
        description=(
            "Change of the system's energy input ratio (1/SystemCOP) per kelvin of "
            "outdoor dry-bulb temperature above `EIRReferenceTemperature`. Each "
            "hour's consumed energy is delivered energy times "
            "max(0, 1/SystemCOP + EIRTemperatureSlope * (T_out - "
            "EIRReferenceTemperature)) / DistributionCOP. 0: a constant COP."
        ),
    )
    EIRReferenceTemperature: float | None = Field(
        default=None,
        title="Reference outdoor temperature of the energy input ratio [degC]",
        description=(
            "Outdoor dry-bulb temperature at which the energy input ratio is "
            "1/SystemCOP. Needed when `EIRTemperatureSlope` is not 0."
        ),
    )

    @model_validator(mode="after")
    def check_eir_reference(self):
        """A temperature-dependent energy input ratio needs its reference temperature."""
        if self.EIRTemperatureSlope != 0 and self.EIRReferenceTemperature is None:
            msg = "EIRTemperatureSlope needs an EIRReferenceTemperature."
            raise ValueError(msg)
        return self

    def energy_input_ratio(
        self, outdoor_temperature: "float | np.ndarray"
    ) -> np.ndarray:
        """The effective energy input ratio (consumed / delivered) at each outdoor temperature.

        Args:
            outdoor_temperature: Outdoor dry-bulb temperatures [degC], a float or an
                array.

        Returns:
            eir: max(0, 1/SystemCOP + EIRTemperatureSlope * (T - EIRReferenceTemperature))
                / DistributionCOP, of the same shape. With a zero slope this is
                1 / effective_system_cop.
        """
        t = np.asarray(outdoor_temperature, dtype=float)
        ratio = np.full_like(t, 1 / self.SystemCOP)
        if self.EIRTemperatureSlope != 0:
            reference = cast(float, self.EIRReferenceTemperature)
            ratio = ratio + self.EIRTemperatureSlope * (t - reference)
        return np.maximum(ratio, 0.0) / self.DistributionCOP

    @property
    def effective_system_cop(self) -> float:
        """Compute the effective system COP based on the system and distribution COPs.

        Returns:
            cop (float): The effective system COP.
        """
        return self.SystemCOP * self.DistributionCOP

    @property
    def HeatingSystemType(self) -> HeatingSystemType:
        """Compute the heating system type based on the system COP.

        Returns:
            heating_system_type (HeatingSystemType): The heating system type.
        """
        if (
            self.ConditioningType != "Heating"
            and self.ConditioningType != "HeatingAndCooling"
        ):
            msg = "Heating system type is only applicable to heating systems."
            raise ValueError(msg)
        # TODO: compute based off of CoP
        msg = "Heating system type is not implemented."
        raise NotImplementedError(msg)
        return "ElectricResistance"

    @property
    def CoolingSystemType(self) -> CoolingSystemType:
        """Compute the cooling system type based on the system COP.

        Returns:
            cooling_system_type (CoolingSystemType): The cooling system type.
        """
        if (
            self.ConditioningType != "Cooling"
            and self.ConditioningType != "HeatingAndCooling"
        ):
            msg = "Cooling system type is only applicable to cooling systems."
            raise ValueError(msg)
        # TODO: compute based off of CoP
        msg = "Cooling system type is not implemented."
        raise NotImplementedError(msg)
        return "DX"

    @property
    def DistributionType(self) -> DistributionType:
        """Compute the distribution type based on the system COP.

        Returns:
            distribution_type (DistributionType): The distribution type.
        """
        # TODO: compute based off of CoP
        msg = "Distribution type is not implemented."
        raise NotImplementedError(msg)
        return "Hydronic"


class ConditioningSystemsComponent(NamedObject, MetadataMixin, extra="forbid"):
    """A conditioning system object in the SBEM library."""

    Heating: ThermalSystemComponent | None
    Cooling: ThermalSystemComponent | None
    MaximumHeatingSupplyAirTemperature: float = Field(
        default=30.0,
        title="Maximum heating supply air temperature [degC]",
        description="The ideal loads' maximum supply air temperature when heating.",
        gt=0,
        lt=100,
    )
    MinimumCoolingSupplyAirTemperature: float = Field(
        default=13.0,
        title="Minimum cooling supply air temperature [degC]",
        description="The ideal loads' minimum supply air temperature when cooling.",
        gt=-100,
        lt=50,
    )
    SpecificFanPower: float | None = Field(
        default=None,
        title="Specific fan power [W/(m3/s)]",
        description=(
            "Fan electric power per volume flow of supply air. The fan end use is "
            "this times the ideal loads' hourly supply air volume (at standard "
            "density). None: no fan end use."
        ),
        ge=0,
    )

    @model_validator(mode="after")
    def validate_conditioning_types(self):
        """Validate that the conditioning types are correct.

        Cannot have a heating system assigned to a cooling system and vice versa.
        """
        if self.Heating and "heating" not in self.Heating.ConditioningType.lower():
            msg = "Heating system type is only applicable to heating systems."
            raise ValueError(msg)
        if self.Cooling and "cooling" not in self.Cooling.ConditioningType.lower():
            msg = "Cooling system type is only applicable to cooling systems."
            raise ValueError(msg)
        if (
            self.MaximumHeatingSupplyAirTemperature
            <= self.MinimumCoolingSupplyAirTemperature
        ):
            msg = (
                "MaximumHeatingSupplyAirTemperature must be above "
                "MinimumCoolingSupplyAirTemperature."
            )
            raise ValueError(msg)

        return self


VentilationProvider = Literal["None", "Natural", "Mechanical", "Both"]

EconomizerMethod = Literal[
    "NoEconomizer", "DifferentialDryBulb", "DifferentialEnthalpy"
]

HRVMethod = Literal["NoHRV", "Sensible", "Enthalpy"]

DCVMethod = Literal["NoDCV", "OccupancySchedule", "CO2Setpoint"]


class VentilationComponent(NamedObject, MetadataMixin, extra="forbid"):
    """A ventilation object in the SBEM library."""

    # TODO: add unit notes in field descriptions
    FreshAirPerFloorArea: float = Field(
        ...,
        title="Fresh air per m2 of the object [m³/s/m²]",
        ge=0,
        le=0.05,
    )
    FreshAirPerPerson: float = Field(
        ...,
        title="Fresh air per person of the object [m³/s/p]",
        ge=0,
        le=0.05,
    )
    Schedule: YearComponent = Field(..., title="Ventilation schedule of the object")
    Provider: VentilationProvider = Field(..., title="Type of the object")
    HRV: HRVMethod = Field(..., title="HRV type of the object")
    Economizer: EconomizerMethod = Field(..., title="Economizer type of the object")
    DCV: DCVMethod = Field(..., title="DCV type of the object")
    SensibleHeatRecoveryEffectiveness: float | None = Field(
        default=None,
        title="Sensible heat recovery effectiveness [0-1]",
        description=(
            "Sensible effectiveness of the heat recovery at 100% airflow. Used when "
            "HRV is not NoHRV. None: epinterface's assumed constant (0.70)."
        ),
        ge=0,
        le=1,
    )
    LatentHeatRecoveryEffectiveness: float | None = Field(
        default=None,
        title="Latent heat recovery effectiveness [0-1]",
        description=(
            "Latent effectiveness of the heat recovery at 100% airflow. Used when "
            "HRV is Enthalpy. None: epinterface's assumed constant (0.65)."
        ),
        ge=0,
        le=1,
    )

    NatVentMinOutdoorAirTemp: float = Field(
        default=12.0,
        title="Natural ventilation minimum outdoor temperature [degC]",
        description="Windows stay closed below this outdoor dry-bulb temperature.",
        ge=-100,
        le=100,
    )
    NatVentMaxOutdoorAirTemp: float = Field(
        default=25.0,
        title="Natural ventilation maximum outdoor temperature [degC]",
        description="Windows stay closed above this outdoor dry-bulb temperature.",
        ge=-100,
        le=100,
    )
    NatVentMaxRelHumidity: float | None = Field(
        default=None,
        title="Natural ventilation maximum outdoor relative humidity [%]",
        description=(
            "Windows stay closed when the outdoor relative humidity is above this "
            "value. None: no humidity limit."
        ),
        ge=0,
        le=100,
    )
    NatVentZoneTempSetpoint: float | None = Field(
        default=None,
        title="Natural ventilation minimum zone temperature [degC]",
        description=(
            "Windows stay closed when the zone air temperature is below this "
            "value. None: no indoor limit."
        ),
        ge=-100,
        le=100,
    )
    IsWindOn: bool = Field(
        default=True,
        title="Wind-driven natural ventilation",
        description="Whether wind drives air through the open windows.",
    )
    IsBuoyancyOn: bool = Field(
        default=False,
        title="Buoyancy-driven natural ventilation",
        description=(
            "Whether the stack effect drives air through the open windows, with a "
            "height difference of half the zone's tallest window. False: no stack "
            "effect, as before this field existed."
        ),
    )

    @property
    def sensible_heat_recovery_effectiveness(self) -> float:
        """The sensible effectiveness the model uses: the field, or the assumed constant."""
        if self.SensibleHeatRecoveryEffectiveness is not None:
            return self.SensibleHeatRecoveryEffectiveness
        return assumed_constants.Sensible_Heat_Recovery_Effectiveness

    @property
    def latent_heat_recovery_effectiveness(self) -> float:
        """The latent effectiveness the model uses: the field, or the assumed constant."""
        if self.LatentHeatRecoveryEffectiveness is not None:
            return self.LatentHeatRecoveryEffectiveness
        return assumed_constants.Latent_Heat_Recovery_Effectiveness

    @model_validator(mode="after")
    def validate_ventilation_systems(self):
        """Validate that the ventilation systems are correct.

        If the ventilation type is natural, then the zone cannot have variants of mechanical ventilation systems (e.g, HRV, DCV, Economizer).
        """
        if self.Provider == "Natural":
            if self.HRV != "NoHRV":
                msg = "Natural ventilation systems can't have HRV."
                raise ValueError(msg)
            if self.DCV != "NoDCV":
                msg = "Natural ventilation systems can't have DCV."
                raise ValueError(msg)
            if self.Economizer != "NoEconomizer":
                msg = "Natural ventilation systems can't have an Economizer."
                raise ValueError(msg)
        if self.NatVentMinOutdoorAirTemp >= self.NatVentMaxOutdoorAirTemp:
            msg = "NatVentMinOutdoorAirTemp must be below NatVentMaxOutdoorAirTemp."
            raise ValueError(msg)
        if self.Provider == "None":
            if self.HRV != "NoHRV":
                msg = "None ventilation systems can't have HRV."
                raise ValueError(msg)
            if self.DCV != "NoDCV":
                msg = "None ventilation systems can't have DCV."
                raise ValueError(msg)
            if self.Economizer != "NoEconomizer":
                msg = "None ventilation systems can't have an Economizer."
                raise ValueError(msg)
        return self


class ZoneHVACComponent(
    NamedObject,
    MetadataMixin,
    extra="forbid",
):
    """Conditioning object in the SBEM library."""

    ConditioningSystems: ConditioningSystemsComponent
    Ventilation: VentilationComponent
    # TODO: change the structure like ZoneSpaceUse
    """Zone conditioning object."""

    def add_conditioning_to_idf_zone(
        self, doc: EPDocument, target_zone_name: str
    ) -> EPDocument:
        """Add conditioning to an IDF zone.

        This constructs HVAC template objects which get assigned to the zone.

        NB: currently, many of the climate studio parameters are ignored -
        particularly the ones related to humidity control.

        Args:
            doc (EPDocument): The IDF document to add the conditioning to.
            target_zone_name (str): The name of the zone to add the conditioning to.

        Returns:
            EPDocument: The updated IDF document.
        """
        # TODO: add the idf conversion functions

        return doc


DHWFuelType = Literal["Electricity", "NaturalGas", "Propane", "FuelOil", "Steam"]


class DHWComponent(
    NamedObject,
    MetadataMixin,
    extra="forbid",
):
    """Domestic Hot Water object."""

    SystemCOP: float = Field(
        ...,
        title="Domestic hot water coefficient of performance",
        ge=0,
    )
    WaterTemperatureInlet: float = Field(
        ...,
        title="Water temperature inlet [°C]",
        ge=0,
        le=100,
    )  # TODO:remove this or just set as constant. Leaving for flexibility here

    DistributionCOP: float = Field(
        ...,
        title="Distribution coefficient of performance",
        ge=0,
        le=1,
    )

    WaterSupplyTemperature: float = Field(
        ...,
        title="Water supply temperature [°C]",
        ge=0,
        le=100,
    )
    IsOn: BoolStr = Field(..., title="Is on")
    FuelType: DHWFuelType = Field(..., title="Hot water fuel type")

    @model_validator(mode="after")
    def validate_supply_greater_than_inlet(self):
        """Validate that the supply temperature is greater than the inlet temperature."""
        if self.WaterSupplyTemperature <= self.WaterTemperatureInlet:
            msg = "Water supply temperature must be greater than the inlet temperature."
            raise ValueError(msg)
        return self

    @property
    def effective_system_cop(self) -> float:
        """Compute the effective system COP based on the system and distribution COPs.

        Returns:
            cop (float): The effective system COP.
        """
        return self.SystemCOP * self.DistributionCOP
