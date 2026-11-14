"""Flat model used for calibration."""

from collections.abc import Callable
from pathlib import Path

from idfkit import Vector3D, rotate_building
from idfkit.geometry import get_surface_coords
from pydantic import BaseModel, Field

from epinterface.analysis.overheating import OverheatingAnalysisConfig
from epinterface.document import EPDocument
from epinterface.geometry import ShoeboxGeometry
from epinterface.sbem.builder import AtticAssumptions, BasementAssumptions, Model
from epinterface.sbem.components.envelope import (
    ConstructionAssemblyComponent,
    ConstructionLayerComponent,
    EnvelopeAssemblyComponent,
    GlazingConstructionSimpleComponent,
    InfiltrationComponent,
    ZoneEnvelopeComponent,
)
from epinterface.sbem.components.materials import ConstructionMaterialComponent
from epinterface.sbem.components.operations import ZoneOperationsComponent
from epinterface.sbem.components.schedules import (
    DayComponent,
    WeekComponent,
    YearComponent,
    YearScheduleCategory,
)
from epinterface.sbem.components.space_use import (
    EquipmentComponent,
    LightingComponent,
    OccupancyComponent,
    ThermostatComponent,
    WaterUseComponent,
    ZoneSpaceUseComponent,
)
from epinterface.sbem.components.systems import (
    ConditioningSystemsComponent,
    DCVMethod,
    DHWComponent,
    DHWFuelType,
    EconomizerMethod,
    FuelType,
    HRVMethod,
    ThermalSystemComponent,
    VentilationComponent,
    VentilationProvider,
    ZoneHVACComponent,
)
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.weather import WeatherUrl

xps_board = ConstructionMaterialComponent(
    Name="XPSBoard",
    Conductivity=0.037,
    Density=40,
    SpecificHeat=1200,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Insulation",
)

concrete_mc_light = ConstructionMaterialComponent(
    Name="ConcreteMC_Light",
    Conductivity=1.65,
    Density=2100,
    SpecificHeat=1040,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Concrete",
)

concrete_rc_dense = ConstructionMaterialComponent(
    Name="ConcreteRC_Dense",
    Conductivity=1.75,
    Density=2400,
    SpecificHeat=840,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Concrete",
)

gypsum_board = ConstructionMaterialComponent(
    Name="GypsumBoard",
    Conductivity=0.16,
    Density=950,
    SpecificHeat=840,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Finishes",
)

gypsum_plaster = ConstructionMaterialComponent(
    Name="GypsumPlaster",
    Conductivity=0.42,
    Density=900,
    SpecificHeat=840,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Finishes",
)

softwood_general = ConstructionMaterialComponent(
    Name="SoftwoodGeneral",
    Conductivity=0.13,
    Density=496,
    SpecificHeat=1630,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Timber",
)

clay_brick = ConstructionMaterialComponent(
    Name="ClayBrick",
    Conductivity=0.41,
    Density=1000,
    SpecificHeat=920,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Masonry",
)

concrete_block_h = ConstructionMaterialComponent(
    Name="ConcreteBlockH",
    Conductivity=1.25,
    Density=880,
    SpecificHeat=840,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Concrete",
)

fiberglass_batts = ConstructionMaterialComponent(
    Name="FiberglassBatt",
    Conductivity=0.043,
    Density=12,
    SpecificHeat=840,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Insulation",
)

cement_mortar = ConstructionMaterialComponent(
    Name="CementMortar",
    Conductivity=0.8,
    Density=1900,
    SpecificHeat=840,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Other",
)

ceramic_tile = ConstructionMaterialComponent(
    Name="CeramicTile",
    Conductivity=0.8,
    Density=2243,
    SpecificHeat=840,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Finishes",
)

urethane_carpet = ConstructionMaterialComponent(
    Name="UrethaneCarpet",
    Conductivity=0.045,
    Density=110,
    SpecificHeat=840,
    ThermalAbsorptance=0.9,
    SolarAbsorptance=0.6,
    VisibleAbsorptance=0.6,
    TemperatureCoefficientThermalConductivity=0.0,
    Roughness="MediumRough",
    Type="Finishes",
)


class ParametericYear(BaseModel):
    """A model for a year schedule that is parameterized by the base, and the interpolation factors."""

    Base: float = Field(default=..., ge=0, le=1)
    """Overnight Baseload"""

    AMInterp: float = Field(default=..., ge=0, le=1)
    """AM Hours: 6pm, 7pm, 8pm, Base + AMInterp * (1-Base)"""

    LunchInterp: float = Field(default=..., ge=0, le=1)
    """Lunch Hours: 12pm, 1pm Base + LunchInterp * (1-Base)"""

    PMInterp: float = Field(default=..., ge=0, le=1)
    """PM Hours: 6pm,7pm,8pm Base + PMInterp * (1-Base)"""

    WeekendPeakInterp: float = Field(default=..., ge=0, le=1)
    """Weekend Peak = Base + WeekendPeakInterp * (1-Base)"""

    SummerPeakInterp: float = Field(default=..., ge=0, le=1)
    """Summer Peak = Base + SummerPeakInterp * (1-Base)"""

    def to_schedule(self, name: str, category: YearScheduleCategory):
        """Convert the parameters to a schedule."""
        peak = 1
        am_inter = self.Base + self.AMInterp * (peak - self.Base)
        lunch_inter = self.Base + self.LunchInterp * (peak - self.Base)
        pm_inter = self.Base + self.PMInterp * (peak - self.Base)

        we_peak = self.Base + self.WeekendPeakInterp * (peak - self.Base)
        we_am_inter_val = self.Base + self.AMInterp * (we_peak - self.Base)
        we_lunch_inter_val = self.Base + self.LunchInterp * (we_peak - self.Base)
        we_pm_inter_val = self.Base + self.PMInterp * (we_peak - self.Base)

        summer_peak = self.Base + self.SummerPeakInterp * (peak - self.Base)
        summer_am_inter = self.Base + self.AMInterp * (summer_peak - self.Base)
        summer_lunch_inter = self.Base + self.LunchInterp * (summer_peak - self.Base)
        summer_pm_inter = self.Base + self.PMInterp * (summer_peak - self.Base)

        summer_we_peak = self.Base + self.SummerPeakInterp * (we_peak - self.Base)
        summer_we_am_inter = self.Base + self.AMInterp * (summer_we_peak - self.Base)
        summer_we_lunch_inter = self.Base + self.LunchInterp * (
            summer_we_peak - self.Base
        )
        summer_we_pm_inter = self.Base + self.PMInterp * (summer_we_peak - self.Base)

        weekday = DayComponent(
            Name=f"{name}_ParametericWeekday",
            Type="Fraction",
            Hour_00=self.Base,
            Hour_01=self.Base,
            Hour_02=self.Base,
            Hour_03=self.Base,
            Hour_04=self.Base,
            Hour_05=self.Base,
            Hour_06=am_inter,
            Hour_07=am_inter,
            Hour_08=am_inter,
            Hour_09=peak,
            Hour_10=peak,
            Hour_11=peak,
            Hour_12=lunch_inter,
            Hour_13=lunch_inter,
            Hour_14=peak,
            Hour_15=peak,
            Hour_16=peak,
            Hour_17=peak,
            Hour_18=pm_inter,
            Hour_19=pm_inter,
            Hour_20=pm_inter,
            Hour_21=self.Base,
            Hour_22=self.Base,
            Hour_23=self.Base,
        )

        weekend = DayComponent(
            Name=f"{name}_ParametericWeekend",
            Type="Fraction",
            Hour_00=self.Base,
            Hour_01=self.Base,
            Hour_02=self.Base,
            Hour_03=self.Base,
            Hour_04=self.Base,
            Hour_05=self.Base,
            Hour_06=we_am_inter_val,
            Hour_07=we_am_inter_val,
            Hour_08=we_am_inter_val,
            Hour_09=we_peak,
            Hour_10=we_peak,
            Hour_11=we_peak,
            Hour_12=we_lunch_inter_val,
            Hour_13=we_lunch_inter_val,
            Hour_14=we_peak,
            Hour_15=we_peak,
            Hour_16=we_peak,
            Hour_17=we_peak,
            Hour_18=we_pm_inter_val,
            Hour_19=we_pm_inter_val,
            Hour_20=we_pm_inter_val,
            Hour_21=self.Base,
            Hour_22=self.Base,
            Hour_23=self.Base,
        )

        summer_weekday = DayComponent(
            Name=f"{name}_ParametericSummerWeekday",
            Type="Fraction",
            Hour_00=self.Base,
            Hour_01=self.Base,
            Hour_02=self.Base,
            Hour_03=self.Base,
            Hour_04=self.Base,
            Hour_05=self.Base,
            Hour_06=summer_am_inter,
            Hour_07=summer_am_inter,
            Hour_08=summer_am_inter,
            Hour_09=summer_peak,
            Hour_10=summer_peak,
            Hour_11=summer_peak,
            Hour_12=summer_lunch_inter,
            Hour_13=summer_lunch_inter,
            Hour_14=summer_peak,
            Hour_15=summer_peak,
            Hour_16=summer_peak,
            Hour_17=summer_peak,
            Hour_18=summer_pm_inter,
            Hour_19=summer_pm_inter,
            Hour_20=summer_pm_inter,
            Hour_21=self.Base,
            Hour_22=self.Base,
            Hour_23=self.Base,
        )

        summer_weekend = DayComponent(
            Name=f"{name}_ParametericSummerWeekend",
            Type="Fraction",
            Hour_00=self.Base,
            Hour_01=self.Base,
            Hour_02=self.Base,
            Hour_03=self.Base,
            Hour_04=self.Base,
            Hour_05=self.Base,
            Hour_06=summer_we_am_inter,
            Hour_07=summer_we_am_inter,
            Hour_08=summer_we_am_inter,
            Hour_09=summer_we_peak,
            Hour_10=summer_we_peak,
            Hour_11=summer_we_peak,
            Hour_12=summer_we_lunch_inter,
            Hour_13=summer_we_lunch_inter,
            Hour_14=summer_we_peak,
            Hour_15=summer_we_peak,
            Hour_16=summer_we_peak,
            Hour_17=summer_we_peak,
            Hour_18=summer_we_pm_inter,
            Hour_19=summer_we_pm_inter,
            Hour_20=summer_we_pm_inter,
            Hour_21=self.Base,
            Hour_22=self.Base,
            Hour_23=self.Base,
        )

        regular_week = WeekComponent(
            Name=f"{name}_ParametericRegularWeek",
            Monday=weekday,
            Tuesday=weekday,
            Wednesday=weekday,
            Thursday=weekday,
            Friday=weekday,
            Saturday=weekend,
            Sunday=weekend,
        )

        summer_week = WeekComponent(
            Name=f"{name}_ParametericSummerWeek",
            Monday=summer_weekday,
            Tuesday=summer_weekday,
            Wednesday=summer_weekday,
            Thursday=summer_weekday,
            Friday=summer_weekday,
            Saturday=summer_weekend,
            Sunday=summer_weekend,
        )

        year = YearComponent(
            Name=f"{name}_ParametericYear",
            Type=category,
            January=regular_week,
            February=regular_week,
            March=regular_week,
            April=regular_week,
            May=regular_week,
            June=summer_week,
            July=summer_week,
            August=summer_week,
            September=regular_week,
            October=regular_week,
            November=regular_week,
            December=regular_week,
        )

        return year


