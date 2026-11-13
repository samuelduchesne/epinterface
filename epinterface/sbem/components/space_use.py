"""Space use components for the SBEM library.."""

import logging
from typing import Literal

from idfkit import IDFDocument
from pydantic import Field

from epinterface.constants import assumed_constants, physical_constants
from epinterface.document import add_or_replace, field_name
from epinterface.interface import add_constant_schedule
from epinterface.sbem.common import BoolStr, MetadataMixin, NamedObject
from epinterface.sbem.components.schedules import (
    YearComponent,
)
from epinterface.sbem.exceptions import NotImplementedParameter

logger = logging.getLogger(__name__)

# TODO: add some type validation on schedules - e.g. people must be people type, lighting and equipment must be power, heating setpoints must be schedules, etc.


class OccupancyComponent(NamedObject, MetadataMixin, extra="forbid"):
    """An occupancy object in the SBEM library."""

    PeopleDensity: float = Field(
        ...,
        title="Occupancy density of the object [ppl/m2]",
        ge=0,
    )
    Schedule: YearComponent = Field(
        ..., title="Occupancy schedule of the object [frac]"
    )
    IsOn: BoolStr = Field(..., title="People are on")
    MetabolicRate: float = assumed_constants.MetabolicRate_met

    @property
    def MetabolicRate_met_to_W(self):
        """Get the metabolic rate in Watts."""
        avg_human_weight_kg = assumed_constants.AvgHumanWeight_kg
        conversion_factor = physical_constants.ConversionFactor_W_per_kg
        # mets * kg * W/kg = W
        return self.MetabolicRate * avg_human_weight_kg * conversion_factor

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
        if not self.IsOn:
            return doc

        activity_sch_name = (
            f"{target_zone_or_zone_list_name}_{self.safe_name}_PEOPLE_Activity_Schedule"
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
            doc, activity_sch_name, self.MetabolicRate_met_to_W, "AnyNumber"
        )

        name_prefix = f"{target_zone_or_zone_list_name}_{self.safe_name}_PEOPLE"
        doc, year_name = self.Schedule.add_year_to_idf(
            doc,
            name_prefix=None,
            summer_design_day_sch_name="d_AllOn_00",
            winter_design_day_sch_name="d_AllOn_00",
        )
        add_or_replace(
            doc,
            "People",
            name_prefix,
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            number_of_people_schedule_name=year_name,
            number_of_people_calculation_method="People/Area",
            people_per_floor_area=self.PeopleDensity,
            fraction_radiant=assumed_constants.FractionRadiantPeople,
            sensible_heat_fraction="autocalculate",
            activity_level_schedule_name=activity_sch_year.name,
            enable_ashrae_55_comfort_warnings="No",
        )
        return doc


DimmingTypeType = Literal["Off", "Stepped", "Continuous"]


class LightingComponent(NamedObject, MetadataMixin, extra="forbid"):
    """A lighting object in the SBEM library."""

    PowerDensity: float = Field(
        ...,
        title="Lighting density of the object [W/m2]",
        ge=0,
    )

    DimmingType: DimmingTypeType = Field(
        ...,
        title="Dimming type",
    )
    Schedule: YearComponent = Field(..., title="Lighting schedule of the object [frac]")
    IsOn: BoolStr = Field(..., title="Lights are on")

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
        if not self.IsOn:
            return doc

        if self.DimmingType != "Off":
            raise NotImplementedParameter("DimmingType:On", self.Name, "Lights")

        name_prefix = f"{target_zone_or_zone_list_name}_{self.safe_name}_LIGHTS"
        doc, year_name = self.Schedule.add_year_to_idf(
            doc,
            name_prefix=None,
            summer_design_day_sch_name="d_AllOn_00",
            winter_design_day_sch_name="d_AllOn_00",
        )
        watts_per_area = field_name(
            doc, "Lights", "watts_per_floor_area", "watts_per_zone_floor_area"
        )
        add_or_replace(
            doc,
            "Lights",
            name_prefix,
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            schedule_name=year_name,
            design_level_calculation_method="Watts/Area",
            **{watts_per_area: self.PowerDensity},
            return_air_fraction=assumed_constants.ReturnAirFractionLights,
            fraction_radiant=assumed_constants.FractionRadiantLights,
            fraction_visible=assumed_constants.FractionVisibleLights,
            fraction_replaceable=assumed_constants.FractionReplaceableLights,
        )
        return doc


