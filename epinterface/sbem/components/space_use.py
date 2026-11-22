"""Space use components for the SBEM library.."""

import logging
from typing import Literal

from idfkit.geometry import get_surface_coords
from pydantic import Field

from epinterface.constants import assumed_constants, physical_constants
from epinterface.document import EPDocument, add_or_replace, watts_per_area
from epinterface.interface import add_constant_schedule
from epinterface.sbem.common import BoolStr, MetadataMixin, NamedObject
from epinterface.sbem.components.schedules import (
    YearComponent,
)

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
        self, doc: EPDocument, target_zone_or_zone_list_name: str
    ) -> EPDocument:
        """Add people to an IDF zone.

        Args:
            doc (EPDocument): The IDF document to add the people to.
            target_zone_or_zone_list_name (str): The name of the zone or zone list to add the people to.

        Returns:
            EPDocument: The updated IDF document.
        """
        if not self.IsOn:
            return doc

        activity_sch_name = (
            f"{target_zone_or_zone_list_name}_{self.safe_name}_PEOPLE_Activity_Schedule"
        )
        if "AnyNumber" not in doc["ScheduleTypeLimits"]:
            add_or_replace(
                doc["ScheduleTypeLimits"].add,
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
            # Untyped: 24.1 renamed a mean radiant temperature choice.
            doc.get_collection("People").add,
            name_prefix,
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            number_of_people_schedule_name=year_name,
            number_of_people_calculation_method="People/Area",
            people_per_floor_area=self.PeopleDensity,
            fraction_radiant=assumed_constants.FractionRadiantPeople,
            sensible_heat_fraction="Autocalculate",
            activity_level_schedule_name=activity_sch_year.name,
            enable_ashrae_55_comfort_warnings="No",
        )
        return doc


DimmingTypeType = Literal["Off", "Stepped", "Continuous"]

