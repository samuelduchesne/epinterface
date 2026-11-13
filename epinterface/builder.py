"""A simple model for automatically constructing a shoebox building energy model."""

import logging
from pathlib import Path

import pandas as pd
from idfkit import IDFDocument, load_idf

from epinterface.ddy_injector_bayes import DDYSizingSpec
from epinterface.document import (
    add_construction,
    add_or_replace,
    field_name,
    minimal_document,
)
from epinterface.geometry import ShoeboxGeometry
from epinterface.interface import (
    DefaultMaterialLibrary,
    add_constant_schedule,
    add_zone_list,
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
        idf = minimal_document(version)
        ddy = load_idf(str(ddy_path), version=version)
        ddyspec = DDYSizingSpec(match=True)
        ddyspec.inject_ddy(idf, ddy)

        # Configure simulation
        add_or_replace(
            idf,
            "SimulationControl",
            do_zone_sizing_calculation="Yes",
            do_system_sizing_calculation="Yes",
            # The model has no plant loops; plant sizing would require Sizing:Plant.
            do_plant_sizing_calculation="No",
            run_simulation_for_sizing_periods="Yes",
            run_simulation_for_weather_file_run_periods="Yes",
            do_hvac_sizing_simulation_for_sizing_periods="Yes",
            maximum_number_of_hvac_sizing_simulation_passes=1,
        )

        # Configure run period
        add_or_replace(
            idf,
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

        # configure timestep
        add_or_replace(idf, "Timestep", number_of_timesteps_per_hour=self.timestep)

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

        add_or_replace(
            idf,
            "WindowMaterial:SimpleGlazingSystem",
            "DefaultGlazing",
            u_factor=self.WindowU,
            solar_heat_gain_coefficient=self.WindowSHGC,
            visible_transmittance=0.7,
        )
        add_construction(idf, "Project External Window", ["DefaultGlazing"])

        # Handle Wall Constructions
        wall_layers = [
            (material_lib.stucco, 0.03),
            (material_lib.insulation, 0.15),
            (material_lib.gypsum, 0.02),
        ]
        wall_construction = add_construction(
            idf,
            "Project Wall",
            [
                material.add_layer_to_idf(idf, thickness).name
                for material, thickness in wall_layers
            ],
        )
        for surface in idf["BuildingSurface:Detailed"]:
            if (surface.surface_type or "").lower() == "wall" and (
                surface.outside_boundary_condition or ""
            ).lower() == "outdoors":
                surface.construction_name = wall_construction.name

        # TODO: handle other constructions.

        # Handle Zone List
        zone_names = [
            zone.name for zone in idf["Zone"] if "attic" not in zone.name.lower()
        ]
        zone_list = add_zone_list(idf, "Conditioned_Zones", zone_names)

        # Handle HVAC
        thermostat = add_or_replace(
            idf,
            "HVACTemplate:Thermostat",
            "Thermostat",
            constant_heating_setpoint=self.HeatingSetpoint,
            constant_cooling_setpoint=self.CoolingSetpoint,
        )
        for zone in idf["Zone"]:
            zone_name = zone.name
            if "attic" in zone_name.lower():
                continue
            add_or_replace(
                idf,
                "HVACTemplate:Zone:IdealLoadsAirSystem",
                "",
                zone_name=zone_name,
                template_thermostat_name=thermostat.name,
                maximum_heating_supply_air_temperature=30.0,
                minimum_cooling_supply_air_temperature=18.0,
                maximum_heating_supply_air_humidity_ratio=0.0156,
                minimum_cooling_supply_air_humidity_ratio=0.0077,
                heating_limit="NoLimit",
                cooling_limit="NoLimit",
                dehumidification_control_type="None",
                cooling_sensible_heat_ratio=0.7,
                dehumidification_setpoint=60.0,
                humidification_control_type="None",
                humidification_setpoint=30.0,
                outdoor_air_method="None",
                outdoor_air_flow_rate_per_person=0.00944,
                outdoor_air_flow_rate_per_zone_floor_area=0.00025,
                outdoor_air_flow_rate_per_zone=0.0,
                demand_controlled_ventilation_type="None",
                outdoor_air_economizer_type="NoEconomizer",
                heat_recovery_type="None",
                sensible_heat_recovery_effectiveness=0.7,
                latent_heat_recovery_effectiveness=0.65,
            )

        # Handle People
        occ_sched = add_values_schedule(
            idf,
            "Occupancy_sch",
            schedules.Occupancy.values.tolist(),
            type_limits="Fraction",
        )
        ensure_fraction_type_limits(idf)
        add_or_replace(
            idf,
            "ScheduleTypeLimits",
            "any number",
            numeric_type="Continuous",
            unit_type="Dimensionless",
        )
        acti_year = add_values_schedule(
            idf,
            "Activity_Schedule",
            [117.28] * HOURS_PER_YEAR,
            type_limits="any number",
        )
        add_or_replace(
            idf,
            "People",
            "People",
            zone_or_zonelist_or_space_or_spacelist_name=zone_list.name,
            number_of_people_schedule_name=occ_sched.name,
            number_of_people_calculation_method="People/Area",
            people_per_floor_area=self.PeopleDensity,
            fraction_radiant=0.3,
            sensible_heat_fraction="autocalculate",
            activity_level_schedule_name=acti_year.name,
            enable_ashrae_55_comfort_warnings="No",
        )

        # Handle Infiltration
        add_or_replace(
            idf,
            "ZoneInfiltration:DesignFlowRate",
            "Infiltration",
            zone_or_zonelist_or_space_or_spacelist_name=zone_list.name,
            schedule_name=always_on_name,
            design_flow_rate_calculation_method="AirChanges/Hour",
            flow_rate_per_exterior_surface_area=self.Infiltration,
            constant_term_coefficient=1.0,
            temperature_term_coefficient=0.0,
            velocity_term_coefficient=0.0,
            velocity_squared_term_coefficient=0.0,
        )

        def watts_per_area(obj_type: str) -> str:
            return field_name(
                idf, obj_type, "watts_per_floor_area", "watts_per_zone_floor_area"
            )

        # Handle Equipment
        equip_sched = add_values_schedule(
            idf,
            "Equipment_sch",
            schedules.Equipment.values.tolist(),
            type_limits="Fraction",
        )
        add_or_replace(
            idf,
            "ElectricEquipment",
            "Equipment",
            zone_or_zonelist_or_space_or_spacelist_name=zone_list.name,
            schedule_name=equip_sched.name,
            design_level_calculation_method="Watts/Area",
            **{watts_per_area("ElectricEquipment"): self.EPD},
            fraction_latent=0.0,
            fraction_radiant=0.2,
            fraction_lost=0.0,
        )

        # Handle Lights
        lights_sched = add_values_schedule(
            idf,
            "Lights_sch",
            schedules.Lights.values.tolist(),
            type_limits="Fraction",
        )
        add_or_replace(
            idf,
            "Lights",
            "Lights",
            zone_or_zonelist_or_space_or_spacelist_name=zone_list.name,
            schedule_name=lights_sched.name,
            design_level_calculation_method="Watts/Area",
            **{watts_per_area("Lights"): self.LPD},
            return_air_fraction=0.0,
            fraction_radiant=0.42,
            fraction_visible=0.18,
            fraction_replaceable=1.0,
        )

        # TODO: water use (no heater is provided, so only the flow rate matters).

        # TODO: should we be using a slab processor?

        return idf