class EquipmentComponent(NamedObject, MetadataMixin, extra="forbid"):
    """An equipment object in the SBEM library."""

    PowerDensity: float = Field(..., title="Equipment density of the object [W/m2]")
    Schedule: YearComponent = Field(
        ..., title="Equipment schedule of the object [frac]"
    )
    IsOn: BoolStr = Field(..., title="Equipment is on")

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
        if not self.IsOn:
            return doc

        name_prefix = f"{target_zone_or_zone_list_name}_{self.safe_name}_EQUIPMENT"
        doc, year_name = self.Schedule.add_year_to_idf(
            doc,
            name_prefix=None,
            summer_design_day_sch_name="d_AllOn_00",
            winter_design_day_sch_name="d_AllOn_00",
        )
        watts_per_area = field_name(
            doc,
            "ElectricEquipment",
            "watts_per_floor_area",
            "watts_per_zone_floor_area",
        )
        add_or_replace(
            doc,
            "ElectricEquipment",
            name_prefix,
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            schedule_name=year_name,
            design_level_calculation_method="Watts/Area",
            **{watts_per_area: self.PowerDensity},
            fraction_latent=assumed_constants.FractionLatentEquipment,
            fraction_radiant=assumed_constants.FractionRadiantEquipment,
            fraction_lost=assumed_constants.FractionLostEquipment,
        )
        return doc


class ThermostatComponent(NamedObject, MetadataMixin, extra="forbid"):
    """A thermostat object in the SBEM library."""

    IsOn: BoolStr = Field(..., title="Thermostat is on")
    HeatingSetpoint: float = Field(
        ...,
        title="Heating setpoint of the object; ignored if schedule is present, except also used for determining natural ventilation boundaries.",
    )
    HeatingSchedule: YearComponent = Field(..., title="Heating schedule of the object")
    CoolingSetpoint: float = Field(
        ...,
        title="Cooling setpoint of the object; ignored if schedule is present, except also used for determining natural ventilation boundaries.",
    )
    CoolingSchedule: YearComponent = Field(..., title="Cooling schedule of the object")


class WaterUseComponent(NamedObject, MetadataMixin, extra="forbid"):
    """A water use object in the SBEM library."""

    FlowRatePerPerson: float = Field(
        ...,
        title="Flow rate per person [m3/day/p]",
        ge=0,
        le=10,
        description="This is the AVERAGE total amount of water per person per day; "
        "the peak flow rate will be computed dynamically based on the schedule.",
    )
    Schedule: YearComponent = Field(..., title="Water schedule")


class ZoneSpaceUseComponent(NamedObject, MetadataMixin, extra="forbid"):
    """Space use object."""

    Occupancy: OccupancyComponent
    Lighting: LightingComponent
    Equipment: EquipmentComponent
    Thermostat: ThermostatComponent
    WaterUse: WaterUseComponent

    # TODO: Is this really necessary, or should it be lifted up to the ZoneComponent?
    # it currently is acting as a very bare bones passthrough.
    def add_loads_to_idf_zone(
        self, doc: IDFDocument, target_zone_name: str
    ) -> IDFDocument:
        """Add the loads to an IDF zone.

        This will add the people, equipment, and lights to the zone.

        Args:
            doc (IDFDocument): The IDF document to add the loads to.
            target_zone_name (str): The name of the zone to add the loads to.

        Returns:
            IDFDocument: The updated IDF document.
        """
        doc = self.Lighting.add_lights_to_idf_zone(doc, target_zone_name)
        doc = self.Occupancy.add_people_to_idf_zone(doc, target_zone_name)
        doc = self.Equipment.add_equipment_to_idf_zone(doc, target_zone_name)
        # doc = self.Thermostat.add_thermostat_to_idf_zone(doc, target_zone_name)
        # raise NotImplementedError
        return doc
