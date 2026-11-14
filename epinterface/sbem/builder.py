"""A module for building the energy model using the SBEM template library approach."""

import gc
import io
import logging
import os
import sys
import tempfile
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast, get_args
from uuid import uuid4

import numpy as np
import pandas as pd
import yaml
from idfkit import IDFObject
from idfkit.geometry import Polygon3D, get_surface_coords, set_surface_coords
from idfkit.simulation.parsers.sql import SQLResult
from ladybug.epw import EPW
from numpy.typing import NDArray
from pydantic import BaseModel, Field, field_validator, model_validator

from epinterface.analysis.energy_and_peak import DESIRED_METERS_FOR_VERSION
from epinterface.analysis.energy_and_peak import (
    standard_results_postprocess as energy_and_peak_postprocess,
)
from epinterface.analysis.overheating import (
    OverheatingAnalysisConfig,
    OverheatingAnalysisResults,
    overheating_results_postprocess,
)
from epinterface.constants import assumed_constants, physical_constants
from epinterface.data import EnergyPlusArtifactDir
from epinterface.ddy_injector_bayes import DDYSizingSpec
from epinterface.document import (
    EPDocument,
    add_or_replace,
    load_document,
    minimal_document,
)
from epinterface.geometry import ShoeboxGeometry, get_zone_floor_area
from epinterface.interface import (
    add_default_schedules,
    add_default_sim_controls,
    add_site_ground_temperature,
    add_zone_list,
)
from epinterface.results import timeseries_frame
from epinterface.sbem.components.composer import (
    construct_composer_model,
    construct_graph,
)
from epinterface.sbem.components.envelope import (
    ConstructionAssemblyComponent,
    EnvelopeAssemblyComponent,
    GlazingConstructionSimpleComponent,
)
from epinterface.sbem.components.systems import DHWFuelType, FuelType
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.sbem.exceptions import NotImplementedParameter
from epinterface.sbem.prisma.client import PrismaSettings
from epinterface.settings import energyplus_settings

# AVAILABLE_HOURLY_VARIABLES, AvailableHourlyVariables and add_output_objects
# live in epinterface.simulation and are re-exported here for existing imports.
from epinterface.simulation import (
    AVAILABLE_HOURLY_VARIABLES as AVAILABLE_HOURLY_VARIABLES,
)
from epinterface.simulation import (
    AvailableHourlyVariables as AvailableHourlyVariables,
)
from epinterface.simulation import (
    SQLResultFile,
    add_output_objects,
    detach_sql,
    read_warnings,
    run_energyplus,
)
from epinterface.weather import BaseWeather

logger = logging.getLogger(__name__)


class SimulationPathConfig(BaseModel):
    """The configuration for the simulation's pathing."""

    output_dir: Path = Field(
        default_factory=lambda: EnergyPlusArtifactDir / "cache" / str(uuid4())[:8],
        description="The output directory for the IDF model.",
    )
    weather_dir: Path = Field(
        default_factory=lambda: EnergyPlusArtifactDir / "cache" / "weather",
        description="The directory to store the weather files.",
    )


class SurfaceHandler(BaseModel):
    """A handler for filtering and adding surfaces to a model."""

    boundary_condition: str | None
    original_construction_name: str | None
    original_surface_type: str | None
    surface_group: Literal["glazing", "opaque", "internal_mass"]
    zone_name_contains: str | None
    outside_boundary_condition_object_contains: str | None

    @model_validator(mode="after")
    def check_no_obco_if_not_bc_surface(self):
        """An outside boundary condition object is only specifiable if the boundary condition is `surface`."""
        if (
            self.outside_boundary_condition_object_contains is not None
            and self.boundary_condition != "surface"
        ):
            msg = "An outside boundary condition object is only specifiable if the boundary condition is `surface`."
            raise ValueError(msg)
        return self

    def assign_constructions_to_objs(
        self,
        doc: EPDocument,
        construction: ConstructionAssemblyComponent
        | GlazingConstructionSimpleComponent,
    ) -> EPDocument:
        """Adds a construction (and its materials) to a document and assigns it to matching surfaces.

        The basic idea is to look for certain idf objects that need a construction assigned to them,
        and then assign the construction to them by name.

        Depending on the configuration of the surface handler, we will look for different types of IDF objects.

        Args:
            doc (EPDocument): The document to add the construction to.
            construction (ConstructionAssemblyComponent | GlazingConstructionComponent): The construction to add.
        """
        # This will identify what *type* of energy plus object we need to assign a particular construction to.
        # e.g. glazing -> look for FENESTRATIONSURFACE:DETAILED
        # e.g. opaque -> look for BUILDINGSURFACE:DETAILED
        # e.g. internal mass -> look for INTERNALMASS
        obj_type_key = (
            "FenestrationSurface:Detailed"
            if self.surface_group == "glazing"
            else (
                "InternalMass"
                if self.surface_group == "internal_mass"
                else "BuildingSurface:Detailed"
            )
        )

        if self.boundary_condition is not None and self.surface_group == "glazing":
            raise NotImplementedParameter(
                "BoundaryCondition", self.surface_group, "Glazing"
            )

        # Now we can find the matching idf objects that need a construction.
        srfs = [srf for srf in doc[obj_type_key] if self.check_srf(srf)]
        doc = construction.add_to_idf(doc)

        # and then we can finally assign the construction to the surfaces.
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
            and self.check_zone_name(srf)
            and self.check_outside_boundary_condition_object(srf)
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

    # TODO: convert this to a regex for better control
    def check_zone_name(self, srf: IDFObject):
        """Check that the zone name for the surface contains the expected substring."""
        if self.zone_name_contains is None:
            # Ignore the zone name check when filter not provided
            return True
        if self.surface_group == "glazing":
            # Ignore the zone name check for windows
            return True
        # Check the zone name
        zone_name = srf.zone_name or ""
        return self.zone_name_contains.lower() in zone_name.lower()

    def check_outside_boundary_condition_object(self, srf: IDFObject):
        """Check if the surface's outside boundary condition object contains the desired substring."""
        if self.outside_boundary_condition_object_contains is None:
            # Ignore the outside boundary condition object check when filter not provided
            return True
        # Check the outside boundary condition object
        if self.surface_group == "glazing":
            # Ignore the outside boundary condition object check for windows
            return True
        return (
            self.outside_boundary_condition_object_contains.lower()
            in (srf.outside_boundary_condition_object or "").lower()
        )


