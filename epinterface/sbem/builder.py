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
from typing import TYPE_CHECKING, Literal, cast, get_args
from uuid import uuid4

import numpy as np
import pandas as pd
import yaml
from idfkit.geometry import Polygon3D, get_surface_coords, set_surface_coords
from idfkit.simulation.parsers.sql import SQLResult
from idfkit.weather import load_epw
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
from epinterface.geometry import (
    ShoeboxGeometry,
    ZoneGroupLayout,
    get_zone_floor_area,
    perimeter_depth_for_share,
)
from epinterface.interface import (
    add_default_schedules,
    add_default_sim_controls,
    add_site_ground_temperature,
    add_zone_list,
)
from epinterface.results import timeseries_frame
from epinterface.sbem.archetype import (
    Archetype,
    AtticAssumptions,
    BasementAssumptions,
)
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

if TYPE_CHECKING:
    # The object classes exist only in idfkit's stubs.
    from idfkit.document import (
        AnyBuildingSurfaceDetailed,
        AnyFenestrationSurfaceDetailed,
        AnyInternalMass,
    )

logger = logging.getLogger(__name__)

IDEAL_LOADS_SYSTEM_SUFFIX = " Ideal Loads Air System"
"""Suffix of the `ZoneHVAC:IdealLoadsAirSystem` name the HVAC template gives each zone."""

SUPPLY_AIR_VOLUME_VARIABLE = (
    "Zone Ideal Loads Supply Air Standard Density Volume Flow Rate"
)
"""The ideal loads' supply air flow [m3/s] the fan end use is computed from."""

OUTDOOR_TEMPERATURE_VARIABLE = "Site Outdoor Air Drybulb Temperature"
"""The outdoor temperature a temperature-dependent energy input ratio uses."""