DAYLIGHTING_STEPS = 3
"""Number of steps of a stepped daylighting control."""


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
    IlluminanceTarget: float = Field(
        default=500.0,
        title="Daylighting illuminance setpoint [lux]",
        description=(
            "Illuminance at the reference point above which dimming lowers the "
            "lights. Used when DimmingType is not Off."
        ),
        gt=0,
    )
    DaylightWorkplaneHeight: float = Field(
        default=0.8,
        title="Daylighting workplane height [m]",
        description="Height of the daylighting reference point above the floor.",
        ge=0,
    )
    DaylightMeshResolution: float | None = Field(
        default=None,
        title="Daylighting illuminance map spacing [m]",
        description=(
            "Spacing of the reported illuminance map's grid at the workplane "
            "height, when DimmingType is not Off. None: no map."
        ),
        gt=0,
    )

    def add_lights_to_idf_zone(
        self, doc: EPDocument, target_zone_or_zone_list_name: str
    ) -> EPDocument:
        """Add lights to an IDF zone.

        Note that this makes some assumptions about the fraction visible/radiant/replaceable.

        Args:
            doc (EPDocument): The IDF document to add the lights to.
            target_zone_or_zone_list_name (str): The name of the zone or zone list to add the lights to.

        Returns:
            EPDocument: The updated IDF document.
        """
        if not self.IsOn:
            return doc

        name_prefix = f"{target_zone_or_zone_list_name}_{self.safe_name}_LIGHTS"
        doc, year_name = self.Schedule.add_year_to_idf(
            doc,
            name_prefix=None,
            summer_design_day_sch_name="d_AllOn_00",
            winter_design_day_sch_name="d_AllOn_00",
        )
        add_or_replace(
            # Untyped: the Watts/Area field was renamed in 24.1 (see watts_per_area).
            doc.get_collection("Lights").add,
            name_prefix,
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            schedule_name=year_name,
            design_level_calculation_method="Watts/Area",
            **watts_per_area(doc, self.PowerDensity),
            return_air_fraction=assumed_constants.ReturnAirFractionLights,
            fraction_radiant=assumed_constants.FractionRadiantLights,
            fraction_visible=assumed_constants.FractionVisibleLights,
            fraction_replaceable=assumed_constants.FractionReplaceableLights,
        )
        if self.DimmingType != "Off":
            doc = self.add_daylighting_to_idf_zone(doc, target_zone_or_zone_list_name)
        return doc

    def add_daylighting_to_idf_zone(
        self, doc: EPDocument, target_zone_name: str
    ) -> EPDocument:
        """Dim the zone's lights with daylight.

        Writes a `Daylighting:Controls` (split-flux method, the component's
        dimming type) with one reference point controlling all the lights, at
        `DaylightWorkplaneHeight` above the centre of the zone's largest floor
        surface, with `IlluminanceTarget` as setpoint. With a
        `DaylightMeshResolution`, also an `Output:IlluminanceMap` over the
        floor's bounding box at the workplane height.

        Args:
            doc (EPDocument): The IDF document.
            target_zone_name (str): The zone (not a zone list).

        Returns:
            EPDocument: The updated IDF document.

        Raises:
            ValueError: If the zone has no floor surface.
        """
        floors = [
            srf
            for srf in doc["BuildingSurface:Detailed"]
            if (srf.zone_name or "").lower() == target_zone_name.lower()
            and (srf.surface_type or "").lower() == "floor"
        ]
        polygons = [p for p in (get_surface_coords(f) for f in floors) if p]
        if not polygons:
            msg = f"Daylighting needs a floor surface in zone {target_zone_name!r}."
            raise ValueError(msg)
        largest = max(polygons, key=lambda p: p.area)
        points = largest.as_tuple_list()
        x = sum(c[0] for c in points) / len(points)
        y = sum(c[1] for c in points) / len(points)
        z = min(c[2] for c in points) + self.DaylightWorkplaneHeight
        name = f"{target_zone_name}_{self.safe_name}_DAYLIGHTING"
        point_name = f"{name}_POINT"
        add_or_replace(
            doc["Daylighting:ReferencePoint"].add,
            point_name,
            zone_or_space_name=target_zone_name,
            x_coordinate_of_reference_point=x,
            y_coordinate_of_reference_point=y,
            z_coordinate_of_reference_point=z,
        )
        add_or_replace(
            doc["Daylighting:Controls"].add,
            name,
            zone_or_space_name=target_zone_name,
            daylighting_method="SplitFlux",
            lighting_control_type=self.DimmingType,
            number_of_stepped_control_steps=DAYLIGHTING_STEPS,
            control_data=[
                {
                    "daylighting_reference_point_name": point_name,
                    "fraction_of_lights_controlled_by_reference_point": 1.0,
                    "illuminance_setpoint_at_reference_point": self.IlluminanceTarget,
                }
            ],
        )
        if self.DaylightMeshResolution is not None:
            all_points = [c for p in polygons for c in p.as_tuple_list()]
            xs = [c[0] for c in all_points]
            ys = [c[1] for c in all_points]
            step = self.DaylightMeshResolution

            def count(lo: float, hi: float) -> int:
                return max(2, int((hi - lo) / step) + 1)

            add_or_replace(
                doc["Output:IlluminanceMap"].add,
                f"{name}_MAP",
                zone_or_space_name=target_zone_name,
                z_height=z,
                x_minimum_coordinate=min(xs),
                x_maximum_coordinate=max(xs),
                number_of_x_grid_points=count(min(xs), max(xs)),
                y_minimum_coordinate=min(ys),
                y_maximum_coordinate=max(ys),
                number_of_y_grid_points=count(min(ys), max(ys)),
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
        self, doc: EPDocument, target_zone_or_zone_list_name: str
    ) -> EPDocument:
        """Add equipment to an IDF zone.

        Args:
            doc (EPDocument): The IDF document to add the equipment to.
            target_zone_or_zone_list_name (str): The name of the zone or zone list to add the equipment to.

        Returns:
            EPDocument: The updated IDF document.
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
        add_or_replace(
            # Untyped: the Watts/Area field was renamed in 24.1 (see watts_per_area).
            doc.get_collection("ElectricEquipment").add,
            name_prefix,
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            schedule_name=year_name,
            design_level_calculation_method="Watts/Area",
            **watts_per_area(doc, self.PowerDensity),
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
        self, doc: EPDocument, target_zone_name: str
    ) -> EPDocument:
        """Add the loads to an IDF zone.

        This will add the people, equipment, and lights to the zone.

        Args:
            doc (EPDocument): The IDF document to add the loads to.
            target_zone_name (str): The name of the zone to add the loads to.

        Returns:
            EPDocument: The updated IDF document.
        """
        doc = self.Lighting.add_lights_to_idf_zone(doc, target_zone_name)
        doc = self.Occupancy.add_people_to_idf_zone(doc, target_zone_name)
        doc = self.Equipment.add_equipment_to_idf_zone(doc, target_zone_name)
        # doc = self.Thermostat.add_thermostat_to_idf_zone(doc, target_zone_name)
        # raise NotImplementedError
        return doc
