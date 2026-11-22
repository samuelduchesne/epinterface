"""Operations components for the SBEM library."""

import re
from logging import getLogger
from typing import TYPE_CHECKING

from idfkit.geometry import get_surface_coords

from epinterface.document import EPDocument, add_or_replace
from epinterface.geometry import (
    get_zone_floor_area,
    get_zone_glazed_area,
    get_zone_windows,
)
from epinterface.interface import add_constant_schedule, add_ideal_loads_template
from epinterface.sbem.common import MetadataMixin, NamedObject
from epinterface.sbem.components.space_use import ZoneSpaceUseComponent
from epinterface.sbem.components.systems import DHWComponent, ZoneHVACComponent
from epinterface.schedules import add_day_hourly_schedule

if TYPE_CHECKING:
    # The object classes exist only in idfkit's stubs.
    from idfkit.document import AnyHVACTemplateThermostat

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
        self, doc: EPDocument, target_zone_name: str
    ) -> EPDocument:
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
            doc (EPDocument): The IDF document to add the operations to.
            target_zone_name (str): The name of the zone to add the operations to.

        Returns:
            doc (EPDocument): The updated IDF document.
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
                doc["ScheduleTypeLimits"].add,
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
            doc["WaterUse:Equipment"].add,
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
        self, doc: EPDocument, target_zone_name: str
    ) -> "AnyHVACTemplateThermostat":
        """Add a thermostat to the zone.

        Args:
            doc (EPDocument): The IDF document to add the thermostat to.
            target_zone_name (str): The name of the zone to add the thermostat to.

        Returns:
            thermostat (AnyHVACTemplateThermostat): The `HVACTemplate:Thermostat` object.
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
            doc["HVACTemplate:Thermostat"].add,
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
        self, doc: EPDocument, target_zone_name: str
    ) -> EPDocument:
        """Add conditioning to an IDF zone."""
        thermostat = self.add_thermostat_to_idf_zone(doc, target_zone_name)
        if self.HVAC.Ventilation.DCV != "NoDCV":
            # check the design spec outdoor air for the DCV
            raise NotImplementedError("DCV not implemented.")
        outdoor_air_method, outdoor_air_object = self._outdoor_air_specification(
            doc, target_zone_name
        )
        add_ideal_loads_template(
            doc,
            target_zone_name,
            thermostat.name,
            maximum_heating_supply_air_temperature=self.HVAC.ConditioningSystems.MaximumHeatingSupplyAirTemperature,
            minimum_cooling_supply_air_temperature=self.HVAC.ConditioningSystems.MinimumCoolingSupplyAirTemperature,
            **self._ideal_loads_limits(doc, target_zone_name),
            heating_availability_schedule_name=None
            if self.HVAC.ConditioningSystems.Heating
            else "AlwaysOff",
            cooling_availability_schedule_name=None
            if self.HVAC.ConditioningSystems.Cooling
            else "AlwaysOff",
            outdoor_air_method=outdoor_air_method,
            design_specification_outdoor_air_object_name=outdoor_air_object,
            outdoor_air_flow_rate_per_person=self.HVAC.Ventilation.FreshAirPerPerson,
            outdoor_air_flow_rate_per_zone_floor_area=self.HVAC.Ventilation.FreshAirPerFloorArea,
            demand_controlled_ventilation_type="None"
            if self.HVAC.Ventilation.DCV == "NoDCV"
            else self.HVAC.Ventilation.DCV,
            outdoor_air_economizer_type=self.HVAC.Ventilation.Economizer,
            heat_recovery_type="None"
            if self.HVAC.Ventilation.HRV == "NoHRV"
            else self.HVAC.Ventilation.HRV,
            sensible_heat_recovery_effectiveness=self.HVAC.Ventilation.sensible_heat_recovery_effectiveness,
            latent_heat_recovery_effectiveness=self.HVAC.Ventilation.latent_heat_recovery_effectiveness,
        )

        if self.HVAC.Ventilation.Provider in ("Natural", "Both"):
            doc = self.add_natural_ventilation_to_idf_zone(doc, target_zone_name)
        if self.HVAC.Ventilation.IsScheduledVentilationOn:
            doc = self.add_scheduled_ventilation_to_idf_zone(doc, target_zone_name)

        return doc

    def _ideal_loads_limits(
        self, doc: EPDocument, target_zone_name: str
    ) -> dict[str, str | float]:
        """The ideal loads' heating and cooling limits for a zone.

        The limits per floor area are multiplied by the zone's floor area; an
        unset one is autosized.

        Returns:
            fields (dict[str, str | float]): The template's limit fields.
        """
        systems = self.HVAC.ConditioningSystems
        per_area = (
            systems.MaxHeatingFlowPerFloorArea,
            systems.MaxCoolingFlowPerFloorArea,
            systems.MaxHeatingCapacityPerFloorArea,
            systems.MaxCoolingCapacityPerFloorArea,
        )
        area = (
            get_zone_floor_area(doc, target_zone_name)
            if any(v is not None for v in per_area)
            else 0.0
        )

        def limit(value: float | None) -> str | float:
            return "autosize" if value is None else float(value * area)

        return {
            "heating_limit": systems.HeatingLimitType,
            "maximum_heating_air_flow_rate": limit(per_area[0]),
            "maximum_sensible_heating_capacity": limit(per_area[2]),
            "cooling_limit": systems.CoolingLimitType,
            "maximum_cooling_air_flow_rate": limit(per_area[1]),
            "maximum_total_cooling_capacity": limit(per_area[3]),
        }

    def _outdoor_air_specification(
        self, doc: EPDocument, target_zone_name: str
    ) -> tuple[str, str | None]:
        """The ideal loads' outdoor air method and its detailed specification.

        Without mechanical ventilation the method is `None`. With it, the
        method is `Sum` (per person plus per floor area), or, when
        `MechVentSchedule` is set, `DetailedSpecification`: a
        `DesignSpecification:OutdoorAir` with the same flows and the schedule.

        Returns:
            method (str): The template's outdoor air method.
            name (str | None): The `DesignSpecification:OutdoorAir` name, if any.
        """
        ventilation = self.HVAC.Ventilation
        if ventilation.Provider not in ("Mechanical", "Both"):
            return "None", None
        if ventilation.MechVentSchedule is None:
            return "Sum", None
        doc, schedule_name = ventilation.MechVentSchedule.add_year_to_idf(
            doc, name_prefix=None
        )
        name = f"{target_zone_name}_{ventilation.safe_name}_OUTDOOR_AIR"
        add_or_replace(
            doc["DesignSpecification:OutdoorAir"].add,
            name,
            outdoor_air_method="Sum",
            outdoor_air_flow_per_person=ventilation.FreshAirPerPerson,
            outdoor_air_flow_per_zone_floor_area=ventilation.FreshAirPerFloorArea,
            outdoor_air_flow_per_zone=0.0,
            outdoor_air_flow_air_changes_per_hour=0.0,
            outdoor_air_schedule_name=schedule_name,
        )
        return "DetailedSpecification", name

    def add_natural_ventilation_to_idf_zone(
        self, doc: EPDocument, target_zone_name: str
    ) -> EPDocument:
        """Add natural ventilation through the zone's windows.

        Used when the ventilation provider is `Natural` or `Both` (natural and
        mechanical). Writes a `ZoneVentilation:WindandStackOpenArea` whose
        opening area is the zone's glazed area, opened by the ventilation
        schedule.

        Args:
            doc (EPDocument): The IDF document to add the ventilation to.
            target_zone_name (str): The name of the zone.

        Returns:
            doc (EPDocument): The updated IDF document.
        """
        # total_window_area = calculate_window_area_for_zone(doc, target_zone_name)
        total_window_area = get_zone_glazed_area(doc, target_zone_name)

        if total_window_area == 0:
            logger.warning(
                f"No windows found for natural ventilation in zone {target_zone_name}"
            )
            return doc
        vent_wind_stack_name = f"{target_zone_name}_{self.SpaceUse.Thermostat.safe_name}_{self.HVAC.Ventilation.safe_name}_VENTILATION_WIND_AND_STACK_OPEN_AREA"

        doc, vent_wind_stack_name_sch = self.HVAC.Ventilation.Schedule.add_year_to_idf(
            doc,
            name_prefix=None,
            summer_design_day_sch_name="d_AllOff_00",
            winter_design_day_sch_name="d_AllOff_00",
        )
        ventilation = self.HVAC.Ventilation
        if not ventilation.IsWindOn and not ventilation.IsBuoyancyOn:
            return doc
        height_difference = (
            0.5 * _tallest_window_height(doc, target_zone_name)
            if ventilation.IsBuoyancyOn
            else 0.0
        )
        add_or_replace(
            doc["ZoneVentilation:WindandStackOpenArea"].add,
            vent_wind_stack_name,
            zone_or_space_name=target_zone_name,
            opening_area=float(total_window_area),
            opening_area_fraction_schedule_name=vent_wind_stack_name_sch,
            # an opening effectiveness of 0 removes the wind term
            opening_effectiveness="Autocalculate" if ventilation.IsWindOn else 0.0,
            effective_angle=0.0,
            # a height difference of 0 removes the stack term
            height_difference=height_difference,
            discharge_coefficient_for_opening="Autocalculate",
            minimum_indoor_temperature=ventilation.NatVentZoneTempSetpoint,
            delta_temperature=2.0,
            minimum_outdoor_temperature=ventilation.NatVentMinOutdoorAirTemp,
            maximum_outdoor_temperature=ventilation.NatVentMaxOutdoorAirTemp,
            maximum_wind_speed=40.0,
        )
        if ventilation.NatVentMaxRelHumidity is not None:
            _close_above_outdoor_humidity(
                doc, vent_wind_stack_name, ventilation.NatVentMaxRelHumidity
            )
        return doc

    def add_scheduled_ventilation_to_idf_zone(
        self, doc: EPDocument, target_zone_name: str
    ) -> EPDocument:
        """Add scheduled ventilation: outdoor air at a set number of air changes.

        Writes a natural `ZoneVentilation:DesignFlowRate` of
        `ScheduledVentilationAch` air changes per hour, multiplied by
        `ScheduledVentilationSchedule` (constant when None) and stopped while the
        zone is colder than `ScheduledVentilationSetpoint`.

        Args:
            doc (EPDocument): The IDF document to add the ventilation to.
            target_zone_name (str): The name of the zone.

        Returns:
            doc (EPDocument): The updated IDF document.
        """
        ventilation = self.HVAC.Ventilation
        if ventilation.ScheduledVentilationAch == 0:
            return doc
        name = f"{target_zone_name}_{ventilation.safe_name}_SCHEDULED_VENTILATION"
        if ventilation.ScheduledVentilationSchedule is None:
            schedule_name = add_constant_schedule(
                doc, f"{name}_Schedule", 1, "Fraction"
            ).name
        else:
            doc, schedule_name = (
                ventilation.ScheduledVentilationSchedule.add_year_to_idf(
                    doc, name_prefix=None
                )
            )
        add_or_replace(
            doc["ZoneVentilation:DesignFlowRate"].add,
            name,
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_name,
            schedule_name=schedule_name,
            design_flow_rate_calculation_method="AirChanges/Hour",
            air_changes_per_hour=ventilation.ScheduledVentilationAch,
            ventilation_type="Natural",
            constant_term_coefficient=1.0,
            temperature_term_coefficient=0.0,
            velocity_term_coefficient=0.0,
            velocity_squared_term_coefficient=0.0,
            minimum_indoor_temperature=ventilation.ScheduledVentilationSetpoint
            if ventilation.ScheduledVentilationSetpoint is not None
            else -100.0,
        )
        return doc


OUTDOOR_HUMIDITY_SENSOR = "SBEM_Outdoor_RH"
"""The EMS sensor of the outdoor relative humidity, shared by every zone."""


def _ems_name(name: str) -> str:
    """An EMS variable name (letters, digits, underscores) derived from `name`."""
    return re.sub(r"\W", "_", name)


def _tallest_window_height(doc: EPDocument, zone_name: str) -> float:
    """The height of the zone's tallest window [m] (0 without windows)."""
    heights = [0.0]
    for window in get_zone_windows(doc, zone_name):
        polygon = get_surface_coords(window)
        if polygon is None:
            continue
        z = [c[2] for c in polygon.as_tuple_list()]
        heights.append(max(z) - min(z))
    return max(heights)