def epw_monthly_ground_temperatures(epw_path: Path, depth: float) -> list[float]:
    """Read the twelve monthly ground temperatures at a depth from an EPW header.

    Args:
        epw_path (Path): The EPW file.
        depth (float): The depth below grade [m], one of those the header lists.

    Returns:
        temperatures (list[float]): The monthly ground temperatures, January first [°C].

    Raises:
        KeyError: If the header lists no ground temperatures at that depth.
    """
    for ground in load_epw(epw_path).ground_temperatures:
        if np.isclose(ground.depth, depth):
            return list(ground.monthly)
    msg = f"{epw_path} lists no ground temperatures at {depth} m."
    raise KeyError(msg)


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

    @model_validator(mode="after")
    def check_internal_mass_filters(self):
        """An internal mass can only be matched on its construction name.

        `InternalMass` has no surface type, boundary condition or zone name field to
        filter on (its zone field is `zone_or_zonelist_name`).
        """
        if self.surface_group == "internal_mass" and any(
            value is not None
            for value in (
                self.boundary_condition,
                self.original_surface_type,
                self.zone_name_contains,
                self.outside_boundary_condition_object_contains,
            )
        ):
            msg = "An internal mass handler can only filter on the original construction name."
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

        Depending on the configuration of the surface handler, we look in a different collection:
        `FenestrationSurface:Detailed` for glazing, `InternalMass` for internal mass and
        `BuildingSurface:Detailed` otherwise. Windows and internal masses are matched on their
        original construction name only; the other filters name fields their types do not have.

        Args:
            doc (EPDocument): The document to add the construction to.
            construction (ConstructionAssemblyComponent | GlazingConstructionComponent): The construction to add.
        """
        if self.boundary_condition is not None and self.surface_group == "glazing":
            raise NotImplementedParameter(
                "BoundaryCondition", self.surface_group, "Glazing"
            )

        # Now we can find the matching idf objects that need a construction.
        srfs: list[
            AnyBuildingSurfaceDetailed
            | AnyFenestrationSurfaceDetailed
            | AnyInternalMass
        ]
        if self.surface_group == "glazing":
            srfs = [
                srf
                for srf in doc["FenestrationSurface:Detailed"]
                if self.check_construction_name(srf)
            ]
        elif self.surface_group == "internal_mass":
            srfs = [
                srf for srf in doc["InternalMass"] if self.check_construction_name(srf)
            ]
        else:
            srfs = [
                srf for srf in doc["BuildingSurface:Detailed"] if self.check_srf(srf)
            ]
        doc = construction.add_to_idf(doc)

        # and then we can finally assign the construction to the surfaces.
        for srf in srfs:
            srf.construction_name = construction.Name
        return doc

    def check_srf(self, srf: "AnyBuildingSurfaceDetailed"):
        """Check if the surface matches the filters.

        Args:
            srf (AnyBuildingSurfaceDetailed): The surface to check.

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

    def check_construction_type(self, srf: "AnyBuildingSurfaceDetailed"):
        """Check if the surface matches the construction type.

        Args:
            srf (AnyBuildingSurfaceDetailed): The surface to check.

        Returns:
            match (bool): True if the surface matches the construction type.
        """
        if self.original_surface_type is None:
            # Ignore the construction type check when filter not provided
            return True
        # Check the construction type
        return self.original_surface_type.lower() == (srf.surface_type or "").lower()

    def check_boundary(self, srf: "AnyBuildingSurfaceDetailed"):
        """Check if the surface matches the boundary condition.

        Args:
            srf (AnyBuildingSurfaceDetailed): The surface to check.

        Returns:
            match (bool): True if the surface matches the boundary condition.
        """
        if self.boundary_condition is None:
            # Ignore the bc filter when filter not provided
            return True
        # Check the boundary condition
        return (
            srf.outside_boundary_condition or ""
        ).lower() == self.boundary_condition.lower()

    def check_construction_name(
        self,
        srf: "AnyBuildingSurfaceDetailed | AnyFenestrationSurfaceDetailed | AnyInternalMass",
    ):
        """Check if the surface matches the original construction name.

        Args:
            srf (AnyBuildingSurfaceDetailed | AnyFenestrationSurfaceDetailed | AnyInternalMass): The surface to check.

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
    def check_zone_name(self, srf: "AnyBuildingSurfaceDetailed"):
        """Check that the zone name for the surface contains the expected substring."""
        if self.zone_name_contains is None:
            # Ignore the zone name check when filter not provided
            return True
        # Check the zone name
        zone_name = srf.zone_name or ""
        return self.zone_name_contains.lower() in zone_name.lower()

    def check_outside_boundary_condition_object(
        self, srf: "AnyBuildingSurfaceDetailed"
    ):
        """Check if the surface's outside boundary condition object contains the desired substring."""
        if self.outside_boundary_condition_object_contains is None:
            # Ignore the outside boundary condition object check when filter not provided
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
                    doc["InternalMass"].add,
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


