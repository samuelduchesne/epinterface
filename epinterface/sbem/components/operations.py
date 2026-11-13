"""Operations components for the SBEM library."""

from logging import getLogger

from idfkit import IDFDocument, IDFObject

from epinterface.constants import assumed_constants
from epinterface.document import add_or_replace
from epinterface.geometry import get_zone_floor_area, get_zone_glazed_area
from epinterface.interface import add_constant_schedule
from epinterface.sbem.common import MetadataMixin, NamedObject
from epinterface.sbem.components.space_use import ZoneSpaceUseComponent
from epinterface.sbem.components.systems import DHWComponent, ZoneHVACComponent
from epinterface.schedules import add_day_hourly_schedule

logger = getLogger(__name__)


class ZoneOperationsComponent(
    NamedObject,
    MetadataMixin,
    extra="forbid",
):
    """Zone use consolidation across space use, HVAC, DHW."""

    SpaceUse: ZoneSpaceUseComponent
    HVAC: ZoneHVACComponent
    DHW: DHWComponent

    def add_water_use_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str
    ) -> IDFDocument:
        """Handle adding water use to the zone based on both DHW and Operations.SpaceUse.WaterUse.

        We choose to execute this from the zone component interface because it requires context from both
        zone.Operations.SpaceUse.WaterUse and zone.Operations.

        Note: the water use component's flow rate represents the total amount of water used per person per day;
        in order to calculate a peak flow rate, we will need to ensure that the product of the schedule and the peak
        flow rate would resolve to the same daily average value per person.

        This will be responsible for:
            1. Extracting the total area of the zone by finding the matching surfaces.
            2. Computing the total number of people in the zone based on the occupancy density and the total area.
            3. Computing the average flow rate of water use/s in the zone based on the flow rate per person/day and the total number of people.
            4. Computing the peak flow rate of water use/s in the zone based on the average flow rate and the average fractional value of the schedule.
            5. Adding the water use equipment to the zone.


        # TODO: major problem - this assumes the zone has already been correctly sized!
        # this method should only actually be called AFTER
        # the building has been properly rescaled, which currently is executed at the very end.
        # that hook should probably be moved up.

        Args:
            doc (IDFDocument): The IDF document to add the operations to.
            target_zone_name (str): The name of the zone to add the operations to.

        Returns:
            doc (IDFDocument): The updated IDF document.
        """
        # TODO: should IsOn definitely live in DHW? should dhw be nullable?
        # should it live in spaceuse.wateruse for consistency?
        if not self.DHW.IsOn:
            return doc

        # Acquire the relevant data fields
        flow_rate_per_person_per_day = (
            self.SpaceUse.WaterUse.FlowRatePerPerson
        )  # m3/person/day
        occupant_density = self.SpaceUse.Occupancy.PeopleDensity  # ppl/m2
        water_supply_temperature = self.DHW.WaterSupplyTemperature  # degC
        water_temperature_inlet = self.DHW.WaterTemperatureInlet  # degC
        water_use_frac_sched = self.SpaceUse.WaterUse.Schedule
        water_use_name = f"{target_zone_name}_{self.SpaceUse.WaterUse.safe_name}_{self.DHW.safe_name}_WATER"

        # determine zone area to then compute total people
        # we will do this by finding all matching surfaces and computing their areas.
        zone = doc["Zone"].get(target_zone_name)
        if zone is None:
            raise ValueError(f"NO_ZONE:{target_zone_name}")
        area = get_zone_floor_area(doc, zone.name)
        total_ppl = occupant_density * area

        # Compute final flow rates.
        total_flow_per_day = flow_rate_per_person_per_day * total_ppl  # m3/day
        avg_flow_per_s = total_flow_per_day / (3600 * 24)  # m3/s
        # TODO: Update this rather than being constant rate

        if "Temperature" not in doc["ScheduleTypeLimits"]:
            add_or_replace(
                doc,
                "ScheduleTypeLimits",
                "Temperature",
                lower_limit_value=-100.0,
                upper_limit_value=100.0,
                numeric_type="Continuous",
                unit_type="Dimensionless",
            )

        # TODO: should we be using time-varying temperatures?
        target_temperature_yr_schedule = add_constant_schedule(
            doc,
            f"{water_use_name}_TargetWaterTemperatureSch",
            water_supply_temperature,
            "Temperature",
        )
        inlet_temperature_yr_schedule = add_constant_schedule(
            doc,
            f"{water_use_name}_InletWaterTemperatureSch",
            water_temperature_inlet,
            "Temperature",
        )

        if water_use_frac_sched.schedule_type_limits != "Fraction":
            msg = f"WATER_USE_FRACTION_SCHEDULE_TYPE_NOT_FRACTION:{water_use_name}"
            raise ValueError(msg)

        doc, water_use_frac_sch_name = water_use_frac_sched.add_year_to_idf(
            doc, name_prefix=None
        )
        # sch_obj = doc["Schedule:Year"][water_use_frac_sch_name]
        # arch_sch = Schedule.from_epbunch(sch_obj)
        # values = np.array(arch_sch.Values)
        # avg_fractional_value = np.sum(values) / 8760
        logger.warning("USING HARDCODED 2018 to compute avg fractional value")
        avg_fractional_value = water_use_frac_sched.fractional_year_sum(2018)
        # total_fractional_value * peak_flow_rate_per_s = avg_float_per_s
        peak_flow_rate_per_s = avg_flow_per_s / avg_fractional_value

        add_or_replace(
            doc,
            "WaterUse:Equipment",
            water_use_name,
            end_use_subcategory="Domestic Hot Water",
            peak_flow_rate=float(peak_flow_rate_per_s),
            flow_rate_fraction_schedule_name=water_use_frac_sch_name,
            target_temperature_schedule_name=target_temperature_yr_schedule.name,
            hot_water_supply_temperature_schedule_name=target_temperature_yr_schedule.name,
            cold_water_supply_temperature_schedule_name=inlet_temperature_yr_schedule.name,
            zone_name=target_zone_name,
        )
        return doc

    def add_thermostat_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str
    ) -> IDFObject:
        """Add a thermostat to the zone.

        Args:
            doc (IDFDocument): The IDF document to add the thermostat to.
            target_zone_name (str): The name of the zone to add the thermostat to.

        Returns:
            thermostat (IDFObject): The `HVACTemplate:Thermostat` object.
        """
        thermostat_name = (
            f"{target_zone_name}_{self.SpaceUse.Thermostat.safe_name}_THERMOSTAT"
        )
        heating_schedule = self.SpaceUse.Thermostat.HeatingSchedule
        cooling_schedule = self.SpaceUse.Thermostat.CoolingSchedule

        heating_schedule_name = None
        cooling_schedule_name = None
        if heating_schedule is not None:
            _, heat_high = self.SpaceUse.Thermostat.HeatingSchedule.bounds
            heating_design_day_name = f"{thermostat_name}_HeatingDesignDay"
            add_day_hourly_schedule(
                doc, heating_design_day_name, "Temperature", [heat_high] * 24
            )
            doc, heating_schedule_name = heating_schedule.add_year_to_idf(
                doc,
                name_prefix=None,
                winter_design_day_sch_name=heating_design_day_name,
                summer_design_day_sch_name=heating_design_day_name,
            )
        if cooling_schedule is not None:
            cool_low, _ = self.SpaceUse.Thermostat.CoolingSchedule.bounds
            cooling_design_day_name = f"{thermostat_name}_CoolingDesignDay"
            add_day_hourly_schedule(
                doc, cooling_design_day_name, "Temperature", [cool_low] * 24
            )
            doc, cooling_schedule_name = cooling_schedule.add_year_to_idf(
                doc,
                name_prefix=None,
                winter_design_day_sch_name=cooling_design_day_name,
                summer_design_day_sch_name=cooling_design_day_name,
            )

        return add_or_replace(
            doc,
            "HVACTemplate:Thermostat",
            thermostat_name,
            heating_setpoint_schedule_name=heating_schedule_name,
            constant_heating_setpoint=self.SpaceUse.Thermostat.HeatingSetpoint
            if self.SpaceUse.Thermostat.HeatingSchedule is None
            else None,
            cooling_setpoint_schedule_name=cooling_schedule_name,
            constant_cooling_setpoint=self.SpaceUse.Thermostat.CoolingSetpoint
            if self.SpaceUse.Thermostat.CoolingSchedule is None
            else None,
        )

    def add_conditioning_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str
    ) -> IDFDocument:
        """Add conditioning to an IDF zone."""
        thermostat = self.add_thermostat_to_idf_zone(doc, target_zone_name)
        if self.HVAC.Ventilation.DCV != "NoDCV":
            # check the design spec outdoor air for the DCV
            raise NotImplementedError("DCV not implemented.")
        # The template has no name, so it is always added (never reused).
        add_or_replace(
            doc,
            "HVACTemplate:Zone:IdealLoadsAirSystem",
            "",
            zone_name=target_zone_name,
            template_thermostat_name=thermostat.name,
            maximum_heating_supply_air_temperature=30.0,
            minimum_cooling_supply_air_temperature=13.0,
            maximum_heating_supply_air_humidity_ratio=0.0156,
            minimum_cooling_supply_air_humidity_ratio=0.0077,
            heating_limit="LimitFlowRateAndCapacity",
            maximum_heating_air_flow_rate="autosize",
            maximum_sensible_heating_capacity="autosize",
            cooling_limit="LimitFlowRateAndCapacity",
            maximum_cooling_air_flow_rate="autosize",
            maximum_total_cooling_capacity="autosize",
            heating_availability_schedule_name=None
            if self.HVAC.ConditioningSystems.Heating
            else "AlwaysOff",
            cooling_availability_schedule_name=None
            if self.HVAC.ConditioningSystems.Cooling
            else "AlwaysOff",
            dehumidification_control_type="None",
            cooling_sensible_heat_ratio=0.7,
            dehumidification_setpoint=60.0,
            humidification_control_type="None",
            humidification_setpoint=30.0,
            outdoor_air_method="Sum"
            if self.HVAC.Ventilation.Provider == "Mechanical"
            or self.HVAC.Ventilation.Provider == "Both"
            else "None",
            outdoor_air_flow_rate_per_person=self.HVAC.Ventilation.FreshAirPerPerson,
            outdoor_air_flow_rate_per_zone_floor_area=self.HVAC.Ventilation.FreshAirPerFloorArea,
            outdoor_air_flow_rate_per_zone=0.0,
            demand_controlled_ventilation_type="None"
            if self.HVAC.Ventilation.DCV == "NoDCV"
            else self.HVAC.Ventilation.DCV,
            outdoor_air_economizer_type=self.HVAC.Ventilation.Economizer,
            heat_recovery_type="None"
            if self.HVAC.Ventilation.HRV == "NoHRV"
            else self.HVAC.Ventilation.HRV,
            sensible_heat_recovery_effectiveness=assumed_constants.Sensible_Heat_Recovery_Effectiveness,
            latent_heat_recovery_effectiveness=assumed_constants.Latent_Heat_Recovery_Effectiveness,
        )

        if self.HVAC.Ventilation.Provider == "Natural":
            # total_window_area = calculate_window_area_for_zone(doc, target_zone_name)
            total_window_area = get_zone_glazed_area(doc, target_zone_name)

            if total_window_area == 0:
                logger.warning(
                    f"No windows found for natural ventilation in zone {target_zone_name}"
                )
                return doc
            vent_wind_stack_name = f"{target_zone_name}_{self.SpaceUse.Thermostat.safe_name}_{self.HVAC.Ventilation.safe_name}_VENTILATION_WIND_AND_STACK_OPEN_AREA"

            doc, vent_wind_stack_name_sch = (
                self.HVAC.Ventilation.Schedule.add_year_to_idf(
                    doc,
                    name_prefix=None,
                    summer_design_day_sch_name="d_AllOff_00",
                    winter_design_day_sch_name="d_AllOff_00",
                )
            )
            add_or_replace(
                doc,
                "ZoneVentilation:WindandStackOpenArea",
                vent_wind_stack_name,
                zone_or_space_name=target_zone_name,
                opening_area=float(total_window_area),
                opening_area_fraction_schedule_name=vent_wind_stack_name_sch,
                opening_effectiveness="AutoCalculate",
                effective_angle=0.0,
                height_difference=0.0,
                discharge_coefficient_for_opening="AutoCalculate",
                delta_temperature=2.0,
                minimum_outdoor_temperature=12.0,
                maximum_outdoor_temperature=25.0,
                maximum_wind_speed=40.0,
            )

        return doc