def _close_above_outdoor_humidity(
    doc: EPDocument, ventilation_name: str, max_relative_humidity: float
) -> None:
    """Shut a natural ventilation object while outdoor humidity is above a limit.

    An EMS program sets the ventilation's air exchange flow rate to 0 whenever
    the outdoor relative humidity exceeds `max_relative_humidity` [%], and leaves
    it to EnergyPlus otherwise.
    """
    add_or_replace(
        doc["EnergyManagementSystem:Sensor"].add,
        OUTDOOR_HUMIDITY_SENSOR,
        output_variable_or_output_meter_index_key_name="Environment",
        output_variable_or_output_meter_name="Site Outdoor Air Relative Humidity",
    )
    actuator = f"{_ems_name(ventilation_name)}_Flow"
    add_or_replace(
        doc["EnergyManagementSystem:Actuator"].add,
        actuator,
        actuated_component_unique_name=ventilation_name,
        actuated_component_type="Zone Ventilation",
        actuated_component_control_type="Air Exchange Flow Rate",
    )
    program = f"{_ems_name(ventilation_name)}_RH_Limit"
    add_or_replace(
        doc["EnergyManagementSystem:Program"].add,
        program,
        lines=[
            {"program_line": line}
            for line in (
                f"IF {OUTDOOR_HUMIDITY_SENSOR} > {max_relative_humidity}",
                f"SET {actuator} = 0",
                "ELSE",
                f"SET {actuator} = Null",
                "ENDIF",
            )
        ],
    )
    add_or_replace(
        doc["EnergyManagementSystem:ProgramCallingManager"].add,
        f"{program}_Manager",
        energyplus_model_calling_point="BeginTimestepBeforePredictor",
        programs=[{"program_name": program}],
    )
