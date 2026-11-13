"""A simple testing script for the epinterface.sbem library."""

from idfkit import save_idf
from pydantic import BaseModel

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
    EconomizerMethod,
    HRVMethod,
    ThermalSystemComponent,
    VentilationComponent,
    VentilationProvider,
    ZoneHVACComponent,
)
from epinterface.sbem.components.zones import ZoneComponent


class FlatParameters(BaseModel):
    """A flattened set of parameters for invoking building energy models more conveniently."""

    CoolingSetpoint: float
    HeatingSetpoint: float
    EquipmentPowerDensity: float
    LightingPowerDensity: float
    PeopleDensity: float

    VentFlowRatePerPerson: float
    VentFlowRatePerArea: float
    VentProvider: VentilationProvider
    VentHRV: HRVMethod
    VentEconomizer: EconomizerMethod
    VentDCV: DCVMethod

    DHWFlowRatePerPerson: float

    InfiltrationACH: float
    WindowUValue: float
    WindowSHGF: float
    WindowTVis: float

    FacadeRValue: float
    RoofRValue: float
    SlabRValue: float

    WWR: float
    f2f_height: float
    num_stories: int
    width: float
    depth: float

    weather_url: str

    def to_zone(self) -> ZoneComponent:
        """Convert the parameters to a zone component."""
        thermostat_heating_day = DayComponent(
            Name="Thermostat Heating Day",
            Type="Temperature",
            Hour_00=self.HeatingSetpoint,
            Hour_01=self.HeatingSetpoint,
            Hour_02=self.HeatingSetpoint,
            Hour_03=self.HeatingSetpoint,
            Hour_04=self.HeatingSetpoint,
            Hour_05=self.HeatingSetpoint,
            Hour_06=self.HeatingSetpoint,
            Hour_07=self.HeatingSetpoint,
            Hour_08=self.HeatingSetpoint,
            Hour_09=self.HeatingSetpoint,
            Hour_10=self.HeatingSetpoint,
            Hour_11=self.HeatingSetpoint,
            Hour_12=self.HeatingSetpoint,
            Hour_13=self.HeatingSetpoint,
            Hour_14=self.HeatingSetpoint,
            Hour_15=self.HeatingSetpoint,
            Hour_16=self.HeatingSetpoint,
            Hour_17=self.HeatingSetpoint,
            Hour_18=self.HeatingSetpoint,
            Hour_19=self.HeatingSetpoint,
            Hour_20=self.HeatingSetpoint,
            Hour_21=self.HeatingSetpoint,
            Hour_22=self.HeatingSetpoint,
            Hour_23=self.HeatingSetpoint,
        )

        thermostat_cooling_day = DayComponent(
            Name="Thermostat Cooling Day",
            Type="Temperature",
            Hour_00=self.CoolingSetpoint,
            Hour_01=self.CoolingSetpoint,
            Hour_02=self.CoolingSetpoint,
            Hour_03=self.CoolingSetpoint,
            Hour_04=self.CoolingSetpoint,
            Hour_05=self.CoolingSetpoint,
            Hour_06=self.CoolingSetpoint,
            Hour_07=self.CoolingSetpoint,
            Hour_08=self.CoolingSetpoint,
            Hour_09=self.CoolingSetpoint,
            Hour_10=self.CoolingSetpoint,
            Hour_11=self.CoolingSetpoint,
            Hour_12=self.CoolingSetpoint,
            Hour_13=self.CoolingSetpoint,
            Hour_14=self.CoolingSetpoint,
            Hour_15=self.CoolingSetpoint,
            Hour_16=self.CoolingSetpoint,
            Hour_17=self.CoolingSetpoint,
            Hour_18=self.CoolingSetpoint,
            Hour_19=self.CoolingSetpoint,
            Hour_20=self.CoolingSetpoint,
            Hour_21=self.CoolingSetpoint,
            Hour_22=self.CoolingSetpoint,
            Hour_23=self.CoolingSetpoint,
        )

        thermostat_heating_week = WeekComponent(
            Name="Thermostat Heating Week",
            Monday=thermostat_heating_day,
            Tuesday=thermostat_heating_day,
            Wednesday=thermostat_heating_day,
            Thursday=thermostat_heating_day,
            Friday=thermostat_heating_day,
            Saturday=thermostat_heating_day,
            Sunday=thermostat_heating_day,
        )

        thermostat_cooling_week = WeekComponent(
            Name="Thermostat Cooling Week",
            Monday=thermostat_cooling_day,
            Tuesday=thermostat_cooling_day,
            Wednesday=thermostat_cooling_day,
            Thursday=thermostat_cooling_day,
            Friday=thermostat_cooling_day,
            Saturday=thermostat_cooling_day,
            Sunday=thermostat_cooling_day,
        )

        thermostat_heating_year = YearComponent(
            Name="Thermostat Heating Year",
            January=thermostat_heating_week,
            February=thermostat_heating_week,
            March=thermostat_heating_week,
            April=thermostat_heating_week,
            May=thermostat_heating_week,
            June=thermostat_heating_week,
            July=thermostat_heating_week,
            August=thermostat_heating_week,
            September=thermostat_heating_week,
            October=thermostat_heating_week,
            November=thermostat_heating_week,
            December=thermostat_heating_week,
            Type="Setpoint",
        )

        thermostat_cooling_year = YearComponent(
            Name="Thermostat Cooling Year",
            January=thermostat_cooling_week,
            February=thermostat_cooling_week,
            March=thermostat_cooling_week,
            April=thermostat_cooling_week,
            May=thermostat_cooling_week,
            June=thermostat_cooling_week,
            July=thermostat_cooling_week,
            August=thermostat_cooling_week,
            September=thermostat_cooling_week,
            October=thermostat_cooling_week,
            November=thermostat_cooling_week,
            December=thermostat_cooling_week,
            Type="Setpoint",
        )

        thermostat = ThermostatComponent(
            Name="Thermostat",
            HeatingSchedule=thermostat_heating_year,
            CoolingSchedule=thermostat_cooling_year,
            HeatingSetpoint=self.HeatingSetpoint,
            CoolingSetpoint=self.CoolingSetpoint,
            IsOn=True,
        )

        lighting_day = DayComponent(
            Name="Lighting Fractional Day",
            Type="Fraction",
            Hour_00=0.7,
            Hour_01=0.3,
            Hour_02=0.1,
            Hour_03=0.1,
            Hour_04=0.1,
            Hour_05=0.3,
            Hour_06=0.3,
            Hour_07=0.1,
            Hour_08=0.1,
            Hour_09=0.1,
            Hour_10=0.1,
            Hour_11=0.1,
            Hour_12=0.1,
            Hour_13=0.1,
            Hour_14=0.1,
            Hour_15=0.4,
            Hour_16=0.7,
            Hour_17=0.8,
            Hour_18=0.9,
            Hour_19=1.0,
            Hour_20=1.0,
            Hour_21=1.0,
            Hour_22=0.9,
            Hour_23=0.8,
        )

        lighting_week = WeekComponent(
            Name="Lighting Week",
            Monday=lighting_day,
            Tuesday=lighting_day,
            Wednesday=lighting_day,
            Thursday=lighting_day,
            Friday=lighting_day,
            Saturday=lighting_day,
            Sunday=lighting_day,
        )

        lighting_year = YearComponent(
            Name="Lighting Year",
            January=lighting_week,
            February=lighting_week,
            March=lighting_week,
            April=lighting_week,
            May=lighting_week,
            June=lighting_week,
            July=lighting_week,
            August=lighting_week,
            September=lighting_week,
            October=lighting_week,
            November=lighting_week,
            December=lighting_week,
            Type="Lighting",
        )

        lighting = LightingComponent(
            Name="Lighting",
            Schedule=lighting_year,
            PowerDensity=self.LightingPowerDensity,
            DimmingType="Off",
            IsOn=True,
        )

        equipment_day = DayComponent(
            Name="equipment Fractional Day",
            Type="Fraction",
            Hour_00=0.7,
            Hour_01=0.3,
            Hour_02=0.1,
            Hour_03=0.1,
            Hour_04=0.1,
            Hour_05=0.3,
            Hour_06=0.3,
            Hour_07=0.5,
            Hour_08=0.5,
            Hour_09=0.5,
            Hour_10=0.5,
            Hour_11=0.5,
            Hour_12=0.5,
            Hour_13=0.5,
            Hour_14=0.5,
            Hour_15=0.5,
            Hour_16=0.7,
            Hour_17=0.8,
            Hour_18=0.9,
            Hour_19=0.7,
            Hour_20=0.7,
            Hour_21=0.7,
            Hour_22=0.9,
            Hour_23=0.8,
        )

        equipment_week = WeekComponent(
            Name="equipment Week",
            Monday=equipment_day,
            Tuesday=equipment_day,
            Wednesday=equipment_day,
            Thursday=equipment_day,
            Friday=equipment_day,
            Saturday=equipment_day,
            Sunday=equipment_day,
        )

        equipment_year = YearComponent(
            Name="equipment Year",
            January=equipment_week,
            February=equipment_week,
            March=equipment_week,
            April=equipment_week,
            May=equipment_week,
            June=equipment_week,
            July=equipment_week,
            August=equipment_week,
            September=equipment_week,
            October=equipment_week,
            November=equipment_week,
            December=equipment_week,
            Type="Equipment",
        )

        equipment = EquipmentComponent(
            Name="equipment",
            Schedule=equipment_year,
            PowerDensity=self.EquipmentPowerDensity,
            IsOn=True,
        )

        water_use_day = DayComponent(
            Name="water_use Fractional Day",
            Type="Fraction",
            Hour_00=0.1,
            Hour_01=0.1,
            Hour_02=0.1,
            Hour_03=0.1,
            Hour_04=0.1,
            Hour_05=0.1,
            Hour_06=0.5,
            Hour_07=0.5,
            Hour_08=0.9,
            Hour_09=0.1,
            Hour_10=0.1,
            Hour_11=0.1,
            Hour_12=0.1,
            Hour_13=0.1,
            Hour_14=0.1,
            Hour_15=0.1,
            Hour_16=0.1,
            Hour_17=0.1,
            Hour_18=0.5,
            Hour_19=0.7,
            Hour_20=0.8,
            Hour_21=0.6,
            Hour_22=0.1,
            Hour_23=0.1,
        )

        water_use_week = WeekComponent(
            Name="water_use Week",
            Monday=water_use_day,
            Tuesday=water_use_day,
            Wednesday=water_use_day,
            Thursday=water_use_day,
            Friday=water_use_day,
            Saturday=water_use_day,
            Sunday=water_use_day,
        )

        water_use_year = YearComponent(
            Name="water_use Year",
            January=water_use_week,
            February=water_use_week,
            March=water_use_week,
            April=water_use_week,
            May=water_use_week,
            June=water_use_week,
            July=water_use_week,
            August=water_use_week,
            September=water_use_week,
            October=water_use_week,
            November=water_use_week,
            December=water_use_week,
            Type="WaterUse",
        )

        water_use = WaterUseComponent(
            Name="water_use",
            Schedule=water_use_year,
            FlowRatePerPerson=self.DHWFlowRatePerPerson,
        )

        occupancy_day = DayComponent(
            Name="occupancy Fractional Day",
            Type="Fraction",
            Hour_00=1,
            Hour_01=1,
            Hour_02=1,
            Hour_03=1,
            Hour_04=1,
            Hour_05=1,
            Hour_06=0.9,
            Hour_07=0.8,
            Hour_08=0.8,
            Hour_09=0.5,
            Hour_10=0.3,
            Hour_11=0.3,
            Hour_12=0.5,
            Hour_13=0.3,
            Hour_14=0.4,
            Hour_15=0.5,
            Hour_16=0.6,
            Hour_17=0.7,
            Hour_18=0.8,
            Hour_19=1,
            Hour_20=1,
            Hour_21=1,
            Hour_22=1,
            Hour_23=1,
        )

        occupancy_week = WeekComponent(
            Name="occupancy Week",
            Monday=occupancy_day,
            Tuesday=occupancy_day,
            Wednesday=occupancy_day,
            Thursday=occupancy_day,
            Friday=occupancy_day,
            Saturday=occupancy_day,
            Sunday=occupancy_day,
        )

        occupancy_year = YearComponent(
            Name="occupancy Year",
            January=occupancy_week,
            February=occupancy_week,
            March=occupancy_week,
            April=occupancy_week,
            May=occupancy_week,
            June=occupancy_week,
            July=occupancy_week,
            August=occupancy_week,
            September=occupancy_week,
            October=occupancy_week,
            November=occupancy_week,
            December=occupancy_week,
            Type="WaterUse",
        )

        occupancy = OccupancyComponent(
            Name="occupancy",
            Schedule=occupancy_year,
            PeopleDensity=self.PeopleDensity,
            IsOn=True,
        )

        heating_system = ThermalSystemComponent(
            Name="heating_system",
            ConditioningType="Heating",
            Fuel="NaturalGas",
            SystemCOP=0.81,
            DistributionCOP=0.95,
        )

        cooling_system = ThermalSystemComponent(
            Name="cooling_system",
            ConditioningType="Cooling",
            Fuel="Electricity",
            SystemCOP=3.5,
            DistributionCOP=0.95,
        )

        conditioning_systems = ConditioningSystemsComponent(
            Name="conditioning_systems",
            Heating=heating_system,
            Cooling=cooling_system,
        )

        vent_schedule_day = DayComponent(
            Name="vent_schedule_day",
            Type="Fraction",
            Hour_00=0.5,
            Hour_01=0.5,
            Hour_02=0.5,
            Hour_03=0.5,
            Hour_04=0.5,
            Hour_05=0.5,
            Hour_06=0.5,
            Hour_07=0.5,
            Hour_08=0.5,
            Hour_09=0.5,
            Hour_10=0.5,
            Hour_11=0.5,
            Hour_12=0.5,
            Hour_13=0.5,
            Hour_14=0.5,
            Hour_15=0.5,
            Hour_16=0.5,
            Hour_17=0.5,
            Hour_18=0.5,
            Hour_19=0.5,
            Hour_20=0.5,
            Hour_21=0.5,
            Hour_22=0.5,
            Hour_23=0.5,
        )

        vent_schedule_week = WeekComponent(
            Name="vent_schedule_week",
            Monday=vent_schedule_day,
            Tuesday=vent_schedule_day,
            Wednesday=vent_schedule_day,
            Thursday=vent_schedule_day,
            Friday=vent_schedule_day,
            Saturday=vent_schedule_day,
            Sunday=vent_schedule_day,
        )

        vent_schedule_year = YearComponent(
            Name="vent_schedule_year",
            January=vent_schedule_week,
            February=vent_schedule_week,
            March=vent_schedule_week,
            April=vent_schedule_week,
            May=vent_schedule_week,
            June=vent_schedule_week,
            July=vent_schedule_week,
            August=vent_schedule_week,
            September=vent_schedule_week,
            October=vent_schedule_week,
            November=vent_schedule_week,
            December=vent_schedule_week,
            Type="Window",
        )

        ventilation_system = VentilationComponent(
            Name="ventilation_system",
            Schedule=vent_schedule_year,
            FreshAirPerFloorArea=self.VentFlowRatePerArea,
            FreshAirPerPerson=self.VentFlowRatePerPerson,
            Provider=self.VentProvider,
            HRV=self.VentHRV,
            Economizer=self.VentEconomizer,
            DCV=self.VentDCV,
        )

        dhw = DHWComponent(
            Name="dhw",
            SystemCOP=0.9,
            DistributionCOP=0.95,
            WaterTemperatureInlet=10,
            WaterSupplyTemperature=55,
            IsOn=True,
            FuelType="Electricity",
        )

        hvac = ZoneHVACComponent(
            Name="hvac",
            ConditioningSystems=conditioning_systems,
            Ventilation=ventilation_system,
        )

        space_use = ZoneSpaceUseComponent(
            Name="space_use",
            Occupancy=occupancy,
            Lighting=lighting,
            Equipment=equipment,
            WaterUse=water_use,
            Thermostat=thermostat,
        )

        operations = ZoneOperationsComponent(
            Name="operations",
            HVAC=hvac,
            SpaceUse=space_use,
            DHW=dhw,
        )

        infiltration = InfiltrationComponent(
            Name="infiltration",
            ConstantCoefficient=0.0,
            TemperatureCoefficient=0.0,
            WindVelocityCoefficient=0.0,
            WindVelocitySquaredCoefficient=0.0,
            AFNAirMassFlowCoefficientCrack=0.0,
            AirChangesPerHour=self.InfiltrationACH,
            FlowPerExteriorSurfaceArea=0.0,
            CalculationMethod="AirChanges/Hour",
            IsOn=True,
        )

        concrete = ConstructionMaterialComponent(
            Name="concrete",
            Conductivity=1.7,
            Density=2400,
            SpecificHeat=840,
            ThermalAbsorptance=0.9,
            SolarAbsorptance=0.6,
            VisibleAbsorptance=0.6,
            TemperatureCoefficientThermalConductivity=0.0,
            Roughness="MediumRough",
            Type="Concrete",
        )
        gypsum = ConstructionMaterialComponent(
            Name="gypsum",
            Conductivity=0.16,
            Density=1000,
            SpecificHeat=1000,
            ThermalAbsorptance=0.9,
            SolarAbsorptance=0.6,
            VisibleAbsorptance=0.6,
            TemperatureCoefficientThermalConductivity=0.0,
            Roughness="MediumRough",
            Type="Finishes",
        )
        xps = ConstructionMaterialComponent(
            Name="xps",
            Conductivity=0.03,
            Density=100,
            SpecificHeat=1000,
            ThermalAbsorptance=0.9,
            SolarAbsorptance=0.6,
            VisibleAbsorptance=0.6,
            TemperatureCoefficientThermalConductivity=0.0,
            Roughness="MediumRough",
            Type="Insulation",
        )
        _eps = ConstructionMaterialComponent(
            Name="eps",
            Conductivity=0.03,
            Density=100,
            SpecificHeat=1000,
            ThermalAbsorptance=0.9,
            SolarAbsorptance=0.6,
            VisibleAbsorptance=0.6,
            TemperatureCoefficientThermalConductivity=0.0,
            Roughness="MediumRough",
            Type="Insulation",
        )
        woodframing = ConstructionMaterialComponent(
            Name="woodframing",
            Conductivity=0.14,
            Density=500,
            SpecificHeat=1000,
            ThermalAbsorptance=0.9,
            SolarAbsorptance=0.6,
            VisibleAbsorptance=0.6,
            TemperatureCoefficientThermalConductivity=0.0,
            Roughness="MediumRough",
            Type="Timber",
        )
        _brick = ConstructionMaterialComponent(
            Name="brick",
            Conductivity=0.8,
            Density=1800,
            SpecificHeat=840,
            ThermalAbsorptance=0.9,
            SolarAbsorptance=0.6,
            VisibleAbsorptance=0.6,
            TemperatureCoefficientThermalConductivity=0.0,
            Roughness="MediumRough",
            Type="Masonry",
        )

        residential_wall = ConstructionAssemblyComponent(
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=woodframing,
                    Thickness=0.02,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=xps,
                    Thickness=0.05,
                    LayerOrder=1,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=gypsum,
                    Thickness=0.012,
                    LayerOrder=2,
                ),
            ],
            Type="Facade",
            Name="residential_wall",
        )
        facade_r_value_without_xps = (
            residential_wall.r_value - residential_wall.sorted_layers[1].r_value
        )
        facade_r_value_delta = self.FacadeRValue - facade_r_value_without_xps
        required_xps_thickness = xps.Conductivity * facade_r_value_delta
        if required_xps_thickness < 0.003:
            msg = f"Required XPS thickness is less than 3mm because the desired total facade R-value is {self.FacadeRValue} m²K/W but the concrete and gypsum layers already have a total R-value of {facade_r_value_without_xps} m²K/W."
            raise ValueError(msg)
        residential_wall.Layers[1].Thickness = required_xps_thickness

        residential_roof = ConstructionAssemblyComponent(
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=xps,
                    Thickness=0.019,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=concrete,
                    Thickness=0.1,
                    LayerOrder=1,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=xps,
                    Thickness=0.017,
                    LayerOrder=2,
                ),
            ],
            Type="FlatRoof",
            Name="residential_roof",
        )

        roof_r_value_without_last_xps = (
            residential_roof.r_value - residential_roof.sorted_layers[-1].r_value
        )
        roof_r_value_delta = self.RoofRValue - roof_r_value_without_last_xps
        required_xps_thickness = xps.Conductivity * roof_r_value_delta
        if required_xps_thickness < 0.003:
            msg = f"Required XPS thickness is less than 3mm because the desired total roof R-value is {self.RoofRValue} m²K/W but the concrete and XPS layers already have a total R-value of {roof_r_value_without_last_xps} m²K/W."
            raise ValueError(msg)
        residential_roof.Layers[-1].Thickness = required_xps_thickness

        residential_partition = ConstructionAssemblyComponent(
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=gypsum,
                    Thickness=0.012,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=woodframing,
                    Thickness=0.05,
                    LayerOrder=1,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=gypsum,
                    Thickness=0.012,
                    LayerOrder=2,
                ),
            ],
            Type="Partition",
            Name="residential_partition",
        )

        residential_floorceiling = ConstructionAssemblyComponent(
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=xps,
                    Thickness=0.012,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=concrete,
                    Thickness=0.1,
                    LayerOrder=1,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=xps,
                    Thickness=0.03,
                    LayerOrder=2,
                ),
            ],
            Type="FloorCeiling",
            Name="residential_floorceiling",
        )

        residential_attic_floor = residential_floorceiling.model_copy(
            deep=True, update={"Type": "AtticFloor", "Name": "residential_attic_floor"}
        )
        residential_attic_roof = residential_roof.model_copy(
            deep=True, update={"Type": "AtticRoof", "Name": "residential_attic_roof"}
        )

        residential_basement_ceiling = residential_floorceiling.model_copy(
            deep=True,
            update={"Type": "BasementCeiling", "Name": "residential_basement_ceiling"},
        )

        residential_groundslab = ConstructionAssemblyComponent(
            Layers=[
                ConstructionLayerComponent(
                    ConstructionMaterial=concrete,
                    Thickness=0.1,
                    LayerOrder=0,
                ),
                ConstructionLayerComponent(
                    ConstructionMaterial=xps,
                    Thickness=0.05,
                    LayerOrder=1,
                ),
            ],
            Type="GroundSlab",
            Name="residential_groundslab",
        )
        groundslab_r_value_without_xps = (
            residential_groundslab.r_value
            - residential_groundslab.sorted_layers[-1].r_value
        )
        groundslab_r_value_delta = self.SlabRValue - groundslab_r_value_without_xps
        required_xps_thickness = xps.Conductivity * groundslab_r_value_delta
        if required_xps_thickness < 0.003:
            msg = f"Required XPS thickness is less than 3mm because the desired total slab R-value is {self.SlabRValue} m²K/W but the concrete and XPS layers already have a total R-value of {groundslab_r_value_without_xps} m²K/W."
            raise ValueError(msg)
        residential_groundslab.Layers[-1].Thickness = required_xps_thickness

        envelope_assemblies = EnvelopeAssemblyComponent(
            Name="envelope_assemblies",
            FacadeAssembly=residential_wall,
            FlatRoofAssembly=residential_roof,
            AtticFloorAssembly=residential_attic_floor,
            AtticRoofAssembly=residential_attic_roof,
            FloorCeilingAssembly=residential_floorceiling,
            PartitionAssembly=residential_partition,
            GroundSlabAssembly=residential_groundslab,
            BasementCeilingAssembly=residential_basement_ceiling,
            ExternalFloorAssembly=residential_groundslab,
            GroundWallAssembly=residential_groundslab,
            InternalMassAssembly=None,
            InternalMassExposedAreaPerArea=None,
        )

        window_assembly = GlazingConstructionSimpleComponent(
            Name="window_assembly",
            UValue=self.WindowUValue,
            SHGF=self.WindowSHGF,
            TVis=self.WindowTVis,
            Type="Single",
        )

        envelope = ZoneEnvelopeComponent(
            Name="envelope",
            Assemblies=envelope_assemblies,
            Window=window_assembly,
            Infiltration=infiltration,
            AtticInfiltration=infiltration,
            BasementInfiltration=infiltration,
        )

        zone = ZoneComponent(
            Name="zone",
            Envelope=envelope,
            Operations=operations,
        )
        return zone

    def to_model(self) -> Model:
        """Convert the parameters to a model after creating a zone component."""
        zone = self.to_zone()
        zoning = "core/perim" if self.width > 15 and self.depth > 15 else "by_storey"
        geometry = ShoeboxGeometry(
            x=0,
            y=0,
            w=self.width,
            d=self.depth,
            h=self.f2f_height,
            num_stories=self.num_stories,
            zoning=zoning,
            roof_height=None,
            basement=False,
            wwr=self.WWR,
            perim_depth=3,
        )
        return Model(
            Zone=zone,
            geometry=geometry,
            Attic=AtticAssumptions(
                Conditioned=False,
                UseFraction=None,
            ),
            Basement=BasementAssumptions(
                Conditioned=False,
                UseFraction=None,
            ),
            Weather=self.weather_url,  # pyright: ignore [reportArgumentType]
        )


