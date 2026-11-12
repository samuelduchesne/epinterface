"""A simple model for automatically constructing a shoebox building energy model."""

import logging
from pathlib import Path

import pandas as pd
from idfkit import IDFDocument

from epinterface.data import EnergyPlusArtifactDir
from epinterface.ddy_injector_bayes import DDYSizingSpec
from epinterface.document import load_base_document
from epinterface.geometry import ShoeboxGeometry
from epinterface.interface import (
    Construction,
    DefaultMaterialLibrary,
    ElectricEquipment,
    HVACTemplateThermostat,
    HVACTemplateZoneIdealLoadsAirSystem,
    Lights,
    People,
    RunPeriod,
    ScheduleTypeLimits,
    SimpleGlazingMaterial,
    SimulationControl,
    Timestep,
    ZoneInfiltrationDesignFlowRate,
    ZoneList,
    add_constant_schedule,
    ensure_fraction_type_limits,
)
from epinterface.schedules import HOURS_PER_YEAR, add_values_schedule
from epinterface.settings import energyplus_settings
from epinterface.weather import BaseWeather

logger = logging.getLogger(__name__)


class SimpleResidentialModel(BaseWeather, extra="allow"):
    """A simple model for automatically constructing a shoebox building energy model."""

    EPD: float = 9.0
    LPD: float = 4.0
    WWR: float = 0.15
    WindowU: float = 2.7
    WindowSHGC: float = 0.763
    HeatingSetpoint: float = 19
    CoolingSetpoint: float = 24
    PeopleDensity: float = 0.05
    Infiltration: float = 0.1
    timestep: int = 6

    def build(
        self, output_dir: Path | str, weather_cache_dir: Path | str | None = None
    ) -> IDFDocument:
        """Build the energy model.

        Args:
            output_dir (Path | str): The directory to save the IDF file.
            weather_cache_dir (Path | str | None): The directory to cache the weather files.

        Returns:
            IDFDocument: The constructed IDF model.
        """
        if isinstance(output_dir, str):
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        material_lib = DefaultMaterialLibrary()
        weather_cache_dir = Path(weather_cache_dir) if weather_cache_dir else output_dir
        _epw_path, ddy_path = self.fetch_weather(weather_cache_dir)
        schedules = pd.read_parquet(
            Path(__file__).parent / "data" / "res_schedules.parquet"
        )

        version = energyplus_settings.version_tuple
        idf = load_base_document(EnergyPlusArtifactDir / "Minimal.idf", version)
        ddy = load_base_document(ddy_path, version)
        ddyspec = DDYSizingSpec(match=True)
        ddyspec.inject_ddy(idf, ddy)

        # Configure simulation
        sim_control = SimulationControl(
            Do_Zone_Sizing_Calculation="Yes",
            Do_System_Sizing_Calculation="Yes",
            Do_Plant_Sizing_Calculation="Yes",
            Run_Simulation_for_Sizing_Periods="Yes",
            Run_Simulation_for_Weather_File_Run_Periods="Yes",
            Do_HVAC_Sizing_Simulation_for_Sizing_Periods="Yes",
        )
        sim_control.add(idf)

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
        run_period.add(idf)

        # configure timestep
        timestep = Timestep(
            Number_of_Timesteps_per_Hour=self.timestep,
        )
        timestep.add(idf)

        # create constant scheds
        for on_name, off_name in (
            ("Always_On", "Always_Off"),
            ("Always On", "Always Off"),
            ("On", "Off"),
        ):
            add_constant_schedule(idf, on_name, 1)
            add_constant_schedule(idf, off_name, 0)
        always_on_name = "On"

        # Handle Geometry
        zone_dims = ShoeboxGeometry(
            x=0,
            y=0,
            w=10,
            d=10,
            h=3,
            num_stories=3,
            roof_height=2.5,
            basement=False,
            wwr=0.15,
            zoning="by_storey",
        )
        idf = zone_dims.add(idf)

        window_construction = Construction(
            name="Project External Window",
            layers=[
                SimpleGlazingMaterial(
                    Name="DefaultGlazing",
                    Solar_Heat_Gain_Coefficient=self.WindowSHGC,
                    UFactor=self.WindowU,
                    Visible_Transmittance=0.7,
                )
            ],
        )
        window_construction.add(idf)

        # Handle Wall Constructions
        wall_construction = Construction(
            name="Project Wall",
            layers=[
                material_lib.stucco.as_layer(thickness=0.03),
                material_lib.insulation.as_layer(thickness=0.15),
                material_lib.gypsum.as_layer(thickness=0.02),
            ],
        )
        wall_construction.add(idf)
        for surface in idf["BuildingSurface:Detailed"]:
            if (
                surface.surface_type.lower() == "wall"
                and surface.outside_boundary_condition.lower() == "outdoors"
            ):
                surface.construction_name = wall_construction.name

        # Handle Roof Constructions
        # roof_construction = Construction(
        #     name="Project Flat Roof",
        #     layers=[
        #         material_lib.stucco.as_layer(thickness=0.03),
        #         material_lib.insulation.as_layer(thickness=0.15),
        #         material_lib.gypsum.as_layer(thickness=0.02),
        #     ],
        # )
        # roof_construction.add(idf)

        # TODO: handle other constructions.

        # Handle Zone List
        zone_names = [
            zone.name for zone in idf["Zone"] if "attic" not in zone.name.lower()
        ]
        zone_list = ZoneList(Name="Conditioned_Zones", Names=zone_names)
        zone_list.add(idf)

        # Handle HVAC
        thermostat = HVACTemplateThermostat(
            Name="Thermostat",
            Constant_Heating_Setpoint=self.HeatingSetpoint,
            Constant_Cooling_Setpoint=self.CoolingSetpoint,
        )
        thermostat.add(idf)
        for zone in idf["Zone"]:
            zone_name = zone.name
            if "attic" in zone_name.lower():
                continue
            hvac_template = HVACTemplateZoneIdealLoadsAirSystem(
                Zone_Name=zone_name,
                Template_Thermostat_Name=thermostat.Name,
            )
            idf = hvac_template.add(idf)

        # Handle People
        occ_sched = add_values_schedule(
            idf,
            "Occupancy_sch",
            schedules.Occupancy.values.tolist(),
            type_limits="Fraction",
        )
        ensure_fraction_type_limits(idf)
        ScheduleTypeLimits(
            Name="any number", Numeric_Type="Continuous", Unit_Type="Dimensionless"
        ).add(idf)
        acti_year = add_values_schedule(
            idf,
            "Activity_Schedule",
            [117.28] * HOURS_PER_YEAR,
            type_limits="any number",
        )
        people = People(
            Name="People",
            Zone_or_ZoneList_Name=zone_list.Name,
            Number_of_People_Schedule_Name=occ_sched.name,
            Activity_Level_Schedule_Name=acti_year.name,
            Number_of_People_Calculation_Method="People/Area",
            People_per_Floor_Area=self.PeopleDensity,
        )
        people.add(idf)

        # Handle Infiltration
        infiltration = ZoneInfiltrationDesignFlowRate(
            Name="Infiltration",
            Zone_or_ZoneList_Name=zone_list.Name,
            Schedule_Name=always_on_name,
            Design_Flow_Rate_Calculation_Method="AirChanges/Hour",
            Flow_Rate_per_Exterior_Surface_Area=self.Infiltration,
        )
        infiltration.add(idf)

        # Handle Equipment
        equip_sched = add_values_schedule(
            idf,
            "Equipment_sch",
            schedules.Equipment.values.tolist(),
            type_limits="Fraction",
        )
        equipment = ElectricEquipment(
            Name="Equipment",
            Zone_or_ZoneList_Name=zone_list.Name,
            Schedule_Name=equip_sched.name,
            Design_Level_Calculation_Method="Watts/Area",
            Watts_per_Zone_Floor_Area=self.EPD,
        )
        equipment.add(idf)

        # Handle Lights
        lights_sched = add_values_schedule(
            idf,
            "Lights_sch",
            schedules.Lights.values.tolist(),
            type_limits="Fraction",
        )
        lights = Lights(
            Name="Lights",
            Zone_or_ZoneList_Name=zone_list.Name,
            Schedule_Name=lights_sched.name,
            Design_Level_Calculation_Method="Watts/Area",
            Watts_per_Zone_Floor_Area=self.LPD,
        )
        lights.add(idf)

        # Handle Water
        # TODO: energy only changes with flow rate because no heater is provided.
        # water_flow_sch, *_ = Schedule.constant_schedule(Name="Water_Flow", value=0.1).to_year_week_day()
        # water_flow_sch.to_epbunch(idf)
        # target_temp_sch, *_ = Schedule.constant_schedule(Name="Target_Temperature", value=10, Type="Temperature").to_year_week_day()
        # target_temp_sch.to_epbunch(idf)
        # water = WaterUseEquipment(
        #     Name="DHW",
        #     Peak_Flow_Rate=0.0001,
        #     Flow_Rate_Fraction_Schedule_Name=water_flow_sch.Name,
        #     Hot_Water_Supply_Temperature_Schedule_Name=target_temp_sch.Name,
        #     # Zone_Name=
        #     # Latent_Fraction_Schedule_Name=
        #     # Sensible_Fraction_Schedule_Name=
        # )
        # water.add(idf)

        # TODO: should we be using a slab processor?

        return idf