class ParametricSetpoints(BaseModel):
    """A model for a setpoint schedule that is parameterized by the base, and the setbacks."""

    HeatingSetpoint: float = Field(ge=0, le=22)
    DeadBand: float = Field(ge=0, le=10)
    HeatingSetback: float = Field(ge=0, le=10)
    CoolingSetback: float = Field(ge=0, le=10)
    NightSetback: float = Field(ge=0, le=1)
    WeekendSetback: float = Field(ge=0, le=1)
    SummerSetback: float = Field(ge=0, le=1)

    def to_schedules(self):
        """Convert the setpoint parameters to a set of schedules."""
        hsp = self.HeatingSetpoint
        csp = hsp + self.DeadBand
        hsp_setback = hsp - self.HeatingSetback
        csp_setback = csp + self.CoolingSetback

        hsp_night = hsp - self.NightSetback * (hsp - hsp_setback)
        csp_night = csp + self.NightSetback * (csp_setback - csp)

        hsp_weekend_base = hsp - self.WeekendSetback * (hsp - hsp_setback)
        csp_weekend_base = csp + self.WeekendSetback * (csp_setback - csp)

        hsp_summer_base = hsp - self.SummerSetback * (hsp - hsp_setback)
        csp_summer_base = csp + self.SummerSetback * (csp_setback - csp)

        hsp_summer_weekend_base = hsp_summer_base - self.WeekendSetback * (
            hsp_summer_base - hsp_setback
        )
        csp_summer_weekend_base = csp_summer_base + self.WeekendSetback * (
            csp_setback - csp_summer_base
        )

        hsp_standard_day = DayComponent(
            Name="HSP_Standard_Day",
            Type="Temperature",
            Hour_00=hsp_night,
            Hour_01=hsp_night,
            Hour_02=hsp_night,
            Hour_03=hsp_night,
            Hour_04=hsp_night,
            Hour_05=hsp_night,
            Hour_06=hsp_night,
            Hour_07=hsp,
            Hour_08=hsp,
            Hour_09=hsp,
            Hour_10=hsp,
            Hour_11=hsp,
            Hour_12=hsp,
            Hour_13=hsp,
            Hour_14=hsp,
            Hour_15=hsp,
            Hour_16=hsp,
            Hour_17=hsp,
            Hour_18=hsp,
            Hour_19=hsp_night,
            Hour_20=hsp_night,
            Hour_21=hsp_night,
            Hour_22=hsp_night,
            Hour_23=hsp_night,
        )

        hsp_weekend_day = DayComponent(
            Name="HSP_Weekend_Day",
            Type="Temperature",
            Hour_00=hsp_night,
            Hour_01=hsp_night,
            Hour_02=hsp_night,
            Hour_03=hsp_night,
            Hour_04=hsp_night,
            Hour_05=hsp_night,
            Hour_06=hsp_night,
            Hour_07=hsp_weekend_base,
            Hour_08=hsp_weekend_base,
            Hour_09=hsp_weekend_base,
            Hour_10=hsp_weekend_base,
            Hour_11=hsp_weekend_base,
            Hour_12=hsp_weekend_base,
            Hour_13=hsp_weekend_base,
            Hour_14=hsp_weekend_base,
            Hour_15=hsp_weekend_base,
            Hour_16=hsp_weekend_base,
            Hour_17=hsp_weekend_base,
            Hour_18=hsp_weekend_base,
            Hour_19=hsp_night,
            Hour_20=hsp_night,
            Hour_21=hsp_night,
            Hour_22=hsp_night,
            Hour_23=hsp_night,
        )

        hsp_summer_day = DayComponent(
            Name="HSP_Summer_Day",
            Type="Temperature",
            Hour_00=hsp_night,
            Hour_01=hsp_night,
            Hour_02=hsp_night,
            Hour_03=hsp_night,
            Hour_04=hsp_night,
            Hour_05=hsp_night,
            Hour_06=hsp_night,
            Hour_07=hsp_summer_base,
            Hour_08=hsp_summer_base,
            Hour_09=hsp_summer_base,
            Hour_10=hsp_summer_base,
            Hour_11=hsp_summer_base,
            Hour_12=hsp_summer_base,
            Hour_13=hsp_summer_base,
            Hour_14=hsp_summer_base,
            Hour_15=hsp_summer_base,
            Hour_16=hsp_summer_base,
            Hour_17=hsp_summer_base,
            Hour_18=hsp_summer_base,
            Hour_19=hsp_night,
            Hour_20=hsp_night,
            Hour_21=hsp_night,
            Hour_22=hsp_night,
            Hour_23=hsp_night,
        )

        hsp_summer_weekend_day = DayComponent(
            Name="HSP_Summer_Weekend_Day",
            Type="Temperature",
            Hour_00=hsp_night,
            Hour_01=hsp_night,
            Hour_02=hsp_night,
            Hour_03=hsp_night,
            Hour_04=hsp_night,
            Hour_05=hsp_night,
            Hour_06=hsp_night,
            Hour_07=hsp_summer_weekend_base,
            Hour_08=hsp_summer_weekend_base,
            Hour_09=hsp_summer_weekend_base,
            Hour_10=hsp_summer_weekend_base,
            Hour_11=hsp_summer_weekend_base,
            Hour_12=hsp_summer_weekend_base,
            Hour_13=hsp_summer_weekend_base,
            Hour_14=hsp_summer_weekend_base,
            Hour_15=hsp_summer_weekend_base,
            Hour_16=hsp_summer_weekend_base,
            Hour_17=hsp_summer_weekend_base,
            Hour_18=hsp_summer_weekend_base,
            Hour_19=hsp_night,
            Hour_20=hsp_night,
            Hour_21=hsp_night,
            Hour_22=hsp_night,
            Hour_23=hsp_night,
        )

        csp_standard_day = DayComponent(
            Name="CSP_Standard_Day",
            Type="Temperature",
            Hour_00=csp_night,
            Hour_01=csp_night,
            Hour_02=csp_night,
            Hour_03=csp_night,
            Hour_04=csp_night,
            Hour_05=csp_night,
            Hour_06=csp_night,
            Hour_07=csp,
            Hour_08=csp,
            Hour_09=csp,
            Hour_10=csp,
            Hour_11=csp,
            Hour_12=csp,
            Hour_13=csp,
            Hour_14=csp,
            Hour_15=csp,
            Hour_16=csp,
            Hour_17=csp,
            Hour_18=csp,
            Hour_19=csp_night,
            Hour_20=csp_night,
            Hour_21=csp_night,
            Hour_22=csp_night,
            Hour_23=csp_night,
        )

        csp_weekend_day = DayComponent(
            Name="CSP_Weekend_Day",
            Type="Temperature",
            Hour_00=csp_night,
            Hour_01=csp_night,
            Hour_02=csp_night,
            Hour_03=csp_night,
            Hour_04=csp_night,
            Hour_05=csp_night,
            Hour_06=csp_night,
            Hour_07=csp_weekend_base,
            Hour_08=csp_weekend_base,
            Hour_09=csp_weekend_base,
            Hour_10=csp_weekend_base,
            Hour_11=csp_weekend_base,
            Hour_12=csp_weekend_base,
            Hour_13=csp_weekend_base,
            Hour_14=csp_weekend_base,
            Hour_15=csp_weekend_base,
            Hour_16=csp_weekend_base,
            Hour_17=csp_weekend_base,
            Hour_18=csp_weekend_base,
            Hour_19=csp_night,
            Hour_20=csp_night,
            Hour_21=csp_night,
            Hour_22=csp_night,
            Hour_23=csp_night,
        )

        csp_summer_day = DayComponent(
            Name="CSP_Summer_Day",
            Type="Temperature",
            Hour_00=csp_night,
            Hour_01=csp_night,
            Hour_02=csp_night,
            Hour_03=csp_night,
            Hour_04=csp_night,
            Hour_05=csp_night,
            Hour_06=csp_night,
            Hour_07=csp_summer_base,
            Hour_08=csp_summer_base,
            Hour_09=csp_summer_base,
            Hour_10=csp_summer_base,
            Hour_11=csp_summer_base,
            Hour_12=csp_summer_base,
            Hour_13=csp_summer_base,
            Hour_14=csp_summer_base,
            Hour_15=csp_summer_base,
            Hour_16=csp_summer_base,
            Hour_17=csp_summer_base,
            Hour_18=csp_summer_base,
            Hour_19=csp_night,
            Hour_20=csp_night,
            Hour_21=csp_night,
            Hour_22=csp_night,
            Hour_23=csp_night,
        )

        csp_summer_weekend_day = DayComponent(
            Name="CSP_Summer_Weekend_Day",
            Type="Temperature",
            Hour_00=csp_night,
            Hour_01=csp_night,
            Hour_02=csp_night,
            Hour_03=csp_night,
            Hour_04=csp_night,
            Hour_05=csp_night,
            Hour_06=csp_night,
            Hour_07=csp_summer_weekend_base,
            Hour_08=csp_summer_weekend_base,
            Hour_09=csp_summer_weekend_base,
            Hour_10=csp_summer_weekend_base,
            Hour_11=csp_summer_weekend_base,
            Hour_12=csp_summer_weekend_base,
            Hour_13=csp_summer_weekend_base,
            Hour_14=csp_summer_weekend_base,
            Hour_15=csp_summer_weekend_base,
            Hour_16=csp_summer_weekend_base,
            Hour_17=csp_summer_weekend_base,
            Hour_18=csp_summer_weekend_base,
            Hour_19=csp_night,
            Hour_20=csp_night,
            Hour_21=csp_night,
            Hour_22=csp_night,
            Hour_23=csp_night,
        )

        hsp_standard_week = WeekComponent(
            Name="HSP_Standard_Week",
            Monday=hsp_standard_day,
            Tuesday=hsp_standard_day,
            Wednesday=hsp_standard_day,
            Thursday=hsp_standard_day,
            Friday=hsp_standard_day,
            Saturday=hsp_weekend_day,
            Sunday=hsp_weekend_day,
        )

        csp_standard_week = WeekComponent(
            Name="CSP_Standard_Week",
            Monday=csp_standard_day,
            Tuesday=csp_standard_day,
            Wednesday=csp_standard_day,
            Thursday=csp_standard_day,
            Friday=csp_standard_day,
            Saturday=csp_weekend_day,
            Sunday=csp_weekend_day,
        )

        hsp_summer_week = WeekComponent(
            Name="HSP_Summer_Week",
            Monday=hsp_summer_day,
            Tuesday=hsp_summer_day,
            Wednesday=hsp_summer_day,
            Thursday=hsp_summer_day,
            Friday=hsp_summer_day,
            Saturday=hsp_summer_weekend_day,
            Sunday=hsp_summer_weekend_day,
        )

        csp_summer_week = WeekComponent(
            Name="CSP_Summer_Week",
            Monday=csp_summer_day,
            Tuesday=csp_summer_day,
            Wednesday=csp_summer_day,
            Thursday=csp_summer_day,
            Friday=csp_summer_day,
            Saturday=csp_summer_weekend_day,
            Sunday=csp_summer_weekend_day,
        )

        hsp_year = YearComponent(
            Name="HSP_Year",
            Type="Setpoint",
            January=hsp_standard_week,
            February=hsp_standard_week,
            March=hsp_standard_week,
            April=hsp_standard_week,
            May=hsp_standard_week,
            June=hsp_summer_week,
            July=hsp_summer_week,
            August=hsp_summer_week,
            September=hsp_standard_week,
            October=hsp_standard_week,
            November=hsp_standard_week,
            December=hsp_standard_week,
        )

        csp_year = YearComponent(
            Name="CSP_Year",
            Type="Setpoint",
            January=csp_standard_week,
            February=csp_standard_week,
            March=csp_standard_week,
            April=csp_standard_week,
            May=csp_standard_week,
            June=csp_summer_week,
            July=csp_summer_week,
            August=csp_summer_week,
            September=csp_standard_week,
            October=csp_standard_week,
            November=csp_standard_week,
            December=csp_standard_week,
        )

        return hsp_year, csp_year