class SurfaceHandlers(BaseModel):
    """A collection of surface handlers for different surface types."""

    RoofOutdoorBC: SurfaceHandler
    AtticFloorFloor: SurfaceHandler
    AtticFloorCeiling: SurfaceHandler
    Facade: SurfaceHandler
    FloorCeilingFloor: SurfaceHandler
    FloorCeilingCeiling: SurfaceHandler
    Partition: SurfaceHandler
    InternalMass: SurfaceHandler
    GroundSlab: SurfaceHandler
    GroundWall: SurfaceHandler
    BasementCeilingCeiling: SurfaceHandler
    BasementCeilingFloor: SurfaceHandler
    Window: SurfaceHandler

    @classmethod
    def Default(cls, basement_suffix: str):
        """Get the default surface handlers."""
        roof_outdoor_bc_handler = SurfaceHandler(
            boundary_condition="outdoors",
            original_construction_name=None,
            original_surface_type="roof",
            surface_group="opaque",
            zone_name_contains=None,
            outside_boundary_condition_object_contains=None,
        )

        facade_handler = SurfaceHandler(
            boundary_condition="outdoors",
            original_construction_name=None,
            original_surface_type="wall",
            surface_group="opaque",
            zone_name_contains=None,
            outside_boundary_condition_object_contains=None,
        )
        partition_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="wall",
            surface_group="opaque",
            zone_name_contains=None,
            outside_boundary_condition_object_contains=None,
        )
        ground_wall_handler = SurfaceHandler(
            boundary_condition="ground",
            original_construction_name=None,
            original_surface_type="wall",
            surface_group="opaque",
            zone_name_contains=None,
            outside_boundary_condition_object_contains=None,
        )
        floor_ceiling_floor_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="floor",
            surface_group="opaque",
            zone_name_contains=None,
            outside_boundary_condition_object_contains=None,
        )
        floor_ceiling_ceiling_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="ceiling",
            surface_group="opaque",
            zone_name_contains=None,
            outside_boundary_condition_object_contains=None,
        )
        ground_slab_handler = SurfaceHandler(
            boundary_condition="ground",
            original_construction_name=None,
            original_surface_type="floor",
            surface_group="opaque",
            zone_name_contains=None,
            outside_boundary_condition_object_contains=None,
        )
        basement_ceiling_ceiling_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="ceiling",
            surface_group="opaque",
            zone_name_contains=basement_suffix,  # this is because the basement will always `Block shoebox .* -1/0` (depends on core/perim vs by_storey)
            outside_boundary_condition_object_contains=None,
        )
        basement_ceiling_floor_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="floor",
            surface_group="opaque",
            zone_name_contains=None,  # this is because the basement will always `Block shoebox .* -1/0` (depends on core/perim vs by_storey)
            outside_boundary_condition_object_contains=basement_suffix,
        )
        window_handler = SurfaceHandler(
            boundary_condition=None,
            original_construction_name=None,
            original_surface_type=None,
            surface_group="glazing",
            zone_name_contains=None,
            outside_boundary_condition_object_contains=None,
        )

        internal_mass_handler = SurfaceHandler(
            boundary_condition=None,
            original_construction_name=None,
            original_surface_type=None,
            surface_group="internal_mass",
            zone_name_contains=None,
            outside_boundary_condition_object_contains=None,
        )

        attic_floor_floor_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="floor",
            surface_group="opaque",
            zone_name_contains="attic",
            outside_boundary_condition_object_contains=None,
        )
        attic_floor_ceiling_handler = SurfaceHandler(
            boundary_condition="surface",
            original_construction_name=None,
            original_surface_type="ceiling",
            surface_group="opaque",
            zone_name_contains=None,
            outside_boundary_condition_object_contains="attic",
        )
        return cls(
            RoofOutdoorBC=roof_outdoor_bc_handler,
            AtticFloorFloor=attic_floor_floor_handler,
            AtticFloorCeiling=attic_floor_ceiling_handler,
            Facade=facade_handler,
            FloorCeilingFloor=floor_ceiling_floor_handler,
            FloorCeilingCeiling=floor_ceiling_ceiling_handler,
            Partition=partition_handler,
            InternalMass=internal_mass_handler,
            GroundSlab=ground_slab_handler,
            GroundWall=ground_wall_handler,
            BasementCeilingCeiling=basement_ceiling_ceiling_handler,
            BasementCeilingFloor=basement_ceiling_floor_handler,
            Window=window_handler,
        )

    def handle_envelope(
        self,
        doc: EPDocument,
        constructions: EnvelopeAssemblyComponent,
        window: GlazingConstructionSimpleComponent | None,
        with_attic: bool,
        with_basement: bool,
        exposed_basement_frac: float = 0,
    ):
        """Assign the envelope to the document.

        Note that this will add a "reversed" construction for the floorsystem slab/ceiling

        Args:
            doc (EPDocument): The document to add the envelope to.
            constructions (ZoneConstruction): The construction names for the envelope.
            window (GlazingConstructionSimpleComponent | None): The window definition.
            with_attic (bool): Whether to add the attic floor and ceiling constructions.
            with_basement (bool): Whether to add the basement floor and ceiling constructions.
            exposed_basement_frac (float): The fraction of the basement walls that are exposed above ground.

        Returns:
            doc (EPDocument): The updated document.
        """
        floor_ceiling_reversed = constructions.FloorCeilingAssembly.reversed
        attic_floor_reversed = constructions.AtticFloorAssembly.reversed
        basement_ceiling_reversed = constructions.BasementCeilingAssembly.reversed

        # handle the roof which will always have the "roof" surface type
        # and "outdoors" for the bc but needs a different construction.
        outdoor_roof_bc = (
            constructions.AtticRoofAssembly
            if with_attic
            else constructions.FlatRoofAssembly
        )
        doc = self.RoofOutdoorBC.assign_constructions_to_objs(
            doc=doc, construction=outdoor_roof_bc
        )

        doc = self.Facade.assign_constructions_to_objs(
            doc=doc, construction=constructions.FacadeAssembly
        )
        doc = self.Partition.assign_constructions_to_objs(
            doc=doc, construction=constructions.PartitionAssembly
        )
        doc = self.FloorCeilingFloor.assign_constructions_to_objs(
            doc=doc, construction=floor_ceiling_reversed
        )
        doc = self.FloorCeilingCeiling.assign_constructions_to_objs(
            doc=doc, construction=constructions.FloorCeilingAssembly
        )
        # NB: We must execute basement and attic floor/ceiling systems
        # AFTER the regular floor ceiling systems because the regular floor ceilings
        # will match all of the floor/ceiling surfaces
        # and we want to overwrite their constructions.
        if with_basement:
            doc = self.BasementCeilingCeiling.assign_constructions_to_objs(
                doc=doc, construction=constructions.BasementCeilingAssembly
            )
            doc = self.BasementCeilingFloor.assign_constructions_to_objs(
                doc=doc, construction=basement_ceiling_reversed
            )
        if with_attic:
            doc = self.AtticFloorFloor.assign_constructions_to_objs(
                doc=doc, construction=constructions.AtticFloorAssembly
            )
            doc = self.AtticFloorCeiling.assign_constructions_to_objs(
                doc=doc, construction=attic_floor_reversed
            )

        doc = self.GroundSlab.assign_constructions_to_objs(
            doc=doc, construction=constructions.GroundSlabAssembly
        )
        doc = self.GroundWall.assign_constructions_to_objs(
            doc=doc, construction=constructions.GroundWallAssembly
        )

        if with_basement and exposed_basement_frac > 0:
            basement_wall_surfaces = [
                srf
                for srf in doc["BuildingSurface:Detailed"]
                if (srf.outside_boundary_condition or "").lower() == "ground"
                and (srf.surface_type or "").lower() == "wall"
            ]
            for srf in basement_wall_surfaces:
                polygon = get_surface_coords(srf)
                if polygon is None:
                    msg = f"Basement wall {srf.name} has no vertices."
                    raise ValueError(msg)
                coords = polygon.as_tuple_list()
                z_coords = [c[2] for c in coords]
                min_z = min(z_coords)
                max_z = max(z_coords)
                h = max_z - min_z
                unexposed_height = h * (1 - exposed_basement_frac)
                unexposed_height = min(
                    max(unexposed_height, 0.15), h - 0.15
                )  # 15cm, approximately 6in
                cut_z = min_z + unexposed_height
                z_coords_lower_section = [z if z == min_z else cut_z for z in z_coords]
                z_coords_upper_section = [z if z == max_z else cut_z for z in z_coords]
                coords_lower_section = [
                    (c[0], c[1], z)
                    for c, z in zip(coords, z_coords_lower_section, strict=False)
                ]
                coords_upper_section = [
                    (c[0], c[1], z)
                    for c, z in zip(coords, z_coords_upper_section, strict=False)
                ]
                new_bottom_srf = doc.copyidfobject(srf, new_name=f"{srf.name}_bottom")
                new_top_srf = doc.copyidfobject(srf, new_name=f"{srf.name}_top")
                set_surface_coords(
                    new_bottom_srf, Polygon3D.from_tuples(coords_lower_section)
                )
                set_surface_coords(
                    new_top_srf, Polygon3D.from_tuples(coords_upper_section)
                )
                new_top_srf.outside_boundary_condition = "outdoors"
                doc.removeidfobject(srf)

        if window:
            doc = self.Window.assign_constructions_to_objs(doc=doc, construction=window)

        if constructions.InternalMassAssembly is not None:
            # We need to create new IDF Objects since they were not added into the scene
            # yet (whereas the other buildingsurface/fenestrationsurface were added by
            # eppy during the add_block call which inits zone geometry)
            for zone in doc["Zone"]:
                floor_area = get_zone_floor_area(doc, zone.name) * (
                    constructions.InternalMassExposedAreaPerArea or 0
                )
                add_or_replace(
                    doc,
                    "InternalMass",
                    f"{zone.name}_InternalMass",
                    construction_name=constructions.InternalMassAssembly.Name,
                    zone_or_zonelist_name=zone.name,
                    surface_area=float(floor_area),
                )

            # once we've guaranteed that the internal mass object exists, we can
            # assign it the constructions to them
            doc = self.InternalMass.assign_constructions_to_objs(
                doc=doc, construction=constructions.InternalMassAssembly
            )
        return doc