class Model(BaseWeather, validate_assignment=True):
    """A simple model constructor for the IDF model.

    Creates geometry as well as zone definitions.
    """

    geometry: ShoeboxGeometry
    Attic: AtticAssumptions
    Basement: BasementAssumptions
    # TODO: should we have another field for whether or not the attic is ventilated, i.e. high infiltration?
    Zone: ZoneComponent
    CoreZone: ZoneComponent | None = Field(
        default=None,
        description=(
            "Zone definition of the core zones of a core/perimeter shoebox. "
            "None: `Zone` is used for every zone. The envelope assemblies, "
            "window, ground temperatures and the attic and basement zones "
            "always follow `Zone`."
        ),
    )
    GroupZones: list[ZoneComponent] | None = Field(
        default=None,
        description=(
            "Zone definition of each of the geometry's zone groups, in the order "
            "of `geometry.zone_groups`. Each group's zones take its loads, "
            "schedules, conditioning and envelope; `Zone` is the reference group, "
            "whose partition assembly is used between groups and which sets the "
            "attic, basement, ground temperatures and results post-processing."
        ),
    )

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

    @model_validator(mode="after")
    def core_zone_check(self):
        """A core zone definition needs core zones, i.e. core/perimeter zoning.

        Raises:
            ValueError
        """
        if self.CoreZone is not None and self.geometry.zoning != "core/perim":
            msg = (
                "A CoreZone needs a core/perimeter geometry; got zoning "
                f"{self.geometry.zoning!r}."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def group_zones_check(self):
        """Group zone definitions match the geometry's zone groups one to one.

        Raises:
            ValueError
        """
        groups = self.geometry.zone_groups
        if (self.GroupZones is None) != (groups is None):
            msg = (
                "GroupZones and geometry.zone_groups must be set together; got "
                f"GroupZones {'unset' if self.GroupZones is None else 'set'} and "
                f"zone_groups {'unset' if groups is None else 'set'}."
            )
            raise ValueError(msg)
        if self.GroupZones is not None and groups is not None:
            if len(self.GroupZones) != len(groups):
                msg = (
                    f"Got {len(self.GroupZones)} GroupZones for {len(groups)} zone "
                    "groups."
                )
                raise ValueError(msg)
            if self.CoreZone is not None:
                msg = "A CoreZone cannot be combined with GroupZones."
                raise ValueError(msg)
        return self

    @classmethod
    def from_archetype(
        cls, archetype: Archetype, geometry: ShoeboxGeometry, **kwargs
    ) -> "Model":
        """Build a shoebox model of an archetype.

        The archetype's groups are placed on the shoebox's zones:

        - one group: its zone definition is used for every zone;
        - two groups with exposures `perimeter` and `core`: the perimeter group's
          zone definition is `Zone`, the core group's is `CoreZone`. The geometry
          must be core/perimeter. When the shares are set, its perimeter depth
          is replaced by the depth that gives the perimeter group's floor-area
          share on the footprint. When they are unset, the geometry is used as
          it is: the core and perimeter areas follow from its width, depth and
          perimeter depth. The envelope assemblies and window come from the
          perimeter group, which holds the facade.
        - any other set of groups (shares set): the geometry gets one zone
          group per archetype group (`ShoeboxGeometry.zone_groups`), so each
          storey has one zone per group, with floor areas proportional to the
          shares: perimeter groups share the perimeter ring and core groups the
          core, or, without exposures, every group is a strip across the
          footprint. Each zone takes its group's zone definition, envelope
          included (`GroupZones`); `Zone` is the largest perimeter group (the
          largest group without exposures).

        The archetype's attic and basement assumptions are used as they are. Of
        its geometry characteristics, the window-to-wall ratios by orientation
        (`BuildingGeometry.WindowToWallRatio`), when set, replace the geometry's
        window ratio (`ShoeboxGeometry.wwr_by_orientation`): each exterior wall
        takes the ratio of the orientation it faces. The others are descriptive
        and do not change `geometry`.

        Args:
            archetype: The archetype to model.
            geometry: The shoebox to apply it to.
            **kwargs: Other `Model` fields, such as `Weather`.

        Returns:
            model: The model.

        Raises:
            ValueError: If the groups cannot be placed on the shoebox: core and
                perimeter groups on a geometry that is not core/perimeter, more
                than two groups with unset shares, or exposures set for some
                groups only.
        """
        if archetype.Geometry.WindowToWallRatio is not None:
            geometry = geometry.model_copy(
                update={
                    "wwr_by_orientation": dict(archetype.Geometry.WindowToWallRatio)
                }
            )
        groups = archetype.Groups
        if len(groups) == 1:
            return cls(
                geometry=geometry,
                Zone=groups[0].Zone,
                Attic=archetype.Attic,
                Basement=archetype.Basement,
                **kwargs,
            )
        by_exposure = {g.Exposure: g for g in groups}
        if len(groups) != 2 or set(by_exposure) != {"core", "perimeter"}:
            return cls._from_zone_groups(archetype, geometry, **kwargs)
        if geometry.zoning != "core/perim":
            msg = (
                "Core and perimeter groups need a core/perimeter geometry; got "
                f"zoning {geometry.zoning!r}."
            )
            raise ValueError(msg)
        perimeter, core = by_exposure["perimeter"], by_exposure["core"]
        if perimeter.FloorAreaShare is not None:
            geometry = geometry.model_copy(
                update={
                    "perim_depth": perimeter_depth_for_share(
                        geometry.w, geometry.d, perimeter.FloorAreaShare
                    )
                }
            )
        return cls(
            geometry=geometry,
            Zone=perimeter.Zone,
            CoreZone=core.Zone if core.Zone != perimeter.Zone else None,
            Attic=archetype.Attic,
            Basement=archetype.Basement,
            **kwargs,
        )

    @classmethod
    def _from_zone_groups(
        cls, archetype: Archetype, geometry: ShoeboxGeometry, **kwargs
    ) -> "Model":
        """Build a model with one zone per archetype group on each storey."""
        groups = archetype.Groups
        if not archetype.shares_set:
            msg = (
                "Placing more than a 'perimeter' and a 'core' group needs every "
                "group's FloorAreaShare; got unset shares for "
                f"{[g.Name for g in groups]}."
            )
            raise ValueError(msg)
        layouts = [
            ZoneGroupLayout(share=cast(float, g.FloorAreaShare), exposure=g.Exposure)
            for g in groups
        ]
        exposures = {g.Exposure for g in groups}
        if None in exposures and len(exposures) > 1:
            msg = (
                "Either every zone group has an exposure or none has; got "
                f"{[(g.Name, g.Exposure) for g in groups]}."
            )
            raise ValueError(msg)
        geometry = geometry.model_copy(update={"zone_groups": layouts})
        # the reference group holds the most facade: the largest perimeter group
        candidates = [g for g in groups if g.Exposure == "perimeter"] or groups
        reference = max(candidates, key=lambda g: cast(float, g.FloorAreaShare))
        return cls(
            geometry=geometry,
            Zone=reference.Zone,
            GroupZones=[g.Zone for g in groups],
            Attic=archetype.Attic,
            Basement=archetype.Basement,
            **kwargs,
        )

    def zone_definition(self, zone_name: str) -> ZoneComponent:
        """The zone definition used for one of the shoebox's main zones.

        Args:
            zone_name: The EnergyPlus zone name.

        Returns:
            zone: The zone group's definition for a zone of a group (`GroupZones`),
                `CoreZone` for a core zone when it is set, else `Zone`.
        """
        if self.GroupZones is not None:
            index = self.geometry.zone_group_index(zone_name)
            if index is not None:
                return self.GroupZones[index]
            return self.Zone
        if self.CoreZone is not None and "core_zone" in zone_name.lower():
            return self.CoreZone
        return self.Zone

    @property
    def zone_definitions(self) -> list[ZoneComponent]:
        """Every zone definition of the model: `Zone`, `CoreZone` and `GroupZones`."""
        definitions = [self.Zone]
        if self.CoreZone is not None:
            definitions.append(self.CoreZone)
        definitions.extend(self.GroupZones or [])
        return definitions

    @property
    def has_fan_energy(self) -> bool:
        """Whether any zone definition sets a specific fan power."""
        return any(
            z.Operations.HVAC.ConditioningSystems.SpecificFanPower is not None
            for z in self.zone_definitions
        )

    def conditioning_definition(self, zone_name: str) -> ZoneComponent:
        """The zone definition whose conditioning a zone gets.

        Attic and basement zones are conditioned as `Zone`, the reference group;
        the main zones as `zone_definition` says.

        Args:
            zone_name: The zone name, in any letter case.

        Returns:
            zone: The zone definition.
        """
        lower = zone_name.lower()
        if "attic" in lower:
            return self.Zone
        if self.geometry.basement and lower.endswith(
            self.geometry.basement_suffix.lower()
        ):
            return self.Zone
        if self.GroupZones is not None:
            index = self.geometry.zone_group_index(zone_name)
            return self.GroupZones[index] if index is not None else self.Zone
        if self.CoreZone is not None and "core_zone" in lower:
            return self.CoreZone
        return self.Zone

    def fan_energy_hourly(self, sql: SQLResult) -> NDArray[np.float64]:
        """The hourly fan electricity of the whole model [kWh/m2].

        Each zone's ideal loads supply air volume flow at standard density
        (`SUPPLY_AIR_VOLUME_VARIABLE`, the hour's mean) times the specific fan power
        of the zone's conditioning, summed over zones and divided by the total
        conditioned area. A zone whose conditioning has no specific fan power adds
        nothing.

        Args:
            sql (SQLResult): The simulation results.

        Returns:
            fan (NDArray[np.float64]): One value per hour of the run period.

        Raises:
            ValueError: If the results hold no supply air flow although a specific
                fan power is set.
        """
        frame = timeseries_frame(sql, SUPPLY_AIR_VOLUME_VARIABLE, "Hourly")
        if frame.empty:
            msg = (
                f"The results have no hourly {SUPPLY_AIR_VOLUME_VARIABLE!r}; build the "
                "model with a SpecificFanPower set."
            )
            raise ValueError(msg)
        total_w = np.zeros(len(frame))
        suffix = IDEAL_LOADS_SYSTEM_SUFFIX.upper()
        for column in frame.columns:
            key = str(column[1]).upper()
            zone_name = key[: -len(suffix)] if key.endswith(suffix) else key
            sfp = self.conditioning_definition(
                zone_name
            ).Operations.HVAC.ConditioningSystems.SpecificFanPower
            if sfp is None:
                continue
            total_w += frame[column].to_numpy(dtype=float) * sfp
        # one hour at the hour's mean power: W -> Wh -> kWh
        return total_w / 1000 / self.total_conditioned_area

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

    def add_group_constructions(self, doc: EPDocument) -> EPDocument:
        """Give each zone group's zones the group's envelope.

        `add_constructions` first gives every surface the reference envelope
        (`Zone`). Each group whose envelope differs then reassigns the surfaces of
        its own zones: facade, roof, ground slab and walls, floors and ceilings
        between its storeys and to the basement and attic, windows and internal
        mass. Walls between two groups keep the reference partition assembly, so
        both sides of a partition have the same construction.

        Args:
            doc (EPDocument): The document, with the reference envelope assigned.

        Returns:
            doc (EPDocument): The document.
        """
        if self.GroupZones is None:
            return doc
        zone_names: dict[int, set[str]] = {}
        for zone in doc["Zone"]:
            index = self.geometry.zone_group_index(zone.name)
            if index is not None:
                zone_names.setdefault(index, set()).add(zone.name)
        for index, group_zone in enumerate(self.GroupZones):
            if group_zone.Envelope == self.Zone.Envelope:
                continue
            doc = assign_zone_envelope(
                doc,
                zone_names.get(index, set()),
                group_zone.Envelope.Assemblies,
                group_zone.Envelope.Window,
                with_attic=(self.geometry.roof_height or 0) > 0,
                basement_suffix=self.geometry.basement_suffix
                if self.geometry.basement
                else None,
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
        if self.has_fan_energy:
            doc["Output:Variable"].add(
                key_value="*",
                variable_name=SUPPLY_AIR_VOLUME_VARIABLE,
                reporting_frequency="Hourly",
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
            self.zone_definition(zone).add_to_idf_zone(doc, zone)

        # Handle setting ground temperature
        subtractor = (
            4 if (self.geometry.basement and not self.Basement.Conditioned) else 2
        )
        has_heating = self.Zone.Operations.HVAC.ConditioningSystems.Heating is not None
        has_cooling = self.Zone.Operations.HVAC.ConditioningSystems.Cooling is not None
        hsp = self.Zone.Operations.SpaceUse.Thermostat.HeatingSchedule
        csp = self.Zone.Operations.SpaceUse.Thermostat.CoolingSchedule
        # if there is a basement, we use the 4m depth to account for the basement depth;
        # otherwise the 0.5m depth.
        epw_ground_vals = epw_monthly_ground_temperatures(
            epw_path, 4 if self.geometry.basement else 0.5
        )
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
                new_zone_def.Operations.HVAC.Ventilation.IsScheduledVentilationOn = (
                    False
                )
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
                new_zone_def.Operations.HVAC.Ventilation.IsScheduledVentilationOn = (
                    False
                )
                new_zone_def.Operations.HVAC.ConditioningSystems.Heating = None
                new_zone_def.Operations.HVAC.ConditioningSystems.Cooling = None

            # TODO: handle mutating infiltration object when "ventilated attics" are set
            for zone in added_zone_lists.attic_zone_list:
                new_zone_def.add_to_idf_zone(doc, zone)

        doc = self.add_constructions(
            doc, self.Zone.Envelope.Assemblies, self.Zone.Envelope.Window
        )
        if self.GroupZones is not None:
            doc = self.add_group_constructions(doc)

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

        Heating and cooling use is delivered energy times the reference zone's
        energy input ratio: 1 / effective COP, or, with an `EIRTemperatureSlope`,
        a ratio linear in each hour's outdoor temperature
        (`ThermalSystemComponent.energy_input_ratio`). When a zone definition sets a
        `SpecificFanPower`, a "Fans" end use (`fan_energy_hourly`) is added and
        counted as electricity.

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
        heat_eir_hourly = cool_eir_hourly = None
        sloped_heat = (
            cond_sys.Heating
            if cond_sys.Heating is not None
            and cond_sys.Heating.EIRTemperatureSlope != 0
            else None
        )
        sloped_cool = (
            cond_sys.Cooling
            if cond_sys.Cooling is not None
            and cond_sys.Cooling.EIRTemperatureSlope != 0
            else None
        )
        if sloped_heat is not None or sloped_cool is not None:
            outdoor = timeseries_frame(sql, OUTDOOR_TEMPERATURE_VARIABLE, "Hourly")
            if outdoor.empty:
                msg = f"The results have no hourly {OUTDOOR_TEMPERATURE_VARIABLE!r}."
                raise ValueError(msg)
            t_out = outdoor.iloc[:, 0].to_numpy(dtype=float)
            if sloped_heat is not None:
                heat_eir_hourly = sloped_heat.energy_input_ratio(t_out)
            if sloped_cool is not None:
                cool_eir_hourly = sloped_cool.energy_input_ratio(t_out)
        fan_hourly = self.fan_energy_hourly(sql) if self.has_fan_energy else None
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
            heat_eir_hourly=heat_eir_hourly,
            cool_eir_hourly=cool_eir_hourly,
            fan_hourly=fan_hourly,
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


def assign_zone_envelope(  # noqa: C901
    doc: EPDocument,
    zone_names: set[str],
    constructions: EnvelopeAssemblyComponent,
    window: GlazingConstructionSimpleComponent | None,
    with_attic: bool,
    basement_suffix: str | None,
) -> EPDocument:
    """Assign an envelope to the surfaces of some zones only.

    The surfaces of the zones get the assemblies `SurfaceHandlers.handle_envelope`
    would give them, except walls to other zones (partitions), which are left as
    they are. Floors and ceilings are reassigned only when the zone on their other
    side is one of `zone_names`, the basement below them or the attic above them,
    so both sides of every interzone surface stay consistent.

    Args:
        doc (EPDocument): The document.
        zone_names (set[str]): The zones to reassign.
        constructions (EnvelopeAssemblyComponent): Their assemblies.
        window (GlazingConstructionSimpleComponent | None): Their window; None
            leaves the windows as they are.
        with_attic (bool): Whether the model has an attic.
        basement_suffix (str | None): The basement zone name suffix, or None
            without a basement.

    Returns:
        doc (EPDocument): The document.
    """

    def is_basement(zone_name: str) -> bool:
        return basement_suffix is not None and zone_name.lower().endswith(
            basement_suffix.lower()
        )

    def is_attic(zone_name: str) -> bool:
        return "attic" in zone_name.lower()

    surfaces = doc["BuildingSurface:Detailed"]
    zone_of = {srf.name: srf.zone_name or "" for srf in surfaces}
    assignments: list[
        tuple[AnyBuildingSurfaceDetailed, ConstructionAssemblyComponent]
    ] = []
    for srf in surfaces:
        zone = srf.zone_name or ""
        own = zone in zone_names
        kind = (srf.surface_type or "").lower()
        bc = (srf.outside_boundary_condition or "").lower()
        other = zone_of.get(srf.outside_boundary_condition_object or "", "")
        chosen: ConstructionAssemblyComponent | None = None
        if own and kind == "roof" and bc == "outdoors":
            chosen = (
                constructions.AtticRoofAssembly
                if with_attic
                else constructions.FlatRoofAssembly
            )
        elif own and kind == "wall" and bc in ("outdoors", "ground"):
            # exposed basement walls keep the ground wall assembly, as in
            # handle_envelope
            chosen = (
                constructions.GroundWallAssembly
                if bc == "ground" or is_basement(zone)
                else constructions.FacadeAssembly
            )
        elif own and kind == "floor" and bc == "ground":
            chosen = constructions.GroundSlabAssembly
        elif bc == "surface" and kind in ("floor", "ceiling"):
            if own and other in zone_names:
                if kind == "ceiling" and is_basement(zone):
                    chosen = constructions.BasementCeilingAssembly
                elif kind == "floor" and is_basement(other):
                    chosen = constructions.BasementCeilingAssembly.reversed
                elif kind == "ceiling":
                    chosen = constructions.FloorCeilingAssembly
                else:
                    chosen = constructions.FloorCeilingAssembly.reversed
            elif own and kind == "ceiling" and is_attic(other):
                chosen = constructions.AtticFloorAssembly.reversed
            elif is_attic(zone) and kind == "floor" and other in zone_names:
                chosen = constructions.AtticFloorAssembly
        if chosen is not None:
            assignments.append((srf, chosen))
    added: set[str] = set()
    for srf, construction in assignments:
        if construction.Name not in added:
            doc = construction.add_to_idf(doc)
            added.add(construction.Name)
        srf.construction_name = construction.Name

    if window is not None:
        windows = [
            win
            for win in doc["FenestrationSurface:Detailed"]
            if zone_of.get(win.building_surface_name or "", "") in zone_names
        ]
        if windows:
            doc = window.add_to_idf(doc)
            for win in windows:
                win.construction_name = window.Name

    for zone_name in sorted(zone_names):
        mass_name = f"{zone_name}_InternalMass"
        if constructions.InternalMassAssembly is None:
            existing = doc["InternalMass"].get(mass_name)
            if existing is not None:
                doc.removeidfobject(existing)
            continue
        if constructions.InternalMassAssembly.Name not in added:
            doc = constructions.InternalMassAssembly.add_to_idf(doc)
            added.add(constructions.InternalMassAssembly.Name)
        add_or_replace(
            doc["InternalMass"].add,
            mass_name,
            construction_name=constructions.InternalMassAssembly.Name,
            zone_or_zonelist_name=zone_name,
            surface_area=float(
                get_zone_floor_area(doc, zone_name)
                * (constructions.InternalMassExposedAreaPerArea or 0)
            ),
        )
    return doc


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

    # Imported here so that the builder can be imported without a generated
    # Prisma client; only reading a component database needs one.
    from epinterface.sbem.prisma.client import PrismaSettings

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
    from epinterface.sbem.prisma.client import PrismaSettings

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