class FlatModel(BaseModel):
    """A flattened set of parameters for invoking building energy models more conveniently."""

    # EquipmentSummerWeekdayNight: float = Field(ge=0, le=1)
    # EquipmentSummerWeekdayEarlyMorning: float = Field(ge=0, le=1)
    # EquipmentSummerWeekdayMorning: float = Field(ge=0, le=1)
    # EquipmentSummerWeekdayLunch: float = Field(ge=0, le=1)
    # EquipmentSummerWeekdayAfternoon: float = Field(ge=0, le=1)
    # EquipmentSummerWeekdayEvening: float = Field(ge=0, le=1)

    # EquipmentSummerWeekendNight: float = Field(ge=0, le=1)
    # EquipmentSummerWeekendEarlyMorning: float = Field(ge=0, le=1)
    # EquipmentSummerWeekendMorning: float = Field(ge=0, le=1)
    # EquipmentSummerWeekendLunch: float = Field(ge=0, le=1)
    # EquipmentSummerWeekendAfternoon: float = Field(ge=0, le=1)
    # EquipmentSummerWeekendEvening: float = Field(ge=0, le=1)

    # EquipmentRegularWeekdayNight: float = Field(ge=0, le=1)
    # EquipmentRegularWeekdayEarlyMorning: float = Field(ge=0, le=1)
    # EquipmentRegularWeekdayMorning: float = Field(ge=0, le=1)
    # EquipmentRegularWeekdayLunch: float = Field(ge=0, le=1)
    # EquipmentRegularWeekdayAfternoon: float = Field(ge=0, le=1)
    # EquipmentRegularWeekdayEvening: float = Field(ge=0, le=1)

    # EquipmentRegularWeekendNight: float = Field(ge=0, le=1)
    # EquipmentRegularWeekendEarlyMorning: float = Field(ge=0, le=1)
    # EquipmentRegularWeekendMorning: float = Field(ge=0, le=1)
    # EquipmentRegularWeekendLunch: float = Field(ge=0, le=1)
    # EquipmentRegularWeekendAfternoon: float = Field(ge=0, le=1)
    # EquipmentRegularWeekendEvening: float = Field(ge=0, le=1)

    # LightingSummerWeekdayNight: float = Field(ge=0, le=1)
    # LightingSummerWeekdayEarlyMorning: float = Field(ge=0, le=1)
    # LightingSummerWeekdayMorning: float = Field(ge=0, le=1)
    # LightingSummerWeekdayLunch: float = Field(ge=0, le=1)
    # LightingSummerWeekdayAfternoon: float = Field(ge=0, le=1)
    # LightingSummerWeekdayEvening: float = Field(ge=0, le=1)

    # LightingSummerWeekendNight: float = Field(ge=0, le=1)
    # LightingSummerWeekendEarlyMorning: float = Field(ge=0, le=1)
    # LightingSummerWeekendMorning: float = Field(ge=0, le=1)
    # LightingSummerWeekendLunch: float = Field(ge=0, le=1)
    # LightingSummerWeekendAfternoon: float = Field(ge=0, le=1)
    # LightingSummerWeekendEvening: float = Field(ge=0, le=1)

    # LightingRegularWeekdayNight: float = Field(ge=0, le=1)
    # LightingRegularWeekdayEarlyMorning: float = Field(ge=0, le=1)
    # LightingRegularWeekdayMorning: float = Field(ge=0, le=1)
    # LightingRegularWeekdayLunch: float = Field(ge=0, le=1)
    # LightingRegularWeekdayAfternoon: float = Field(ge=0, le=1)
    # LightingRegularWeekdayEvening: float = Field(ge=0, le=1)

    # LightingRegularWeekendNight: float = Field(ge=0, le=1)
    # LightingRegularWeekendEarlyMorning: float = Field(ge=0, le=1)
    # LightingRegularWeekendMorning: float = Field(ge=0, le=1)
    # LightingRegularWeekendLunch: float = Field(ge=0, le=1)
    # LightingRegularWeekendAfternoon: float = Field(ge=0, le=1)
    # LightingRegularWeekendEvening: float = Field(ge=0, le=1)

    # OccupancySummerWeekdayNight: float = Field(ge=0, le=1)
    # OccupancySummerWeekdayEarlyMorning: float = Field(ge=0, le=1)
    # OccupancySummerWeekdayMorning: float = Field(ge=0, le=1)
    # OccupancySummerWeekdayLunch: float = Field(ge=0, le=1)
    # OccupancySummerWeekdayAfternoon: float = Field(ge=0, le=1)
    # OccupancySummerWeekdayEvening: float = Field(ge=0, le=1)

    # OccupancySummerWeekendNight: float = Field(ge=0, le=1)
    # OccupancySummerWeekendEarlyMorning: float = Field(ge=0, le=1)
    # OccupancySummerWeekendMorning: float = Field(ge=0, le=1)
    # OccupancySummerWeekendLunch: float = Field(ge=0, le=1)
    # OccupancySummerWeekendAfternoon: float = Field(ge=0, le=1)
    # OccupancySummerWeekendEvening: float = Field(ge=0, le=1)

    # OccupancyRegularWeekdayNight: float = Field(ge=0, le=1)
    # OccupancyRegularWeekdayEarlyMorning: float = Field(ge=0, le=1)
    # OccupancyRegularWeekdayMorning: float = Field(ge=0, le=1)
    # OccupancyRegularWeekdayLunch: float = Field(ge=0, le=1)
    # OccupancyRegularWeekdayAfternoon: float = Field(ge=0, le=1)
    # OccupancyRegularWeekdayEvening: float = Field(ge=0, le=1)

    # OccupancyRegularWeekendNight: float = Field(ge=0, le=1)
    # OccupancyRegularWeekendEarlyMorning: float = Field(ge=0, le=1)
    # OccupancyRegularWeekendMorning: float = Field(ge=0, le=1)
    # OccupancyRegularWeekendLunch: float = Field(ge=0, le=1)
    # OccupancyRegularWeekendAfternoon: float = Field(ge=0, le=1)
    # OccupancyRegularWeekendEvening: float = Field(ge=0, le=1)

    EquipmentBase: float = Field(ge=0, le=1)
    EquipmentAMInterp: float = Field(ge=0, le=1)
    EquipmentLunchInterp: float = Field(ge=0, le=1)
    EquipmentPMInterp: float = Field(ge=0, le=1)
    EquipmentWeekendPeakInterp: float = Field(ge=0, le=1)
    EquipmentSummerPeakInterp: float = Field(ge=0, le=1)

    LightingBase: float = Field(ge=0, le=1)
    LightingAMInterp: float = Field(ge=0, le=1)
    LightingLunchInterp: float = Field(ge=0, le=1)
    LightingPMInterp: float = Field(ge=0, le=1)
    LightingWeekendPeakInterp: float = Field(ge=0, le=1)
    LightingSummerPeakInterp: float = Field(ge=0, le=1)

    OccupancyBase: float = Field(ge=0, le=1)
    OccupancyAMInterp: float = Field(ge=0, le=1)
    OccupancyLunchInterp: float = Field(ge=0, le=1)
    OccupancyPMInterp: float = Field(ge=0, le=1)
    OccupancyWeekendPeakInterp: float = Field(ge=0, le=1)
    OccupancySummerPeakInterp: float = Field(ge=0, le=1)

    # HSPRegularWeekdayWorkhours: float = Field(ge=0, le=23)
    # HSPRegularWeekdayNight: float = Field(ge=0, le=23)
    # HSPSummerWeekdayWorkhours: float = Field(ge=0, le=23)
    # HSPSummerWeekdayNight: float = Field(ge=0, le=23)
    # HSPWeekendWorkhours: float = Field(ge=0, le=23)
    # HSPWeekendNight: float = Field(ge=0, le=23)

    # CSPRegularWeekdayWorkhours: float = Field(ge=20, le=30)
    # CSPRegularWeekdayNight: float = Field(ge=20, le=30)
    # CSPSummerWeekdayWorkhours: float = Field(ge=20, le=30)
    # CSPSummerWeekdayNight: float = Field(ge=20, le=30)
    # CSPWeekendWorkhours: float = Field(ge=20, le=30)
    # CSPWeekendNight: float = Field(ge=20, le=30)

    HeatingSetpointBase: float = Field(ge=0, le=23)
    SetpointDeadband: float = Field(ge=0, le=10)
    HeatingSetpointSetback: float = Field(ge=0, le=10)
    CoolingSetpointSetback: float = Field(ge=0, le=10)
    NightSetback: float = Field(ge=0, le=1)
    WeekendSetback: float = Field(ge=0, le=1)
    SummerSetback: float = Field(ge=0, le=1)

    HeatingFuel: FuelType
    CoolingFuel: FuelType
    HeatingSystemCOP: float
    CoolingSystemCOP: float
    HeatingDistributionCOP: float
    CoolingDistributionCOP: float

    EquipmentPowerDensity: float = Field(ge=0, le=200)
    LightingPowerDensity: float = Field(ge=0, le=100)
    OccupantDensity: float = Field(ge=0, le=50)

    VentFlowRatePerPerson: float
    VentFlowRatePerArea: float
    VentProvider: VentilationProvider
    VentHRV: HRVMethod
    VentEconomizer: EconomizerMethod
    VentDCV: DCVMethod

    DHWFlowRatePerPerson: float
    DHWFuel: DHWFuelType
    DHWSystemCOP: float
    DHWDistributionCOP: float

    InfiltrationACH: float

    WindowUValue: float
    WindowSHGF: float
    WindowTVis: float

    FacadeRValue: float
    RoofRValue: float
    SlabRValue: float

    WWR: float
    F2FHeight: float
    NFloors: int
    Width: float
    Depth: float
    Rotation: float

    EPWURI: WeatherUrl | Path

    def to_zone(self) -> ZoneComponent:
        """Convert the flat model to a full zone."""
        # occ_regular_workday = DayComponent(
        #     Name="Occupancy_Regular_Workday",
        #     Type="Fraction",
        #     Hour_00=self.OccupancyRegularWeekdayNight,
        #     Hour_01=self.OccupancyRegularWeekdayNight,
        #     Hour_02=self.OccupancyRegularWeekdayNight,
        #     Hour_03=self.OccupancyRegularWeekdayNight,
        #     Hour_04=self.OccupancyRegularWeekdayNight,
        #     Hour_05=self.OccupancyRegularWeekdayNight,
        #     Hour_06=self.OccupancyRegularWeekdayEarlyMorning,
        #     Hour_07=self.OccupancyRegularWeekdayEarlyMorning,
        #     Hour_08=self.OccupancyRegularWeekdayEarlyMorning,
        #     Hour_09=self.OccupancyRegularWeekdayMorning,
        #     Hour_10=self.OccupancyRegularWeekdayMorning,
        #     Hour_11=self.OccupancyRegularWeekdayMorning,
        #     Hour_12=self.OccupancyRegularWeekdayLunch,
        #     Hour_13=self.OccupancyRegularWeekdayLunch,
        #     Hour_14=self.OccupancyRegularWeekdayAfternoon,
        #     Hour_15=self.OccupancyRegularWeekdayAfternoon,
        #     Hour_16=self.OccupancyRegularWeekdayAfternoon,
        #     Hour_17=self.OccupancyRegularWeekdayAfternoon,
        #     Hour_18=self.OccupancyRegularWeekdayEvening,
        #     Hour_19=self.OccupancyRegularWeekdayEvening,
        #     Hour_20=self.OccupancyRegularWeekdayEvening,
        #     Hour_21=self.OccupancyRegularWeekdayNight,
        #     Hour_22=self.OccupancyRegularWeekdayNight,
        #     Hour_23=self.OccupancyRegularWeekdayNight,
        # )

        # occ_regular_weekend = DayComponent(
        #     Name="Occupancy_Regular_Weekend",
        #     Type="Fraction",
        #     Hour_00=self.OccupancyRegularWeekendNight,
        #     Hour_01=self.OccupancyRegularWeekendNight,
        #     Hour_02=self.OccupancyRegularWeekendNight,
        #     Hour_03=self.OccupancyRegularWeekendNight,
        #     Hour_04=self.OccupancyRegularWeekendNight,
        #     Hour_05=self.OccupancyRegularWeekendNight,
        #     Hour_06=self.OccupancyRegularWeekendEarlyMorning,
        #     Hour_07=self.OccupancyRegularWeekendEarlyMorning,
        #     Hour_08=self.OccupancyRegularWeekendEarlyMorning,
        #     Hour_09=self.OccupancyRegularWeekendMorning,
        #     Hour_10=self.OccupancyRegularWeekendMorning,
        #     Hour_11=self.OccupancyRegularWeekendMorning,
        #     Hour_12=self.OccupancyRegularWeekendLunch,
        #     Hour_13=self.OccupancyRegularWeekendLunch,
        #     Hour_14=self.OccupancyRegularWeekendAfternoon,
        #     Hour_15=self.OccupancyRegularWeekendAfternoon,
        #     Hour_16=self.OccupancyRegularWeekendAfternoon,
        #     Hour_17=self.OccupancyRegularWeekendAfternoon,
        #     Hour_18=self.OccupancyRegularWeekendEvening,
        #     Hour_19=self.OccupancyRegularWeekendEvening,
        #     Hour_20=self.OccupancyRegularWeekendEvening,
        #     Hour_21=self.OccupancyRegularWeekendNight,
        #     Hour_22=self.OccupancyRegularWeekendNight,
        #     Hour_23=self.OccupancyRegularWeekendNight,
        # )

        # occ_summer_workday = DayComponent(
        #     Name="Occupancy_Summer_Workday",
        #     Type="Fraction",
        #     Hour_00=self.OccupancySummerWeekdayNight,
        #     Hour_01=self.OccupancySummerWeekdayNight,
        #     Hour_02=self.OccupancySummerWeekdayNight,
        #     Hour_03=self.OccupancySummerWeekdayNight,
        #     Hour_04=self.OccupancySummerWeekdayNight,
        #     Hour_05=self.OccupancySummerWeekdayNight,
        #     Hour_06=self.OccupancySummerWeekdayEarlyMorning,
        #     Hour_07=self.OccupancySummerWeekdayEarlyMorning,
        #     Hour_08=self.OccupancySummerWeekdayEarlyMorning,
        #     Hour_09=self.OccupancySummerWeekdayMorning,
        #     Hour_10=self.OccupancySummerWeekdayMorning,
        #     Hour_11=self.OccupancySummerWeekdayMorning,
        #     Hour_12=self.OccupancySummerWeekdayLunch,
        #     Hour_13=self.OccupancySummerWeekdayLunch,
        #     Hour_14=self.OccupancySummerWeekdayAfternoon,
        #     Hour_15=self.OccupancySummerWeekdayAfternoon,
        #     Hour_16=self.OccupancySummerWeekdayAfternoon,
        #     Hour_17=self.OccupancySummerWeekdayAfternoon,
        #     Hour_18=self.OccupancySummerWeekdayEvening,
        #     Hour_19=self.OccupancySummerWeekdayEvening,
        #     Hour_20=self.OccupancySummerWeekdayEvening,
        #     Hour_21=self.OccupancySummerWeekdayNight,
        #     Hour_22=self.OccupancySummerWeekdayNight,
        #     Hour_23=self.OccupancySummerWeekdayNight,
        # )

        # occ_summer_weekend = DayComponent(
        #     Name="Occupancy_Summer_Weekend",
        #     Type="Fraction",
        #     Hour_00=self.OccupancySummerWeekendNight,
        #     Hour_01=self.OccupancySummerWeekendNight,
        #     Hour_02=self.OccupancySummerWeekendNight,
        #     Hour_03=self.OccupancySummerWeekendNight,
        #     Hour_04=self.OccupancySummerWeekendNight,
        #     Hour_05=self.OccupancySummerWeekendNight,
        #     Hour_06=self.OccupancySummerWeekendEarlyMorning,
        #     Hour_07=self.OccupancySummerWeekendEarlyMorning,
        #     Hour_08=self.OccupancySummerWeekendEarlyMorning,
        #     Hour_09=self.OccupancySummerWeekendMorning,
        #     Hour_10=self.OccupancySummerWeekendMorning,
        #     Hour_11=self.OccupancySummerWeekendMorning,
        #     Hour_12=self.OccupancySummerWeekendLunch,
        #     Hour_13=self.OccupancySummerWeekendLunch,
        #     Hour_14=self.OccupancySummerWeekendAfternoon,
        #     Hour_15=self.OccupancySummerWeekendAfternoon,
        #     Hour_16=self.OccupancySummerWeekendAfternoon,
        #     Hour_17=self.OccupancySummerWeekendAfternoon,
        #     Hour_18=self.OccupancySummerWeekendEvening,
        #     Hour_19=self.OccupancySummerWeekendEvening,
        #     Hour_20=self.OccupancySummerWeekendEvening,
        #     Hour_21=self.OccupancySummerWeekendNight,
        #     Hour_22=self.OccupancySummerWeekendNight,
        #     Hour_23=self.OccupancySummerWeekendNight,
        # )

        # occ_regular_week = WeekComponent(
        #     Name="Occupancy_Regular_Week",
        #     Monday=occ_regular_workday,
        #     Tuesday=occ_regular_workday,
        #     Wednesday=occ_regular_workday,
        #     Thursday=occ_regular_workday,
        #     Friday=occ_regular_workday,
        #     Saturday=occ_regular_weekend,
        #     Sunday=occ_regular_weekend,
        # )

        # occ_summer_week = WeekComponent(
        #     Name="Occupancy_Summer_Week",
        #     Monday=occ_summer_workday,
        #     Tuesday=occ_summer_workday,
        #     Wednesday=occ_summer_workday,
        #     Thursday=occ_summer_workday,
        #     Friday=occ_summer_workday,
        #     Saturday=occ_summer_weekend,
        #     Sunday=occ_summer_weekend,
        # )

        # occ_year = YearComponent(
        #     Name="Occupancy_Schedule",
        #     Type="Occupancy",
        #     January=occ_regular_week,
        #     February=occ_regular_week,
        #     March=occ_regular_week,
        #     April=occ_regular_week,
        #     May=occ_regular_week,
        #     June=occ_summer_week,
        #     July=occ_summer_week,
        #     August=occ_summer_week,
        #     September=occ_regular_week,
        #     October=occ_regular_week,
        #     November=occ_regular_week,
        #     December=occ_regular_week,
        # )

        # lighting_regular_workday = DayComponent(
        #     Name="Lighting_Regular_Workday",
        #     Type="Fraction",
        #     Hour_00=self.LightingRegularWeekdayNight,
        #     Hour_01=self.LightingRegularWeekdayNight,
        #     Hour_02=self.LightingRegularWeekdayNight,
        #     Hour_03=self.LightingRegularWeekdayNight,
        #     Hour_04=self.LightingRegularWeekdayNight,
        #     Hour_05=self.LightingRegularWeekdayNight,
        #     Hour_06=self.LightingRegularWeekdayEarlyMorning,
        #     Hour_07=self.LightingRegularWeekdayEarlyMorning,
        #     Hour_08=self.LightingRegularWeekdayEarlyMorning,
        #     Hour_09=self.LightingRegularWeekdayMorning,
        #     Hour_10=self.LightingRegularWeekdayMorning,
        #     Hour_11=self.LightingRegularWeekdayMorning,
        #     Hour_12=self.LightingRegularWeekdayLunch,
        #     Hour_13=self.LightingRegularWeekdayLunch,
        #     Hour_14=self.LightingRegularWeekdayAfternoon,
        #     Hour_15=self.LightingRegularWeekdayAfternoon,
        #     Hour_16=self.LightingRegularWeekdayAfternoon,
        #     Hour_17=self.LightingRegularWeekdayAfternoon,
        #     Hour_18=self.LightingRegularWeekdayEvening,
        #     Hour_19=self.LightingRegularWeekdayEvening,
        #     Hour_20=self.LightingRegularWeekdayEvening,
        #     Hour_21=self.LightingRegularWeekdayNight,
        #     Hour_22=self.LightingRegularWeekdayNight,
        #     Hour_23=self.LightingRegularWeekdayNight,
        # )

        # lighting_regular_weekend = DayComponent(
        #     Name="Lighting_Regular_Weekend",
        #     Type="Fraction",
        #     Hour_00=self.LightingRegularWeekendNight,
        #     Hour_01=self.LightingRegularWeekendNight,
        #     Hour_02=self.LightingRegularWeekendNight,
        #     Hour_03=self.LightingRegularWeekendNight,
        #     Hour_04=self.LightingRegularWeekendNight,
        #     Hour_05=self.LightingRegularWeekendNight,
        #     Hour_06=self.LightingRegularWeekendEarlyMorning,
        #     Hour_07=self.LightingRegularWeekendEarlyMorning,
        #     Hour_08=self.LightingRegularWeekendEarlyMorning,
        #     Hour_09=self.LightingRegularWeekendMorning,
        #     Hour_10=self.LightingRegularWeekendMorning,
        #     Hour_11=self.LightingRegularWeekendMorning,
        #     Hour_12=self.LightingRegularWeekendLunch,
        #     Hour_13=self.LightingRegularWeekendLunch,
        #     Hour_14=self.LightingRegularWeekendAfternoon,
        #     Hour_15=self.LightingRegularWeekendAfternoon,
        #     Hour_16=self.LightingRegularWeekendAfternoon,
        #     Hour_17=self.LightingRegularWeekendAfternoon,
        #     Hour_18=self.LightingRegularWeekendEvening,
        #     Hour_19=self.LightingRegularWeekendEvening,
        #     Hour_20=self.LightingRegularWeekendEvening,
        #     Hour_21=self.LightingRegularWeekendNight,
        #     Hour_22=self.LightingRegularWeekendNight,
        #     Hour_23=self.LightingRegularWeekendNight,
        # )

        # lighting_summer_workday = DayComponent(
        #     Name="Lighting_Summer_Workday",
        #     Type="Fraction",
        #     Hour_00=self.LightingSummerWeekdayNight,
        #     Hour_01=self.LightingSummerWeekdayNight,
        #     Hour_02=self.LightingSummerWeekdayNight,
        #     Hour_03=self.LightingSummerWeekdayNight,
        #     Hour_04=self.LightingSummerWeekdayNight,
        #     Hour_05=self.LightingSummerWeekdayNight,
        #     Hour_06=self.LightingSummerWeekdayEarlyMorning,
        #     Hour_07=self.LightingSummerWeekdayEarlyMorning,
        #     Hour_08=self.LightingSummerWeekdayEarlyMorning,
        #     Hour_09=self.LightingSummerWeekdayMorning,
        #     Hour_10=self.LightingSummerWeekdayMorning,
        #     Hour_11=self.LightingSummerWeekdayMorning,
        #     Hour_12=self.LightingSummerWeekdayLunch,
        #     Hour_13=self.LightingSummerWeekdayLunch,
        #     Hour_14=self.LightingSummerWeekdayAfternoon,
        #     Hour_15=self.LightingSummerWeekdayAfternoon,
        #     Hour_16=self.LightingSummerWeekdayAfternoon,
        #     Hour_17=self.LightingSummerWeekdayAfternoon,
        #     Hour_18=self.LightingSummerWeekdayEvening,
        #     Hour_19=self.LightingSummerWeekdayEvening,
        #     Hour_20=self.LightingSummerWeekdayEvening,
        #     Hour_21=self.LightingSummerWeekdayNight,
        #     Hour_22=self.LightingSummerWeekdayNight,
        #     Hour_23=self.LightingSummerWeekdayNight,
        # )

        # lighting_summer_weekend = DayComponent(
        #     Name="Lighting_Summer_Weekend",
        #     Type="Fraction",
        #     Hour_00=self.LightingSummerWeekendNight,
        #     Hour_01=self.LightingSummerWeekendNight,
        #     Hour_02=self.LightingSummerWeekendNight,
        #     Hour_03=self.LightingSummerWeekendNight,
        #     Hour_04=self.LightingSummerWeekendNight,
        #     Hour_05=self.LightingSummerWeekendNight,
        #     Hour_06=self.LightingSummerWeekendEarlyMorning,
        #     Hour_07=self.LightingSummerWeekendEarlyMorning,
        #     Hour_08=self.LightingSummerWeekendEarlyMorning,
        #     Hour_09=self.LightingSummerWeekendMorning,
        #     Hour_10=self.LightingSummerWeekendMorning,
        #     Hour_11=self.LightingSummerWeekendMorning,
        #     Hour_12=self.LightingSummerWeekendLunch,
        #     Hour_13=self.LightingSummerWeekendLunch,
        #     Hour_14=self.LightingSummerWeekendAfternoon,
        #     Hour_15=self.LightingSummerWeekendAfternoon,
        #     Hour_16=self.LightingSummerWeekendAfternoon,
        #     Hour_17=self.LightingSummerWeekendAfternoon,
        #     Hour_18=self.LightingSummerWeekendEvening,
        #     Hour_19=self.LightingSummerWeekendEvening,
        #     Hour_20=self.LightingSummerWeekendEvening,
        #     Hour_21=self.LightingSummerWeekendNight,
        #     Hour_22=self.LightingSummerWeekendNight,
        #     Hour_23=self.LightingSummerWeekendNight,
        # )

        # lighting_regular_week = WeekComponent(
        #     Name="Lighting_Regular_Week",
        #     Monday=lighting_regular_workday,
        #     Tuesday=lighting_regular_workday,
        #     Wednesday=lighting_regular_workday,
        #     Thursday=lighting_regular_workday,
        #     Friday=lighting_regular_workday,
        #     Saturday=lighting_regular_weekend,
        #     Sunday=lighting_regular_weekend,
        # )

        # lighting_summer_week = WeekComponent(
        #     Name="Lighting_Summer_Week",
        #     Monday=lighting_summer_workday,
        #     Tuesday=lighting_summer_workday,
        #     Wednesday=lighting_summer_workday,
        #     Thursday=lighting_summer_workday,
        #     Friday=lighting_summer_workday,
        #     Saturday=lighting_summer_weekend,
        #     Sunday=lighting_summer_weekend,
        # )

        # lighting_year = YearComponent(
        #     Name="Lighting_Schedule",
        #     Type="Lighting",
        #     January=lighting_regular_week,
        #     February=lighting_regular_week,
        #     March=lighting_regular_week,
        #     April=lighting_regular_week,
        #     May=lighting_regular_week,
        #     June=lighting_summer_week,
        #     July=lighting_summer_week,
        #     August=lighting_summer_week,
        #     September=lighting_regular_week,
        #     October=lighting_regular_week,
        #     November=lighting_regular_week,
        #     December=lighting_regular_week,
        # )

        # equipment_regular_workday = DayComponent(
        #     Name="Equipment_Regular_Workday",
        #     Type="Fraction",
        #     Hour_00=self.EquipmentRegularWeekdayNight,
        #     Hour_01=self.EquipmentRegularWeekdayNight,
        #     Hour_02=self.EquipmentRegularWeekdayNight,
        #     Hour_03=self.EquipmentRegularWeekdayNight,
        #     Hour_04=self.EquipmentRegularWeekdayNight,
        #     Hour_05=self.EquipmentRegularWeekdayNight,
        #     Hour_06=self.EquipmentRegularWeekdayEarlyMorning,
        #     Hour_07=self.EquipmentRegularWeekdayEarlyMorning,
        #     Hour_08=self.EquipmentRegularWeekdayEarlyMorning,
        #     Hour_09=self.EquipmentRegularWeekdayMorning,
        #     Hour_10=self.EquipmentRegularWeekdayMorning,
        #     Hour_11=self.EquipmentRegularWeekdayMorning,
        #     Hour_12=self.EquipmentRegularWeekdayLunch,
        #     Hour_13=self.EquipmentRegularWeekdayLunch,
        #     Hour_14=self.EquipmentRegularWeekdayAfternoon,
        #     Hour_15=self.EquipmentRegularWeekdayAfternoon,
        #     Hour_16=self.EquipmentRegularWeekdayAfternoon,
        #     Hour_17=self.EquipmentRegularWeekdayAfternoon,
        #     Hour_18=self.EquipmentRegularWeekdayEvening,
        #     Hour_19=self.EquipmentRegularWeekdayEvening,
        #     Hour_20=self.EquipmentRegularWeekdayEvening,
        #     Hour_21=self.EquipmentRegularWeekdayNight,
        #     Hour_22=self.EquipmentRegularWeekdayNight,
        #     Hour_23=self.EquipmentRegularWeekdayNight,
        # )

        # equipment_regular_weekend = DayComponent(
        #     Name="Equipment_Regular_Weekend",
        #     Type="Fraction",
        #     Hour_00=self.EquipmentRegularWeekendNight,
        #     Hour_01=self.EquipmentRegularWeekendNight,
        #     Hour_02=self.EquipmentRegularWeekendNight,
        #     Hour_03=self.EquipmentRegularWeekendNight,
        #     Hour_04=self.EquipmentRegularWeekendNight,
        #     Hour_05=self.EquipmentRegularWeekendNight,
        #     Hour_06=self.EquipmentRegularWeekendEarlyMorning,
        #     Hour_07=self.EquipmentRegularWeekendEarlyMorning,
        #     Hour_08=self.EquipmentRegularWeekendEarlyMorning,
        #     Hour_09=self.EquipmentRegularWeekendMorning,
        #     Hour_10=self.EquipmentRegularWeekendMorning,
        #     Hour_11=self.EquipmentRegularWeekendMorning,
        #     Hour_12=self.EquipmentRegularWeekendLunch,
        #     Hour_13=self.EquipmentRegularWeekendLunch,
        #     Hour_14=self.EquipmentRegularWeekendAfternoon,
        #     Hour_15=self.EquipmentRegularWeekendAfternoon,
        #     Hour_16=self.EquipmentRegularWeekendAfternoon,
        #     Hour_17=self.EquipmentRegularWeekendAfternoon,
        #     Hour_18=self.EquipmentRegularWeekendEvening,
        #     Hour_19=self.EquipmentRegularWeekendEvening,
        #     Hour_20=self.EquipmentRegularWeekendEvening,
        #     Hour_21=self.EquipmentRegularWeekendNight,
        #     Hour_22=self.EquipmentRegularWeekendNight,
        #     Hour_23=self.EquipmentRegularWeekendNight,
        # )

        # equipment_summer_workday = DayComponent(
        #     Name="Equipment_Summer_Workday",
        #     Type="Fraction",
        #     Hour_00=self.EquipmentSummerWeekdayNight,
        #     Hour_01=self.EquipmentSummerWeekdayNight,
        #     Hour_02=self.EquipmentSummerWeekdayNight,
        #     Hour_03=self.EquipmentSummerWeekdayNight,
        #     Hour_04=self.EquipmentSummerWeekdayNight,
        #     Hour_05=self.EquipmentSummerWeekdayNight,
        #     Hour_06=self.EquipmentSummerWeekdayEarlyMorning,
        #     Hour_07=self.EquipmentSummerWeekdayEarlyMorning,
        #     Hour_08=self.EquipmentSummerWeekdayEarlyMorning,
        #     Hour_09=self.EquipmentSummerWeekdayMorning,
        #     Hour_10=self.EquipmentSummerWeekdayMorning,
        #     Hour_11=self.EquipmentSummerWeekdayMorning,
        #     Hour_12=self.EquipmentSummerWeekdayLunch,
        #     Hour_13=self.EquipmentSummerWeekdayLunch,
        #     Hour_14=self.EquipmentSummerWeekdayAfternoon,
        #     Hour_15=self.EquipmentSummerWeekdayAfternoon,
        #     Hour_16=self.EquipmentSummerWeekdayAfternoon,
        #     Hour_17=self.EquipmentSummerWeekdayAfternoon,
        #     Hour_18=self.EquipmentSummerWeekdayEvening,
        #     Hour_19=self.EquipmentSummerWeekdayEvening,
        #     Hour_20=self.EquipmentSummerWeekdayEvening,
        #     Hour_21=self.EquipmentSummerWeekdayNight,
        #     Hour_22=self.EquipmentSummerWeekdayNight,
        #     Hour_23=self.EquipmentSummerWeekdayNight,
        # )

        # equipment_summer_weekend = DayComponent(
        #     Name="Equipment_Summer_Weekend",
        #     Type="Fraction",
        #     Hour_00=self.EquipmentSummerWeekendNight,
        #     Hour_01=self.EquipmentSummerWeekendNight,
        #     Hour_02=self.EquipmentSummerWeekendNight,
        #     Hour_03=self.EquipmentSummerWeekendNight,
        #     Hour_04=self.EquipmentSummerWeekendNight,
        #     Hour_05=self.EquipmentSummerWeekendNight,
        #     Hour_06=self.EquipmentSummerWeekendEarlyMorning,
        #     Hour_07=self.EquipmentSummerWeekendEarlyMorning,
        #     Hour_08=self.EquipmentSummerWeekendEarlyMorning,
        #     Hour_09=self.EquipmentSummerWeekendMorning,
        #     Hour_10=self.EquipmentSummerWeekendMorning,
        #     Hour_11=self.EquipmentSummerWeekendMorning,
        #     Hour_12=self.EquipmentSummerWeekendLunch,
        #     Hour_13=self.EquipmentSummerWeekendLunch,
        #     Hour_14=self.EquipmentSummerWeekendAfternoon,
        #     Hour_15=self.EquipmentSummerWeekendAfternoon,
        #     Hour_16=self.EquipmentSummerWeekendAfternoon,
        #     Hour_17=self.EquipmentSummerWeekendAfternoon,
        #     Hour_18=self.EquipmentSummerWeekendEvening,
        #     Hour_19=self.EquipmentSummerWeekendEvening,
        #     Hour_20=self.EquipmentSummerWeekendEvening,
        #     Hour_21=self.EquipmentSummerWeekendNight,
        #     Hour_22=self.EquipmentSummerWeekendNight,
        #     Hour_23=self.EquipmentSummerWeekendNight,
        # )

        # equipment_regular_week = WeekComponent(
        #     Name="Equipment_Regular_Week",
        #     Monday=equipment_regular_workday,
        #     Tuesday=equipment_regular_workday,
        #     Wednesday=equipment_regular_workday,
        #     Thursday=equipment_regular_workday,
        #     Friday=equipment_regular_workday,
        #     Saturday=equipment_regular_weekend,
        #     Sunday=equipment_regular_weekend,
        # )

        # equipment_summer_week = WeekComponent(
        #     Name="Equipment_Summer_Week",
        #     Monday=equipment_summer_workday,
        #     Tuesday=equipment_summer_workday,
        #     Wednesday=equipment_summer_workday,
        #     Thursday=equipment_summer_workday,
        #     Friday=equipment_summer_workday,
        #     Saturday=equipment_summer_weekend,
        #     Sunday=equipment_summer_weekend,
        # )

        # equipment_year = YearComponent(
        #     Name="equipment_Schedule",
        #     Type="Equipment",
        #     January=equipment_regular_week,
        #     February=equipment_regular_week,
        #     March=equipment_regular_week,
        #     April=equipment_regular_week,
        #     May=equipment_regular_week,
        #     June=equipment_summer_week,
        #     July=equipment_summer_week,
        #     August=equipment_summer_week,
        #     September=equipment_regular_week,
        #     October=equipment_regular_week,
        #     November=lighting_regular_week,
        #     December=equipment_regular_week,
        # )

        equipment_paramteric = ParametericYear(
            Base=self.EquipmentBase,
            AMInterp=self.EquipmentAMInterp,
            LunchInterp=self.EquipmentLunchInterp,
            PMInterp=self.EquipmentPMInterp,
            WeekendPeakInterp=self.EquipmentWeekendPeakInterp,
            SummerPeakInterp=self.EquipmentSummerPeakInterp,
        )

        lighting_paramteric = ParametericYear(
            Base=self.LightingBase,
            AMInterp=self.LightingAMInterp,
            LunchInterp=self.LightingLunchInterp,
            PMInterp=self.LightingPMInterp,
            WeekendPeakInterp=self.LightingWeekendPeakInterp,
            SummerPeakInterp=self.LightingSummerPeakInterp,
        )

        occupancy_paramteric = ParametericYear(
            Base=self.OccupancyBase,
            AMInterp=self.OccupancyAMInterp,
            LunchInterp=self.OccupancyLunchInterp,
            PMInterp=self.OccupancyPMInterp,
            WeekendPeakInterp=self.OccupancyWeekendPeakInterp,
            SummerPeakInterp=self.OccupancySummerPeakInterp,
        )

        equipment_schedule = equipment_paramteric.to_schedule(
            name="Equipment", category="Equipment"
        )
        lighting_schedule = lighting_paramteric.to_schedule(
            name="Lighting", category="Lighting"
        )
        occupancy_schedule = occupancy_paramteric.to_schedule(
            name="Occupancy", category="Occupancy"
        )

        # hsp_regular_workday = DayComponent(
        #     Name="HeatingSetpoint_Regular_Workday",
        #     Type="Temperature",
        #     Hour_00=self.HSPRegularWeekdayNight,
        #     Hour_01=self.HSPRegularWeekdayNight,
        #     Hour_02=self.HSPRegularWeekdayNight,
        #     Hour_03=self.HSPRegularWeekdayNight,
        #     Hour_04=self.HSPRegularWeekdayNight,
        #     Hour_05=self.HSPRegularWeekdayNight,
        #     Hour_06=self.HSPRegularWeekdayWorkhours,
        #     Hour_07=self.HSPRegularWeekdayWorkhours,
        #     Hour_08=self.HSPRegularWeekdayWorkhours,
        #     Hour_09=self.HSPRegularWeekdayWorkhours,
        #     Hour_10=self.HSPRegularWeekdayWorkhours,
        #     Hour_11=self.HSPRegularWeekdayWorkhours,
        #     Hour_12=self.HSPRegularWeekdayWorkhours,
        #     Hour_13=self.HSPRegularWeekdayWorkhours,
        #     Hour_14=self.HSPRegularWeekdayWorkhours,
        #     Hour_15=self.HSPRegularWeekdayWorkhours,
        #     Hour_16=self.HSPRegularWeekdayWorkhours,
        #     Hour_17=self.HSPRegularWeekdayWorkhours,
        #     Hour_18=self.HSPRegularWeekdayWorkhours,
        #     Hour_19=self.HSPRegularWeekdayNight,
        #     Hour_20=self.HSPRegularWeekdayNight,
        #     Hour_21=self.HSPRegularWeekdayNight,
        #     Hour_22=self.HSPRegularWeekdayNight,
        #     Hour_23=self.HSPRegularWeekdayNight,
        # )

        # hsp_regular_weekend = DayComponent(
        #     Name="HeatingSetpoint_Regular_Weekend",
        #     Type="Temperature",
        #     Hour_00=self.HSPWeekendNight,
        #     Hour_01=self.HSPWeekendNight,
        #     Hour_02=self.HSPWeekendNight,
        #     Hour_03=self.HSPWeekendNight,
        #     Hour_04=self.HSPWeekendNight,
        #     Hour_05=self.HSPWeekendNight,
        #     Hour_06=self.HSPWeekendWorkhours,
        #     Hour_07=self.HSPWeekendWorkhours,
        #     Hour_08=self.HSPWeekendWorkhours,
        #     Hour_09=self.HSPWeekendWorkhours,
        #     Hour_10=self.HSPWeekendWorkhours,
        #     Hour_11=self.HSPWeekendWorkhours,
        #     Hour_12=self.HSPWeekendWorkhours,
        #     Hour_13=self.HSPWeekendWorkhours,
        #     Hour_14=self.HSPWeekendWorkhours,
        #     Hour_15=self.HSPWeekendWorkhours,
        #     Hour_16=self.HSPWeekendWorkhours,
        #     Hour_17=self.HSPWeekendWorkhours,
        #     Hour_18=self.HSPWeekendWorkhours,
        #     Hour_19=self.HSPWeekendNight,
        #     Hour_20=self.HSPWeekendNight,
        #     Hour_21=self.HSPWeekendNight,
        #     Hour_22=self.HSPWeekendNight,
        #     Hour_23=self.HSPWeekendNight,
        # )

        # hsp_summer_workday = DayComponent(
        #     Name="HeatingSetpoint_Summer_Workday",
        #     Type="Temperature",
        #     Hour_00=self.HSPSummerWeekdayNight,
        #     Hour_01=self.HSPSummerWeekdayNight,
        #     Hour_02=self.HSPSummerWeekdayNight,
        #     Hour_03=self.HSPSummerWeekdayNight,
        #     Hour_04=self.HSPSummerWeekdayNight,
        #     Hour_05=self.HSPSummerWeekdayNight,
        #     Hour_06=self.HSPSummerWeekdayWorkhours,
        #     Hour_07=self.HSPSummerWeekdayWorkhours,
        #     Hour_08=self.HSPSummerWeekdayWorkhours,
        #     Hour_09=self.HSPSummerWeekdayWorkhours,
        #     Hour_10=self.HSPSummerWeekdayWorkhours,
        #     Hour_11=self.HSPSummerWeekdayWorkhours,
        #     Hour_12=self.HSPSummerWeekdayWorkhours,
        #     Hour_13=self.HSPSummerWeekdayWorkhours,
        #     Hour_14=self.HSPSummerWeekdayWorkhours,
        #     Hour_15=self.HSPSummerWeekdayWorkhours,
        #     Hour_16=self.HSPSummerWeekdayWorkhours,
        #     Hour_17=self.HSPSummerWeekdayWorkhours,
        #     Hour_18=self.HSPSummerWeekdayWorkhours,
        #     Hour_19=self.HSPSummerWeekdayNight,
        #     Hour_20=self.HSPSummerWeekdayNight,
        #     Hour_21=self.HSPSummerWeekdayNight,
        #     Hour_22=self.HSPSummerWeekdayNight,
        #     Hour_23=self.HSPSummerWeekdayNight,
        # )

        # hsp_regular_week = WeekComponent(
        #     Name="HeatingSetpoint_Regular_Week",
        #     Monday=hsp_regular_workday,
        #     Tuesday=hsp_regular_workday,
        #     Wednesday=hsp_regular_workday,
        #     Thursday=hsp_regular_workday,
        #     Friday=hsp_regular_workday,
        #     Saturday=hsp_regular_weekend,
        #     Sunday=hsp_regular_weekend,
        # )

        # hsp_summer_week = WeekComponent(
        #     Name="HeatingSetpoint_Summer_Week",
        #     Monday=hsp_summer_workday,
        #     Tuesday=hsp_summer_workday,
        #     Wednesday=hsp_summer_workday,
        #     Thursday=hsp_summer_workday,
        #     Friday=hsp_summer_workday,
        #     Saturday=hsp_regular_weekend,
        #     Sunday=hsp_regular_weekend,
        # )

        # hsp_year = YearComponent(
        #     Name="HeatingSetpoint_Schedule",
        #     Type="Setpoint",
        #     January=hsp_regular_week,
        #     February=hsp_regular_week,
        #     March=hsp_regular_week,
        #     April=hsp_regular_week,
        #     May=hsp_regular_week,
        #     June=hsp_summer_week,
        #     July=hsp_summer_week,
        #     August=hsp_summer_week,
        #     September=hsp_regular_week,
        #     October=hsp_regular_week,
        #     November=hsp_regular_week,
        #     December=hsp_regular_week,
        # )

        # csp_regular_workday = DayComponent(
        #     Name="CoolingSetpoint_Regular_Workday",
        #     Type="Temperature",
        #     Hour_00=self.CSPRegularWeekdayNight,
        #     Hour_01=self.CSPRegularWeekdayNight,
        #     Hour_02=self.CSPRegularWeekdayNight,
        #     Hour_03=self.CSPRegularWeekdayNight,
        #     Hour_04=self.CSPRegularWeekdayNight,
        #     Hour_05=self.CSPRegularWeekdayNight,
        #     Hour_06=self.CSPRegularWeekdayWorkhours,
        #     Hour_07=self.CSPRegularWeekdayWorkhours,
        #     Hour_08=self.CSPRegularWeekdayWorkhours,
        #     Hour_09=self.CSPRegularWeekdayWorkhours,
        #     Hour_10=self.CSPRegularWeekdayWorkhours,
        #     Hour_11=self.CSPRegularWeekdayWorkhours,
        #     Hour_12=self.CSPRegularWeekdayWorkhours,
        #     Hour_13=self.CSPRegularWeekdayWorkhours,
        #     Hour_14=self.CSPRegularWeekdayWorkhours,
        #     Hour_15=self.CSPRegularWeekdayWorkhours,
        #     Hour_16=self.CSPRegularWeekdayWorkhours,
        #     Hour_17=self.CSPRegularWeekdayWorkhours,
        #     Hour_18=self.CSPRegularWeekdayWorkhours,
        #     Hour_19=self.CSPRegularWeekdayNight,
        #     Hour_20=self.CSPRegularWeekdayNight,
        #     Hour_21=self.CSPRegularWeekdayNight,
        #     Hour_22=self.CSPRegularWeekdayNight,
        #     Hour_23=self.CSPRegularWeekdayNight,
        # )

        # csp_regular_weekend = DayComponent(
        #     Name="CoolingSetpoint_Regular_Weekend",
        #     Type="Temperature",
        #     Hour_00=self.CSPWeekendNight,
        #     Hour_01=self.CSPWeekendNight,
        #     Hour_02=self.CSPWeekendNight,
        #     Hour_03=self.CSPWeekendNight,
        #     Hour_04=self.CSPWeekendNight,
        #     Hour_05=self.CSPWeekendNight,
        #     Hour_06=self.CSPWeekendWorkhours,
        #     Hour_07=self.CSPWeekendWorkhours,
        #     Hour_08=self.CSPWeekendWorkhours,
        #     Hour_09=self.CSPWeekendWorkhours,
        #     Hour_10=self.CSPWeekendWorkhours,
        #     Hour_11=self.CSPWeekendWorkhours,
        #     Hour_12=self.CSPWeekendWorkhours,
        #     Hour_13=self.CSPWeekendWorkhours,
        #     Hour_14=self.CSPWeekendWorkhours,
        #     Hour_15=self.CSPWeekendWorkhours,
        #     Hour_16=self.CSPWeekendWorkhours,
        #     Hour_17=self.CSPWeekendWorkhours,
        #     Hour_18=self.CSPWeekendWorkhours,
        #     Hour_19=self.CSPWeekendNight,
        #     Hour_20=self.CSPWeekendNight,
        #     Hour_21=self.CSPWeekendNight,
        #     Hour_22=self.CSPWeekendNight,
        #     Hour_23=self.CSPWeekendNight,
        # )

        # csp_summer_workday = DayComponent(
        #     Name="CoolingSetpoint_Summer_Workday",
        #     Type="Temperature",
        #     Hour_00=self.CSPSummerWeekdayNight,
        #     Hour_01=self.CSPSummerWeekdayNight,
        #     Hour_02=self.CSPSummerWeekdayNight,
        #     Hour_03=self.CSPSummerWeekdayNight,
        #     Hour_04=self.CSPSummerWeekdayNight,
        #     Hour_05=self.CSPSummerWeekdayNight,
        #     Hour_06=self.CSPSummerWeekdayWorkhours,
        #     Hour_07=self.CSPSummerWeekdayWorkhours,
        #     Hour_08=self.CSPSummerWeekdayWorkhours,
        #     Hour_09=self.CSPSummerWeekdayWorkhours,
        #     Hour_10=self.CSPSummerWeekdayWorkhours,
        #     Hour_11=self.CSPSummerWeekdayWorkhours,
        #     Hour_12=self.CSPSummerWeekdayWorkhours,
        #     Hour_13=self.CSPSummerWeekdayWorkhours,
        #     Hour_14=self.CSPSummerWeekdayWorkhours,
        #     Hour_15=self.CSPSummerWeekdayWorkhours,
        #     Hour_16=self.CSPSummerWeekdayWorkhours,
        #     Hour_17=self.CSPSummerWeekdayWorkhours,
        #     Hour_18=self.CSPSummerWeekdayWorkhours,
        #     Hour_19=self.CSPSummerWeekdayNight,
        #     Hour_20=self.CSPSummerWeekdayNight,
        #     Hour_21=self.CSPSummerWeekdayNight,
        #     Hour_22=self.CSPSummerWeekdayNight,
        #     Hour_23=self.CSPSummerWeekdayNight,
        # )

        # csp_regular_week = WeekComponent(
        #     Name="CoolingSetpoint_Regular_Week",
        #     Monday=csp_regular_workday,
        #     Tuesday=csp_regular_workday,
        #     Wednesday=csp_regular_workday,
        #     Thursday=csp_regular_workday,
        #     Friday=csp_regular_workday,
        #     Saturday=csp_regular_weekend,
        #     Sunday=csp_regular_weekend,
        # )

        # csp_summer_week = WeekComponent(
        #     Name="CoolingSetpoint_Summer_Week",
        #     Monday=csp_summer_workday,
        #     Tuesday=csp_summer_workday,
        #     Wednesday=csp_summer_workday,
        #     Thursday=csp_summer_workday,
        #     Friday=csp_summer_workday,
        #     Saturday=csp_regular_weekend,
        #     Sunday=csp_regular_weekend,
        # )

        # csp_year = YearComponent(
        #     Name="CoolingSetpoint_Schedule",
        #     Type="Setpoint",
        #     January=csp_regular_week,
        #     February=csp_regular_week,
        #     March=csp_regular_week,
        #     April=csp_regular_week,
        #     May=csp_regular_week,
        #     June=csp_summer_week,
        #     July=csp_summer_week,
        #     August=csp_summer_week,
        #     September=csp_regular_week,
        #     October=csp_regular_week,
        #     November=csp_regular_week,
        #     December=csp_regular_week,
        # )

        setpoint_parametric = ParametricSetpoints(
            HeatingSetpoint=self.HeatingSetpointBase,
            DeadBand=self.SetpointDeadband,
            HeatingSetback=self.HeatingSetpointSetback,
            CoolingSetback=self.CoolingSetpointSetback,
            NightSetback=self.NightSetback,
            WeekendSetback=self.WeekendSetback,
            SummerSetback=self.SummerSetback,
        )

        hsp_year, csp_year = setpoint_parametric.to_schedules()

        thermostat = ThermostatComponent(
            Name="Thermostat",
            IsOn=True,
            HeatingSetpoint=hsp_year.January.Monday.Hour_12,
            CoolingSetpoint=csp_year.January.Monday.Hour_12,
            HeatingSchedule=hsp_year,
            CoolingSchedule=csp_year,
        )

        equipment = EquipmentComponent(
            Name="Equipment",
            PowerDensity=self.EquipmentPowerDensity,
            Schedule=equipment_schedule,
            IsOn=True,
        )

        lighting = LightingComponent(
            Name="Lighting",
            PowerDensity=self.LightingPowerDensity,
            Schedule=lighting_schedule,
            IsOn=True,
            DimmingType="Off",
        )

        occupancy = OccupancyComponent(
            Name="Occupancy",
            PeopleDensity=self.OccupantDensity,
            Schedule=occupancy_schedule,
            IsOn=True,
        )

        water_use = WaterUseComponent(
            Name="WaterUse",
            FlowRatePerPerson=self.DHWFlowRatePerPerson,
            Schedule=occupancy_schedule,
        )

        space_use = ZoneSpaceUseComponent(
            Name="SpaceUse",
            Occupancy=occupancy,
            Lighting=lighting,
            Equipment=equipment,
            Thermostat=thermostat,
            WaterUse=water_use,
        )

        heating_system = ThermalSystemComponent(
            Name="HeatingSystem",
            ConditioningType="Heating",
            Fuel=self.HeatingFuel,
            SystemCOP=self.HeatingSystemCOP,
            DistributionCOP=self.HeatingDistributionCOP,
        )

        cooling_system = ThermalSystemComponent(
            Name="CoolingSystem",
            ConditioningType="Cooling",
            Fuel=self.CoolingFuel,
            SystemCOP=self.CoolingSystemCOP,
            DistributionCOP=self.CoolingDistributionCOP,
        )

        conditioning_system = ConditioningSystemsComponent(
            Name="ConditioningSystem",
            Heating=heating_system,
            Cooling=cooling_system,
        )

        all_off_day = DayComponent(
            Name="AllOffDayComponent",
            Type="Fraction",
            Hour_00=0.0,
            Hour_01=0.0,
            Hour_02=0.0,
            Hour_03=0.0,
            Hour_04=0.0,
            Hour_05=0.0,
            Hour_06=0.0,
            Hour_07=0.0,
            Hour_08=0.0,
            Hour_09=0.0,
            Hour_10=0.0,
            Hour_11=0.0,
            Hour_12=0.0,
            Hour_13=0.0,
            Hour_14=0.0,
            Hour_15=0.0,
            Hour_16=0.0,
            Hour_17=0.0,
            Hour_18=0.0,
            Hour_19=0.0,
            Hour_20=0.0,
            Hour_21=0.0,
            Hour_22=0.0,
            Hour_23=0.0,
        )

        all_off_week = WeekComponent(
            Name="AllOffWeekComponent",
            Monday=all_off_day,
            Tuesday=all_off_day,
            Wednesday=all_off_day,
            Thursday=all_off_day,
            Friday=all_off_day,
            Saturday=all_off_day,
            Sunday=all_off_day,
        )

        all_off_year = YearComponent(
            Name="AllOffYearComponent",
            Type="Window",
            January=all_off_week,
            February=all_off_week,
            March=all_off_week,
            April=all_off_week,
            May=all_off_week,
            June=all_off_week,
            July=all_off_week,
            August=all_off_week,
            September=all_off_week,
            October=all_off_week,
            November=all_off_week,
            December=all_off_week,
        )

        ventilation_system = VentilationComponent(
            Name="VentilationSystem",
            FreshAirPerFloorArea=self.VentFlowRatePerArea,
            FreshAirPerPerson=self.VentFlowRatePerPerson,
            Provider=self.VentProvider,
            # TODO: should hrv sensible/latent efficiency be configurable? (e.g. high/medium/low)
            HRV=self.VentHRV,
            Economizer=self.VentEconomizer,
            DCV=self.VentDCV,
            # TODO: this controls natvnent and should
            # be configurable for residential models
            Schedule=all_off_year,
        )

        hvac = ZoneHVACComponent(
            Name="HVAC",
            ConditioningSystems=conditioning_system,
            Ventilation=ventilation_system,
        )

        dhw = DHWComponent(
            Name="DHW",
            SystemCOP=self.DHWSystemCOP,
            DistributionCOP=self.DHWDistributionCOP,
            # TODO: should these be configurable?
            WaterTemperatureInlet=10,
            WaterSupplyTemperature=55,
            IsOn=True,
            FuelType=self.DHWFuel,
        )

        operations = ZoneOperationsComponent(
            Name="Operations",
            SpaceUse=space_use,
            HVAC=hvac,
            DHW=dhw,
        )

        window_assembly = GlazingConstructionSimpleComponent(
            Name="WindowAssembly",
            UValue=self.WindowUValue,
            SHGF=self.WindowSHGF,
            TVis=self.WindowTVis,
            Type="Single",
        )

        infiltration = InfiltrationComponent(
            Name="Infiltration",
            IsOn=True,
            CalculationMethod="AirChanges/Hour",
            AirChangesPerHour=self.InfiltrationACH,
            ConstantCoefficient=0.0,
            TemperatureCoefficient=0.0,
            WindVelocityCoefficient=0.0,
            WindVelocitySquaredCoefficient=0.0,
            AFNAirMassFlowCoefficientCrack=0.0,
            FlowPerExteriorSurfaceArea=0.0,
        )

        # TODO: verify interior/exterior
        # TODO: are we okaky with mass assumptions?
        facade = ConstructionAssemblyComponent(
            Name="Facade",
            Type="Facade",
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=clay_brick,
                    Thickness=0.002,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=concrete_block_h,
                    Thickness=0.15,
                    LayerOrder=1,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=fiberglass_batts,
                    Thickness=0.05,
                    LayerOrder=2,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=gypsum_board,
                    Thickness=0.015,
                    LayerOrder=3,
                ),
            ],
        )

        facade_r_value_without_fiberglass = (
            facade.r_value - facade.sorted_layers[2].r_value
        )

        facade_r_value_delta = self.FacadeRValue - facade_r_value_without_fiberglass
        required_fiberglass_thickness = (
            fiberglass_batts.Conductivity * facade_r_value_delta
        )

        if required_fiberglass_thickness < 0.003:
            msg = f"Required Facade Fiberglass thickness is less than 3mm because the desired total facade R-value is {self.FacadeRValue} m²K/W but the concrete and gypsum layers already have a total R-value of {facade_r_value_without_fiberglass} m²K/W."
            raise ValueError(msg)

        facade.sorted_layers[2].Thickness = required_fiberglass_thickness

        roof = ConstructionAssemblyComponent(
            Name="Roof",
            Type="FlatRoof",
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=xps_board,
                    Thickness=0.1,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=concrete_mc_light,
                    Thickness=0.15,
                    LayerOrder=1,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=concrete_rc_dense,
                    Thickness=0.2,
                    LayerOrder=2,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=gypsum_board,
                    Thickness=0.02,
                    LayerOrder=3,
                ),
            ],
        )

        roof_r_value_without_xps = roof.r_value - roof.sorted_layers[0].r_value
        roof_r_value_delta = self.RoofRValue - roof_r_value_without_xps
        required_xps_thickness = xps_board.Conductivity * roof_r_value_delta
        if required_xps_thickness < 0.003:
            msg = f"Required Roof XPS thickness is less than 3mm because the desired total roof R-value is {self.RoofRValue} m²K/W but the concrete layers already have a total R-value of {roof_r_value_without_xps} m²K/W."
            raise ValueError(msg)

        roof.sorted_layers[0].Thickness = required_xps_thickness

        partition = ConstructionAssemblyComponent(
            Name="Partition",
            Type="Partition",
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=gypsum_plaster,
                    Thickness=0.02,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=softwood_general,
                    Thickness=0.02,
                    LayerOrder=1,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=gypsum_plaster,
                    Thickness=0.02,
                    LayerOrder=2,
                ),
            ],
        )

        floor_ceiling = ConstructionAssemblyComponent(
            Name="FloorCeiling",
            Type="FloorCeiling",
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=urethane_carpet,
                    Thickness=0.02,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=cement_mortar,
                    Thickness=0.02,
                    LayerOrder=1,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=concrete_rc_dense,
                    Thickness=0.15,
                    LayerOrder=2,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=gypsum_board,
                    Thickness=0.02,
                    LayerOrder=3,
                ),
            ],
        )

        ground_slab_assembly = ConstructionAssemblyComponent(
            Name="GroundSlabAssembly",
            Type="GroundSlab",
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=xps_board,
                    Thickness=0.02,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=concrete_rc_dense,
                    Thickness=0.15,
                    LayerOrder=1,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=concrete_mc_light,
                    Thickness=0.04,
                    LayerOrder=2,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=cement_mortar,
                    Thickness=0.03,
                    LayerOrder=3,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=ceramic_tile,
                    Thickness=0.02,
                    LayerOrder=4,
                ),
            ],
        )

        ground_slab_r_value_without_xps = (
            ground_slab_assembly.r_value - ground_slab_assembly.sorted_layers[0].r_value
        )
        ground_slab_r_value_delta = self.SlabRValue - ground_slab_r_value_without_xps
        required_xps_thickness = xps_board.Conductivity * ground_slab_r_value_delta
        if required_xps_thickness < 0.003:
            msg = f"Required Ground Slab XPS thickness is less than 3mm because the desired total slab R-value is {self.SlabRValue} m²K/W but the concrete layers already have a total R-value of {ground_slab_r_value_without_xps} m²K/W."
            raise ValueError(msg)

        ground_slab_assembly.sorted_layers[0].Thickness = required_xps_thickness

        assemblies = EnvelopeAssemblyComponent(
            Name="EnvelopeAssemblies",
            FacadeAssembly=facade,
            FlatRoofAssembly=roof,
            AtticRoofAssembly=roof,
            PartitionAssembly=partition,
            FloorCeilingAssembly=floor_ceiling,
            AtticFloorAssembly=floor_ceiling,
            BasementCeilingAssembly=floor_ceiling,
            GroundSlabAssembly=ground_slab_assembly,
            GroundWallAssembly=ground_slab_assembly,
            ExternalFloorAssembly=ground_slab_assembly,
        )

        basement_infiltration = infiltration.model_copy(deep=True)
        envelope = ZoneEnvelopeComponent(
            Name="Envelope",
            AtticInfiltration=infiltration,
            BasementInfiltration=basement_infiltration,
            Window=window_assembly,
            Infiltration=infiltration,
            Assemblies=assemblies,
        )

        zone = ZoneComponent(
            Name="Zone",
            Operations=operations,
            Envelope=envelope,
        )

        return zone

    def to_model(self) -> tuple[Model, Callable[[EPDocument], EPDocument]]:
        """Returns a tuple of a Model and a post-geometry callback."""
        zone = self.to_zone()
        # TODO: add in a shading mask
        geometry = ShoeboxGeometry(
            x=0,
            y=0,
            w=self.Width,
            d=self.Depth,
            h=self.F2FHeight,
            num_stories=self.NFloors,
            # TODO: should core/perim be dependent on width, depth > 9m?
            zoning="core/perim",
            roof_height=None,
            wwr=self.WWR,
            basement=False,
        )

        def post_geometry_callback(doc: EPDocument) -> EPDocument:
            rotate_building(doc, self.Rotation, anchor=_floor_plan_centre(doc))
            return doc

        return (
            Model(
                geometry=geometry,
                Zone=zone,
                Attic=AtticAssumptions(
                    UseFraction=None,
                    Conditioned=False,
                ),
                Basement=BasementAssumptions(
                    UseFraction=None,
                    Conditioned=False,
                ),
                Weather=self.EPWURI,
            ),
            post_geometry_callback,
        )

    def simulate(
        self,
        overheating_config: OverheatingAnalysisConfig | None = None,
        eplus_parent_dir: Path | None = None,
    ):
        """Simulate the model and return the IDF, result, and error."""
        model, cb = self.to_model()

        r = model.run(
            post_geometry_callback=cb,
            eplus_parent_dir=eplus_parent_dir,
            overheating_config=overheating_config,
        )

        return r