@dataclass
class AddedZoneLists:
    """The zone names of a model, by group.

    Only the conditioned and all-zones groups are written to the document, as
    the `ZoneList` objects "Conditioned_Zones" and "All_Zones".
    """

    conditioned_zone_list: list[str]
    all_zones_list: list[str]
    occupied_zone_list: list[str]
    attic_zone_list: list[str]
    basement_zone_list: list[str]
    main_zone_list: list[str]


class AtticAssumptions(BaseModel):
    """The conditions of the attic."""

    UseFraction: float | None = Field(..., ge=0, le=1)
    Conditioned: bool


class BasementAssumptions(BaseModel):
    """The conditions of the basement."""

    UseFraction: float | None = Field(..., ge=0, le=1)
    Conditioned: bool


class Model(BaseWeather, validate_assignment=True):
    """A simple model constructor for the IDF model.

    Creates geometry as well as zone definitions.
    """

    geometry: ShoeboxGeometry
    Attic: AtticAssumptions
    Basement: BasementAssumptions
    # TODO: should we have another field for whether or not the attic is ventilated, i.e. high infiltration?
    Zone: ZoneComponent

    @field_validator("geometry", mode="after")
    @classmethod
    def check_geometry(cls, v: ShoeboxGeometry):
        """Check the geometry of the model.

        Raises:
            ValueError
        """
        # TODO: should this validator happen on the geometry object?
        if v.w < 3 or v.d < 3:
            msg = f"Geometry must be at least 3m wide and 3m long (width, depth) = ({v.w}, {v.d})."
            raise ValueError(msg)
        if (v.roof_height or 0) > (v.h * 2.5):
            msg = f"Roof Gable height must be less than two and a half times the f2f height (roof_height, f2f_height) = ({v.roof_height}, {v.h})."
            raise ValueError(msg)
        return v

    @property
    def total_conditioned_area(self) -> float:
        """The total conditioned area of the model.

        Returns:
            area (float): The total conditioned area of the model.
        """
        conditioned_area = self.geometry.total_living_area
        if self.geometry.basement and self.Basement.Conditioned:
            conditioned_area += self.geometry.footprint_area
        if self.geometry.roof_height and self.Attic.Conditioned:
            conditioned_area += self.geometry.footprint_area
        return conditioned_area

    @property
    def total_people(self) -> float:
        """The total number of people in the model.

        Returns:
            ppl (float): The total number of people in the model

        """
        raise NotImplementedError(
            "Total people is not yet implemented because of attics/basements etc."
        )
        ppl_per_m2 = (
            self.Zone.Operations.SpaceUse.Occupancy.PeopleDensity
            if self.Zone.Operations.SpaceUse.Occupancy.IsOn
            else 0
        )
        total_area = self.total_conditioned_area  # this is wrong - it should be based off of occupied area which may be different depending on attic/basement use fractions.
        total_ppl = ppl_per_m2 * total_area
        return total_ppl

        # validate the attic conditioning

    @model_validator(mode="after")
    def attic_check(self):
        """Validate the attic insulation surface and geometry.

        It is impossible to have the roof insulated but on gabling (gabling is determined by the roof height).

        It is imposisble to have a conditioned attic if there is no roof height/gabling.

        Raises:
            ValueError
        """
        # TODO: should we add a limiter for min roof height?
        if self.Attic.Conditioned and (
            self.geometry.roof_height is None or self.geometry.roof_height == 0
        ):
            msg = "Cannot have a conditioned attic if there is no roof height."
            raise ValueError(msg)

        if self.Attic.UseFraction and (
            self.geometry.roof_height is None or self.geometry.roof_height == 0
        ):
            msg = "Cannot have an occupied attic if there is no roof height."
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def basement_check(self):
        """Validate the basement insulation surface and geometry.

        It is impossible to have the basement walls insulated but have no basement.

        It is impossible to have a conditioned basement if there is no basement.

        Raises:
            ValueError
        """
        if self.Basement.Conditioned and not self.geometry.basement:
            msg = "Cannot have a conditioned basement if there is no basement in self.geometry."
            raise ValueError(msg)

        if self.Basement.UseFraction and not self.geometry.basement:
            msg = "Cannot have an occupied basement if there is no basement in self.geometry."
            raise ValueError(msg)

        return self

    def add_zone_lists(
        self,
        doc: EPDocument,
    ) -> tuple[EPDocument, AddedZoneLists]:
        """Add the zone lists to the document.

        Note that this attempts to automatically determine
        the zones from the document which are conditioned
        as well as a separate list for all zones.

        Args:
            doc (EPDocument): The document to add the zone lists to.

        Returns:
            doc (EPDocument): The document with the added zone lists
            zone_lists (AddedZoneLists): The list of zone lists
        """
        all_zone_names = [zone.name for zone in doc["Zone"]]

        conditioned_zone_names = []
        attic_zone_names = []
        basement_zone_names = []
        main_zone_names = []
        occupied_zone_names = []
        for zone in doc["Zone"]:
            # handle attic
            is_attic = "attic" in zone.name.lower()
            is_basement = (
                zone.name.lower().endswith(self.geometry.basement_suffix.lower())
                if self.geometry.basement
                else False
            )
            is_normal_zone = not is_attic and not is_basement
            should_condition = (
                (is_attic and self.Attic.Conditioned)
                or (is_basement and self.Basement.Conditioned)
                or is_normal_zone
            )
            should_be_occupied = (
                (is_attic and self.Attic.UseFraction is not None)
                or (is_basement and self.Basement.UseFraction is not None)
                or is_normal_zone
            )
            if should_condition:
                conditioned_zone_names.append(zone.name)
            if should_be_occupied:
                occupied_zone_names.append(zone.name)
            if is_attic:
                attic_zone_names.append(zone.name)
            if is_basement:
                basement_zone_names.append(zone.name)
            if is_normal_zone:
                main_zone_names.append(zone.name)

        # safety check for zone counts
        # attic never gets partitioned so it only ever contributes 1
        # to the conditioned storey count
        conditioned_storey_count = self.geometry.num_stories + (
            1 if self.Basement.Conditioned else 0
        )
        zones_per_storey = self.geometry.zones_per_storey
        expected_zone_count = conditioned_storey_count * zones_per_storey + (
            1 if self.Attic.Conditioned else 0
        )
        if len(conditioned_zone_names) != expected_zone_count:
            msg = f"Expected {expected_zone_count} zones, but found {len(conditioned_zone_names)}."
            raise ValueError(msg)

        add_zone_list(doc, "Conditioned_Zones", conditioned_zone_names)
        add_zone_list(doc, "All_Zones", all_zone_names)
        return doc, AddedZoneLists(
            conditioned_zone_list=conditioned_zone_names,
            all_zones_list=all_zone_names,
            occupied_zone_list=occupied_zone_names,
            attic_zone_list=attic_zone_names,
            basement_zone_list=basement_zone_names,
            main_zone_list=main_zone_names,
        )

    # part of the HVAC/conditioning system
    def compute_dhw(self) -> float:
        """Explicitly compute the domestic hot water energy demand.

        This is useful as a gut-check to make sure the DHW has been added correctly.

        Returns:
            energy (float): The annual domestic hot water energy demand (kWh/m2)
        """
        # TODO: this should be computed from the DHW schedule
        if not self.Zone.Operations.DHW.IsOn:
            return 0
        flow_rate_per_person = (
            self.Zone.Operations.SpaceUse.WaterUse.FlowRatePerPerson
        )  # m3/day/person, average
        temperature_rise = (
            self.Zone.Operations.DHW.WaterSupplyTemperature
            - self.Zone.Operations.DHW.WaterTemperatureInlet
        )  # K
        water_density = physical_constants.WaterDensity_kg_per_m3  # kg/m3
        c = physical_constants.WaterSpecificHeat_J_per_kg_degK  # J/kg.K
        total_flow_rate = flow_rate_per_person * self.total_people  # m3/day
        total_volume = total_flow_rate * 365  # m3 / yr
        total_mass = total_volume * water_density  # kg
        total_energy = total_mass * temperature_rise * c  # J / yr
        total_energy_kWh = total_energy / physical_constants.J_to_kWh  # kWh / yr
        # TODO: unit test this with parameterizations over basement presence/absence,
        # attic presence/absence, basement occupation/unoccupation, etc.
        # - total_conditioned_area now probably needs to be replaced with total_occupied_area
        total_energy_kWh_per_m2 = (
            total_energy_kWh / self.total_conditioned_area
        )  # kWh/m2 / yr
        return total_energy_kWh_per_m2

    def add_constructions(
        self,
        doc: EPDocument,
        constructions: EnvelopeAssemblyComponent,
        window_def: GlazingConstructionSimpleComponent | None,
    ) -> EPDocument:
        """Assigns the constructions to the surfaces in the model.

        Args:
            doc (EPDocument): The document to select the surfaces from.
            constructions (ZoneConstruction): The construction template.
            window_def (WindowDefinition): The window definition template.

        Returns:
            doc (EPDocument): The document with the selected surfaces.
        """
        handlers = SurfaceHandlers.Default(
            basement_suffix=self.geometry.basement_suffix
            if self.geometry.basement
            else "NO-OP"
        )
        doc = handlers.handle_envelope(
            doc,
            constructions,
            window_def,
            with_attic=(self.geometry.roof_height or 0) > 0,
            with_basement=self.geometry.basement,
            exposed_basement_frac=self.geometry.exposed_basement_frac,
        )

        return doc

    def build(  # noqa: C901
        self,
        config: SimulationPathConfig,
        post_geometry_callback: Callable[[EPDocument], EPDocument] | None = None,
    ) -> EPDocument:
        """Build the energy model.

        Args:
            config (SimulationConfig): The configuration for the simulation.
            post_geometry_callback (Callable[[EPDocument], EPDocument] | None): A callback to run after the geometry is added.

        Returns:
            doc (EPDocument): The built energy model.
        """
        config.output_dir.mkdir(parents=True, exist_ok=True)
        epw_path, ddy_path = self.fetch_weather(config.weather_dir)
        ep_version = energyplus_settings.version_tuple
        doc = minimal_document(ep_version)
        add_output_objects(
            doc, DESIRED_METERS_FOR_VERSION[energyplus_settings.supported_major]
        )

        ddy = load_document(ddy_path, ep_version)
        # Sizing periods run in this order. archetypal added them in set order
        # (varying from process to process); winter first is the order the
        # regression baseline ran, and the results are sensitive to it.
        ddy_spec = DDYSizingSpec(
            match=False, conditions_types=["Winter Extreme", "Summer Extreme"]
        )
        ddy_spec.inject_ddy(doc, ddy)

        doc = add_default_sim_controls(doc)
        doc, _scheds = add_default_schedules(doc)

        doc = self.geometry.add(doc)
        if post_geometry_callback is not None:
            doc = post_geometry_callback(doc)

        # construct zone lists
        doc, added_zone_lists = self.add_zone_lists(doc)

        # Handle main zones
        for zone in added_zone_lists.main_zone_list:
            self.Zone.add_to_idf_zone(doc, zone)

        # Handle setting ground temperature
        subtractor = (
            4 if (self.geometry.basement and not self.Basement.Conditioned) else 2
        )
        has_heating = self.Zone.Operations.HVAC.ConditioningSystems.Heating is not None
        has_cooling = self.Zone.Operations.HVAC.ConditioningSystems.Cooling is not None
        hsp = self.Zone.Operations.SpaceUse.Thermostat.HeatingSchedule
        csp = self.Zone.Operations.SpaceUse.Thermostat.CoolingSchedule
        epw = EPW(epw_path.as_posix())
        epw_ground_vals_all = epw.monthly_ground_temperature
        if self.geometry.basement:
            # if there is a basement, we use the 2m depth to account for the basement depth.
            epw_ground_vals = epw_ground_vals_all[4].values
        else:
            # if there is no basement, we use the 0.5m depth to account for the ground temperature.
            epw_ground_vals = epw_ground_vals_all[0.5].values
        low_ground_val = min(epw_ground_vals)
        high_ground_val = max(epw_ground_vals)
        phase = (np.array(epw_ground_vals) - low_ground_val) / (
            high_ground_val - low_ground_val
        )
        if has_heating and has_cooling:
            winter_line = np.array(hsp.MonthlyAverageValues) - subtractor
            summer_line = np.array(csp.MonthlyAverageValues) - subtractor
        elif has_heating:
            winter_line = np.array(hsp.MonthlyAverageValues) - subtractor
            summer_line = np.array(hsp.MonthlyAverageValues)
        elif has_cooling:
            winter_line = np.array(csp.MonthlyAverageValues) - subtractor
            summer_line = np.array(csp.MonthlyAverageValues) - subtractor
        else:
            # No heating or cooling, so we use the default ground temperature, should not matter much.
            winter_line = np.array(assumed_constants.SiteGroundTemperature_degC)
            summer_line = np.array(assumed_constants.SiteGroundTemperature_degC)
        interp_temp = phase * np.abs(summer_line - winter_line) + winter_line
        ground_vals = [max(epw_ground_vals[i], interp_temp[i]) for i in range(12)]
        add_site_ground_temperature(doc, ground_vals)

        # handle basements
        if self.Basement.UseFraction or self.Basement.Conditioned:
            new_zone_def = self.Zone.model_copy(deep=True)
            frac = self.Basement.UseFraction or 0
            pd = new_zone_def.Operations.SpaceUse.Occupancy.PeopleDensity
            epd = new_zone_def.Operations.SpaceUse.Equipment.PowerDensity
            lpd = new_zone_def.Operations.SpaceUse.Lighting.PowerDensity

            new_zone_def.Operations.SpaceUse.Equipment.PowerDensity = frac * epd
            new_zone_def.Operations.SpaceUse.Lighting.PowerDensity = frac * lpd
            new_zone_def.Operations.SpaceUse.Occupancy.PeopleDensity = frac * pd

            # # handle infiltration for basements, which we are assuming is 0 (or whatever is in assumed constants)
            new_zone_def.Envelope.Infiltration = (
                new_zone_def.Envelope.BasementInfiltration
            )

            if not self.Basement.Conditioned:
                new_zone_def.Operations.HVAC.Ventilation.Provider = "None"
                new_zone_def.Operations.HVAC.ConditioningSystems.Heating = None
                new_zone_def.Operations.HVAC.ConditioningSystems.Cooling = None
            else:
                # TODO: make this configurable!!!!
                print(
                    "WARNING: Basement conditioned, but Cooling disabled due to MASSACHUSETTS ASSUMPTIONS"
                )
                new_zone_def.Operations.HVAC.ConditioningSystems.Cooling = None

            for zone in added_zone_lists.basement_zone_list:
                new_zone_def.add_to_idf_zone(doc, zone)

        if self.Attic.UseFraction or self.Attic.Conditioned:
            new_zone_def = self.Zone.model_copy(deep=True)
            frac = self.Attic.UseFraction or 0
            pd = new_zone_def.Operations.SpaceUse.Occupancy.PeopleDensity
            epd = new_zone_def.Operations.SpaceUse.Equipment.PowerDensity
            lpd = new_zone_def.Operations.SpaceUse.Lighting.PowerDensity

            new_zone_def.Operations.SpaceUse.Equipment.PowerDensity = frac * epd
            new_zone_def.Operations.SpaceUse.Lighting.PowerDensity = frac * lpd
            new_zone_def.Operations.SpaceUse.Occupancy.PeopleDensity = frac * pd

            # handle infiltration for roofs
            # because the *regular* infiltration object is the one that gets added, we simply copy
            # the desired attic infiltration into the relevant section.
            new_zone_def.Envelope.Infiltration = new_zone_def.Envelope.AtticInfiltration

            if not self.Attic.Conditioned:
                new_zone_def.Operations.HVAC.Ventilation.Provider = "None"
                new_zone_def.Operations.HVAC.ConditioningSystems.Heating = None
                new_zone_def.Operations.HVAC.ConditioningSystems.Cooling = None

            # TODO: handle mutating infiltration object when "ventilated attics" are set
            for zone in added_zone_lists.attic_zone_list:
                new_zone_def.add_to_idf_zone(doc, zone)

        doc = self.add_constructions(
            doc, self.Zone.Envelope.Assemblies, self.Zone.Envelope.Window
        )

        # > operations
        # ----> space use
        # --------> lighting, equipment, occupancy to main zones.
        # ------------> special handling for attic, basement according to account for use fractions.
        # --------> water use
        # ------------> special handling for attic, basement according to account for use fractions.
        # ------------> needs information from DHW component
        # ------------> needs to calculate flow rates correctly.
        # --------> Thermostat (Ventilation below)
        # ----> HVAC
        # --------> ConditioningSystems can be effectively ignored, as these are just post-processing.
        # --------> Ventilation
        # ------------> HVACTemplate:IdealLoadsAirSystem + HVACTemplate:Thermostat, + DesignSpecification:OutdoorAir?
        # ------------> Needs to deal with link to thermostat.
        # ----> DHW (see water use above)
        # > envelope
        # ----> facade, roof, ground, floor/celing, partition, [external floor?], [slab], [internal mass]
        # --------> special handling for roof/basement insulation
        # --------> special handling for basement/ground heat transfer
        # ----> infiltration
        # --------> special handling for attic (if ventilated?)/basement (if present)
        # ----> window
        # --------> special handling for operable windows

        # TODO: Handle separately ventilated attic/basement?
        # doc = self.add_space_use(
        #     doc, self.space_use, added_zone_lists.conditioned_zone_list
        # )

        return doc

    # add schedules definition

    # base simulation information
    def simulate(
        self,
        config: SimulationPathConfig,
        post_geometry_callback: Callable[[EPDocument], EPDocument] | None = None,
    ) -> tuple[EPDocument, SQLResultFile]:
        """Build and simulate the model.

        Args:
            config (SimulationConfig): The configuration for the simulation.
            post_geometry_callback (Callable[[EPDocument], EPDocument] | None): A callback to run after the geometry is added.

        Returns:
            doc (EPDocument): The built energy model.
            sql (SQLResultFile): The open sql results file with simulation data.

        Raises:
            SimulationError: If EnergyPlus fails.
            FileNotFoundError: If the simulation produced no SQLite file.
        """
        doc = self.build(config, post_geometry_callback)
        epw_path, _ = self.fetch_weather(config.weather_dir)
        sql = run_energyplus(doc, epw_path, config.output_dir)
        return doc, sql

    def get_warnings(self, output_dir: Path) -> str:
        """Get the EnergyPlus warning text written to a simulation directory.

        Args:
            output_dir (Path): The simulation's output directory.

        Returns:
            str: The concatenated text of every `*.err` file under `output_dir`.
        """
        return read_warnings(output_dir)

    def standard_results_postprocess(
        self, sql: SQLResult, ep_version_major: int
    ) -> pd.Series:
        """Postprocess the sql file to get the standard results.

        This will return a series with two levels:
        - Aggregation: "Raw", "End Uses", "Utilities"
        - Meter: ["Electricity", "Cooling", "Heating", "Domestic Hot Water"], ["Electricity", "Propane", ...]

        Args:
            sql (SQLResult): The sql file to postprocess.
            ep_version_major (int): The major version of EnergyPlus.

        Returns:
            series (pd.Series): The postprocessed results.
        """
        ops = self.Zone.Operations
        cond_sys = ops.HVAC.ConditioningSystems
        heat_cop = (
            cond_sys.Heating.effective_system_cop if cond_sys.Heating is not None else 1
        )
        cool_cop = (
            cond_sys.Cooling.effective_system_cop if cond_sys.Cooling is not None else 1
        )
        dhw_cop = ops.DHW.effective_system_cop
        heat_fuel = cond_sys.Heating.Fuel if cond_sys.Heating is not None else None
        cool_fuel = cond_sys.Cooling.Fuel if cond_sys.Cooling is not None else None
        dhw_fuel = ops.DHW.FuelType
        all_fuel_names = sorted({*get_args(FuelType), *get_args(DHWFuelType)})
        return energy_and_peak_postprocess(
            sql,
            normalizing_floor_area=self.total_conditioned_area,
            heat_cop=heat_cop,
            cool_cop=cool_cop,
            dhw_cop=dhw_cop,
            heat_fuel=heat_fuel,
            cool_fuel=cool_fuel,
            dhw_fuel=dhw_fuel,
            all_fuel_names=all_fuel_names,
            ep_version_major=ep_version_major,
        )

    def run(
        self,
        weather_dir: Path | None = None,
        post_geometry_callback: Callable[[EPDocument], EPDocument] | None = None,
        eplus_parent_dir: Path | None = None,
        overheating_config: OverheatingAnalysisConfig | None = None,
    ) -> "ModelRunResults":
        """Build and simualte the idf model.

        With `eplus_parent_dir` set, `ModelRunResults.sql` reads the
        results `.sql` file kept in `eplus_parent_dir / "eplus_simulation"`.
        Without it, the run directory is temporary and deleted before this
        returns: the results file is first closed, then copied to a
        `tempfile.mkstemp` file in the system temporary directory, which
        `ModelRunResults.sql` reads and deletes when closed or garbage
        collected. No file in the deleted run directory is left open, which
        Windows would otherwise refuse to delete.

        Args:
            weather_dir (Path): The directory to store the weather files.
            post_geometry_callback (Callable[[EPDocument], EPDocument] | None): A callback to run after the geometry is added.
            eplus_parent_dir (Path | None): The parent directory to store the eplus working directory.  If None, a temporary directory will be used.
            overheating_config (OverheatingAnalysisConfig | None): Configuration for overheating analysis. Skips if None.

        Returns:
            ModelRunResults: The results of the model run.
        """
        with tempfile.TemporaryDirectory() as output_dir_name:
            output_dir = (
                Path(output_dir_name)
                if eplus_parent_dir is None
                else eplus_parent_dir / "eplus_simulation"
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            config = (
                SimulationPathConfig(
                    output_dir=output_dir,
                    weather_dir=weather_dir,
                )
                if weather_dir is not None
                else SimulationPathConfig(output_dir=output_dir)
            )

            doc, sql = self.simulate(
                config,
                post_geometry_callback=post_geometry_callback,
            )
            try:
                results = self.standard_results_postprocess(
                    sql, ep_version_major=doc.version[0]
                )
                zone_weights, zone_names = self.get_zone_weights_and_names(doc)

                overheating_results = (
                    overheating_results_postprocess(
                        sql,
                        zone_weights=zone_weights,
                        zone_names=zone_names,
                        config=overheating_config,
                    )
                    if overheating_config is not None
                    else None
                )
            except BaseException:
                sql.close()
                raise

            err_text = self.get_warnings(output_dir)

            gc.collect()
            # if eplus_parent_dir is not None, we return the path to the output directory
            output_dir_result = output_dir if eplus_parent_dir is not None else None
            if eplus_parent_dir is None:
                # the temporary run directory is deleted on leaving this block
                sql = detach_sql(sql)

            return ModelRunResults(
                doc=doc,
                sql=sql,
                energy_and_peak=results,
                err_text=err_text,
                output_dir=output_dir_result,
                overheating_results=overheating_results,
            )

    @staticmethod
    def get_zone_weights_and_names(
        doc: EPDocument,
    ) -> tuple[NDArray[np.float64], list[str]]:
        """Get the zone weights and names from the model.

        Args:
            doc (EPDocument): The model to get the zone weights and names from.

        Returns:
            zone_weights (NDArray[np.float64]): The weights of the zones.
            zone_names (list[str]): The names of the zones.
        """
        zone_weights_: list[float] = []
        zone_names: list[str] = []
        for zone in doc["Zone"]:
            floor_area = get_zone_floor_area(doc, zone.name)
            zone_weights_.append(floor_area)
            zone_names.append(zone.name)
        zone_weights: NDArray[np.float64] = np.array(zone_weights_)
        return zone_weights, zone_names


def construct_zone_def(
    component_map_path: Path,
    db_path: Path,
    semantic_field_context: dict[str, float | str | int],
) -> ZoneComponent:
    """Construct the zone definition from a component map and database.

    Args:
        component_map_path: Path to the component map YAML file.
        db_path: Path to the component database file.
        semantic_field_context: The semantic field values used to compile the zone definition.

    Returns:
        zone_def: The zone definition for the simulation.
    """
    g = construct_graph(ZoneComponent)
    SelectorModel = construct_composer_model(
        g,
        ZoneComponent,
        use_children=False,
    )

    with open(component_map_path) as f:
        component_map_yaml = yaml.safe_load(f)
    selector = SelectorModel.model_validate(component_map_yaml)

    if db_path.exists():
        mtime = os.path.getmtime(db_path)
        mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        logger.info(
            f"Loading database: {db_path} "
            f"(modified: {mtime_str}, size: {db_path.stat().st_size} bytes)"
        )
    else:
        logger.error(f"Database file not found: {db_path}")

    settings = PrismaSettings.New(
        database_path=db_path, if_exists="ignore", auto_register=False
    )
    db = settings.db

    def _stdout_has_fileno() -> bool:
        """True if sys.stdout has a real OS file descriptor (required by Prisma on Windows in Jupyter)."""
        try:
            sys.stdout.fileno()
        except (AttributeError, io.UnsupportedOperation, OSError, ValueError):
            return False
        else:
            return True

    if not _stdout_has_fileno():
        with open(os.devnull, "w") as _devnull:
            _old_stdout, _old_stderr = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = _devnull
            try:
                with db:
                    zone = cast(
                        ZoneComponent,
                        selector.get_component(context=semantic_field_context, db=db),
                    )
            finally:
                sys.stdout, sys.stderr = _old_stdout, _old_stderr
                _devnull.close()
    else:
        with db:
            zone = cast(
                ZoneComponent,
                selector.get_component(context=semantic_field_context, db=db),
            )
    return zone


@dataclass
class ModelRunResults:
    """The results of a model run."""

    doc: EPDocument
    sql: SQLResult
    energy_and_peak: pd.Series
    err_text: str
    output_dir: Path | None
    overheating_results: OverheatingAnalysisResults | None = None

    @property
    def idf(self) -> EPDocument:
        """Deprecated alias of `doc`, the model's document."""
        warnings.warn(
            "ModelRunResults.idf is deprecated; use ModelRunResults.doc",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.doc

    def hourly_timeseries(self, names: Sequence[str]) -> pd.DataFrame:
        """Get hourly timeseries for the named output variables or meters.

        Args:
            names (Sequence[str]): The EnergyPlus output variable/meter names.

        Returns:
            pd.DataFrame: A plain pandas DataFrame of the hourly timeseries, one column per (name, key).
        """
        return timeseries_frame(self.sql, names, "Hourly")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp_dir:
        # database_path = Path("/Users/daryaguettler/globi/data/Brazil/components-lib.db")
        # component_map_path = Path(
        #     "/Users/daryaguettler/globi/data/Brazil/component-map.yaml"
        # )
        database_path = Path(
            "/Users/daryaguettler/globi/data/Portugal/components-lib.db"
        )
        component_map_path = Path(
            "/Users/daryaguettler/globi/data/Portugal/component-map.yaml"
        )
        settings = PrismaSettings(
            database_path=database_path,
            auto_register=False,
        )
        g = construct_graph(ZoneComponent)
        SelectorModel = construct_composer_model(
            g,
            ZoneComponent,
            use_children=False,
        )

        with open(component_map_path) as f:
            component_map_yaml = yaml.safe_load(f)
        selector = SelectorModel.model_validate(component_map_yaml)
        db = settings.db
        # context = {
        #     "region": "SP",
        #     "income": "Low",
        #     "typology": "Residential",
        #     "scenario": "withAC",
        # }
        context = {
            "Region": "I1_V2",
            "City": "LS",
            "Typology": "Single_Family_Residential",
            "Age_buckets": "1971_1980",
            "scenario": "Baseline",
        }
        with settings.db:
            zone = cast(ZoneComponent, selector.get_component(context=context, db=db))

        model = Model(
            Weather=(
                # "https://climate.onebuilding.org/WMO_Region_3_South_America/BRA_Brazil/SP_Sao_Paulo/BRA_SP_Guaratingueta.AP.837080_TMYx.2009-2023.zip"
                "https://climate.onebuilding.org/WMO_Region_6_Europe/PRT_Portugal/LB_Lisboa/PRT_LB_Lisboa.Portela.AP.085360_TMYx.2009-2023.zip"
            ),  # pyright: ignore [reportArgumentType]
            Zone=zone,
            Attic=AtticAssumptions(
                Conditioned=False,
                UseFraction=None,
            ),
            Basement=BasementAssumptions(
                Conditioned=False,
                UseFraction=None,
            ),
            geometry=ShoeboxGeometry(
                x=0,
                y=0,
                w=20,
                d=20,
                h=3,
                wwr=0.3,
                num_stories=1,
                basement=False,
                zoning="by_storey",
                roof_height=None,
                exposed_basement_frac=0.25,
            ),
        )

        # post_geometry_callback = lambda x: x.saveas("notebooks/badgeo.idf")

        r = model.run(
            # post_geometry_callback=post_geometry_callback,
        )
        _idf, results, _err_text, _sql, _ = (
            r.doc,
            r.energy_and_peak,
            r.err_text,
            r.sql,
            r.output_dir,
        )

        # temp_config = TemperatureOutputConfig(mode="hours_above_threshold", threshold=26.0)
        # _idf, results, _err_text, _sql = model.run(temp_config=temp_config)
        # _idf.saveas("test-out.idf")
        print(_err_text)
        print(results)

        if "Temperature" in results.index.get_level_values("Measurement"):
            zone_temp_results = results.loc["Temperature"]
            print("Zone Temperature Results:")
            print(zone_temp_results)
        else:
            print("No temperature data found in results")
            print(
                f"Available measurements: {results.index.get_level_values('Measurement').unique().tolist()}"
            )

        energy_raw = results.loc["Energy"].loc["Raw"]
        print("Energy Raw Results:")
        print(energy_raw.groupby(level=0).sum())