# TODO:Material defintions

# TODO: check the weather file - can we use the ground temperature to adjust to the water inlet?
if __name__ == "__main__":
    weather_url = "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/MA_Massachusetts/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.zip"
    params = FlatParameters(
        CoolingSetpoint=24,
        HeatingSetpoint=20,
        EquipmentPowerDensity=4.7,
        LightingPowerDensity=2.6,
        PeopleDensity=0.016,
        VentFlowRatePerPerson=0,
        VentFlowRatePerArea=0,
        VentProvider="Mechanical",
        VentHRV="Sensible",
        VentDCV="NoDCV",
        VentEconomizer="NoEconomizer",
        DHWFlowRatePerPerson=0.052,
        InfiltrationACH=0.2,
        WindowUValue=1.493,
        WindowSHGF=0.373,
        WindowTVis=0.769,
        FacadeRValue=3,
        RoofRValue=3,
        SlabRValue=3,
        WWR=0.25,
        f2f_height=3.5,
        num_stories=20,
        width=10,
        depth=15,
        weather_url=weather_url,
    )
    # Test types:
    # 1. Mechanical but no ventilation flow rates but change the envelope
    # 2. Mechanical with ventilation flow rates

    model = params.to_model()

    result = model.run()
    doc, results, err_text = (result.doc, result.energy_and_peak, result.err_text)
    save_idf(doc, "model.idf")
    results.to_csv("results.csv")
    agg_results = results.groupby(["Meter", "Aggregation"]).sum()
    # summarize the results by meter column across all timesteps
    print(results.groupby(["Meter", "Aggregation"]).sum())
    print("Total EUI:", results.groupby(["Aggregation"]).sum())