def _floor_plan_centre(doc: EPDocument) -> Vector3D:
    """The centre of the floors' x-y bounding box (geomeppy's rotation anchor)."""
    points = [
        vertex
        for srf in doc["BuildingSurface:Detailed"]
        if (srf.surface_type or "").lower() == "floor"
        and (polygon := get_surface_coords(srf)) is not None
        for vertex in polygon.vertices
    ]
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return Vector3D((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, 0)


if __name__ == "__main__":
    flat_model = FlatModel(
        F2FHeight=3.25,
        Width=40,
        Depth=40,
        Rotation=45,
        WWR=0.3,
        NFloors=2,
        FacadeRValue=3.0,
        RoofRValue=3.0,
        SlabRValue=3.0,
        WindowUValue=3.0,
        WindowSHGF=0.7,
        WindowTVis=0.5,
        InfiltrationACH=0.5,
        VentFlowRatePerArea=0.001,
        VentFlowRatePerPerson=0.0085,
        VentProvider="Mechanical",
        VentHRV="NoHRV",
        VentEconomizer="NoEconomizer",
        VentDCV="NoDCV",
        DHWFlowRatePerPerson=0.010,
        DHWFuel="Electricity",
        DHWSystemCOP=1.0,
        DHWDistributionCOP=1.0,
        EquipmentPowerDensity=25,
        LightingPowerDensity=10,
        OccupantDensity=0.01,
        EquipmentBase=0.4,
        EquipmentAMInterp=0.5,
        EquipmentLunchInterp=0.8,
        EquipmentPMInterp=0.5,
        EquipmentWeekendPeakInterp=0.25,
        EquipmentSummerPeakInterp=0.5,
        LightingBase=0.3,
        LightingAMInterp=0.75,
        LightingLunchInterp=0.75,
        LightingPMInterp=0.9,
        LightingWeekendPeakInterp=0.75,
        LightingSummerPeakInterp=0.9,
        OccupancyBase=0.05,
        OccupancyAMInterp=0.25,
        OccupancyLunchInterp=0.9,
        OccupancyPMInterp=0.5,
        OccupancyWeekendPeakInterp=0.15,
        OccupancySummerPeakInterp=0.85,
        # HSPRegularWeekdayWorkhours=21,
        # HSPRegularWeekdayNight=21,
        # HSPSummerWeekdayWorkhours=21,
        # HSPSummerWeekdayNight=21,
        # HSPWeekendWorkhours=21,
        # HSPWeekendNight=21,
        # CSPRegularWeekdayWorkhours=23,
        # CSPRegularWeekdayNight=23,
        # CSPSummerWeekdayWorkhours=23,
        # CSPSummerWeekdayNight=23,
        # CSPWeekendWorkhours=23,
        # CSPWeekendNight=23,
        HeatingSetpointBase=21,
        SetpointDeadband=2,
        HeatingSetpointSetback=2,
        CoolingSetpointSetback=2,
        NightSetback=0.5,
        WeekendSetback=0.5,
        SummerSetback=0.5,
        HeatingFuel="Electricity",
        CoolingFuel="Electricity",
        HeatingSystemCOP=1.0,
        CoolingSystemCOP=1.0,
        HeatingDistributionCOP=1.0,
        CoolingDistributionCOP=1.0,
        EPWURI=WeatherUrl(  # pyright: ignore [reportCallIssue]
            "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/MA_Massachusetts/USA_MA_Bedford-Hanscom.Field.AP.744900_TMYx.2009-2023.zip"
        ),
    )

    r = flat_model.simulate()

    print(r.energy_and_peak.groupby(level=["Measurement", "Aggregation"]).sum())
