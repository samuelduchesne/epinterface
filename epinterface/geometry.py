"""Geometry utilities for the UBEM construction."""

import re
import warnings
from collections.abc import Sequence
from typing import Literal, cast

import numpy as np
from idfkit import (
    IDFDocument,
    IDFObject,
    MatchOptions,
    Polygon3D,
    Vector3D,
    add_shading_block,
    bounding_box,
    calculate_surface_area,
    intersect_and_match,
    rotate_building,
    scale_building,
    translate_building,
)
from idfkit.geometry import get_surface_coords, set_surface_coords
from idfkit.zoning import ZoningScheme, create_block
from numpy.typing import ArrayLike
from pydantic import BaseModel, Field
from shapely import LineString, Polygon, from_wkt
from shapely.affinity import translate

from epinterface.interface import Construction, Material, SimpleGlazingMaterial


def _total_floor_area(doc: IDFDocument) -> float:
    """Sum the areas of all floor surfaces in the document [m2]."""
    return sum(
        calculate_surface_area(srf)
        for srf in doc["BuildingSurface:Detailed"]
        if (srf.surface_type or "").lower() == "floor"
    )


def match_idf_to_building_and_neighbors(
    doc: IDFDocument,
    building: Polygon | str,
    neighbor_polys: Sequence[Polygon | str | None],
    neighbor_floors: Sequence[float | int | None],
    neighbor_f2f_height: float,
    target_short_length: float,
    target_long_length: float,
    rotation_angle: float,
    allow_no_height: bool = False,
) -> IDFDocument:
    """Match an IDF model to a building and neighbors by scaling and rotating the IDF model and adding shading blocks for neighbors.

    Args:
        doc (IDFDocument): The IDF document to match.
        building (Polygon | str): The building to match.
        neighbor_polys (list[Polygon | str | None]): The neighbors to inject as shading.
        neighbor_floors (list[float | int | None]): The counts of the neighbors.
        neighbor_f2f_height (float | None): The height of the building to match
        target_short_length (float): The target short length of the building.
        target_long_length (float): The target long length of the building.
        rotation_angle (float): The rotation angle of the building (radians).
        allow_no_height (bool): Whether to allow no height for neighbors.

    Returns:
        doc (IDFDocument): The matched IDF document.
    """
    building_geo = (
        cast(Polygon, from_wkt(building)) if isinstance(building, str) else building
    )
    neighbor_geos = [
        (cast(Polygon, from_wkt(n)), h * neighbor_f2f_height)
        if isinstance(n, str)
        else (n, h * neighbor_f2f_height)
        for n, h in zip(neighbor_polys, neighbor_floors, strict=True)
        if n is not None and h is not None
    ]
    centroid = building_geo.centroid
    translated_neighbors = [
        (translate(n, xoff=-centroid.x, yoff=-centroid.y), h) for n, h in neighbor_geos
    ]
    bbox = bounding_box(doc)
    if bbox is None:
        msg = "The IDF document has no building surfaces to match."
        raise ValueError(msg)
    (x_min, y_min), (x_max, y_max) = bbox
    x_span = x_max - x_min
    y_span = y_max - y_min
    # TODO: better handling for boxes that aren't [(0,0),...]
    if x_span < y_span:
        raise NotImplementedError(
            "This function assumes that the long edge is the x-axis, which is not the case."
        )
    if abs(x_min) > 1e-3 or abs(y_min) > 1e-3:
        raise NotImplementedError(
            "This function assumes that the building has the lowerleft corner at the origin, which is not the case."
        )

    long_length = x_span
    short_length = y_span

    if not np.isclose(long_length, target_long_length):
        warnings.warn(
            f"Long length mismatch: {long_length} != {target_long_length}, perim zones may be distorted",
            stacklevel=2,
        )
    if not np.isclose(short_length, target_short_length):
        warnings.warn(
            f"Short length mismatch: {short_length} != {target_short_length}, perim zones may be distorted",
            stacklevel=2,
        )
    scale_building(
        doc,
        (target_long_length / long_length, target_short_length / short_length, 1.0),
        anchor=Vector3D(0, 0, 0),
    )
    # This translation makes an assumption that the source building is at [(0,0),(0,w),...]
    translate_building(
        doc, Vector3D(-target_long_length / 2, -target_short_length / 2, 0)
    )
    rotate_building(doc, rotation_angle * 180 / np.pi)
    for i, (geom, height) in enumerate(translated_neighbors):
        if not height and not allow_no_height:
            height = 3.5 * 2
        if np.isnan(height):
            height = 3.5 * 2
        if height != 0:
            footprint = [(x, y) for x, y in geom.exterior.coords[:-1]]
            _add_shading_walls(doc, f"shading_{i}", footprint, height)
    return doc


def _add_shading_walls(
    doc: IDFDocument, name: str, footprint: list[tuple[float, float]], height: float
) -> None:
    """Add the walls of a shading block (geomeppy added no top cap)."""
    for obj in add_shading_block(doc, name=name, footprint=footprint, height=height):
        if obj.name == f"{name} Top":
            doc.removeidfobject(obj)


def compute_shading_mask(
    building: Polygon | str,
    neighbors: Sequence[Polygon | str | None],
    neighbor_heights: Sequence[float | int | None],
    azimuthal_angle: float,
) -> np.ndarray:
    """Compute the shading mask for the building.

    This will emit a ray from the center of the building in
    every direction according to the azimuthal angle division
    of a circle.

    It will compute the intersection of each ray with all the neighbor edges,
    and then determine the height of the each edge that intersects the ray.

    That height is then used to determine an elevation angle; the max of the elevation
    angles for each ray is then the shading mask value for that direction.

    Note that this checks all edges, so its crucial that the neighbors have
    already been culled to the relevant building to avoid unnecessary computation.

    Args:
        building (Polygon | str): The building to compute the shading mask for.
        neighbors (list[Polygon | str | None]): The neighbors to compute the shading mask for.
        neighbor_heights (list[float | int | None]): The heights of the neighbors.
        azimuthal_angle (float): The azimuthal angle to compute the shading mask for.

    Returns:
        shading_mask (np.ndarray): The shading mask for the building.
    """
    building_geom = building if isinstance(building, Polygon) else from_wkt(building)

    neighbor_geo_and_height = [
        (cast(Polygon, from_wkt(n)), float(h)) if isinstance(n, str) else (n, float(h))
        for n, h in zip(neighbors, neighbor_heights, strict=True)
        if n is not None and h is not None
    ]
    safe_neighbor_geoms = [geom for geom, _ in neighbor_geo_and_height]
    safe_neighbor_heights = [height for _, height in neighbor_geo_and_height]

    # first we compute the number of rays we need to cast
    # along with the angles at which to cast them
    n_rays = int(2 * np.pi / azimuthal_angle)
    ray_angles = np.linspace(0, 2 * np.pi - azimuthal_angle, n_rays)
    ray_distance = 9999  # an arbitrarily large distance

    # extract the relevant geometry data
    centroid = building_geom.centroid

    shading_mask = np.zeros(n_rays)

    for ray_angle_idx, ray_angle in enumerate(ray_angles):
        # create the ray as a line segment
        # using basic trig
        x_off, y_off = (
            ray_distance * np.cos(ray_angle),
            ray_distance * np.sin(ray_angle),
        )
        centroid_moved = translate(centroid, x_off, y_off)
        ray = LineString([centroid, centroid_moved])

        # track the max elevation angle for this ray so far
        max_elevation_angle = 0

        for geom, height in zip(
            safe_neighbor_geoms, safe_neighbor_heights, strict=True
        ):
            # create the line segments of the boundary
            x_coords = np.array(geom.boundary.xy[0])
            y_coords = np.array(geom.boundary.xy[1])

            for x0, y0, x1, y1 in zip(
                x_coords[:-1],
                y_coords[:-1],
                x_coords[1:],
                y_coords[1:],
                strict=True,
            ):
                line = LineString([(x0, y0), (x1, y1)])

                # compute the intersection and continue
                # if there is no intersection
                intersection = ray.intersection(line)
                if intersection.is_empty:
                    continue

                # compute the elevation angle and store it if it
                # is greater than the current max
                distance = intersection.distance(centroid)
                elevation_angle = np.arctan2(height, distance)
                max_elevation_angle = max(max_elevation_angle, elevation_angle)

        shading_mask[ray_angle_idx] = max_elevation_angle
    return shading_mask


def shading_fence_closed_ring(
    elevations: ArrayLike,
    d: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Construct N vertical 'shading fence' rectangles whose bases are tangent segments forming a closed regular polygon around a circle of radius d.

    Inputs:
      elevations: (N,) elevation angles theta_k [radians]
      d: radius to tangency points (base midpoints)

    Outputs:
      azimuths: (N,) inferred azimuths alpha_k = 2πk/N
      p0:       (N, 2) base endpoint A (x,y)
      p1:       (N, 2) base endpoint B (x,y)
      h:        (N,) heights h_k = d * tan(theta_k)
      w:        scalar side length / segment width = 2 d tan(π/N)

    Notes:
      - With this construction, the segments intersect/meet: p1[k] == p0[k+1] (cyclic),
        up to floating point tolerance.
      - N must be >= 3 for a closed polygon.
    """
    theta = np.asarray(elevations, dtype=np.float64)
    if theta.ndim != 1:
        msg = f"elevations must be 1D, got shape {theta.shape}"
        raise ValueError(msg)

    N = theta.shape[0]
    if N < 3:
        msg = "Need at least 3 elevations (N >= 3) to form a closed ring."
        raise ValueError(msg)

    # Inferred equally spaced azimuths
    k = np.arange(N, dtype=np.float64)
    azimuths = 2.0 * np.pi * k / N

    ca, sa = np.cos(azimuths), np.sin(azimuths)

    # Tangency points (base midpoints) on circle radius d
    px = d * ca
    py = d * sa

    # Unit tangent direction (perpendicular to radius)
    tx = -sa
    ty = ca

    # Choose width so adjacent tangent segments meet (circumscribed regular N-gon)
    half_w = d * np.tan(np.pi / N)
    w = 2.0 * half_w

    # Endpoints in xy: p ± half_w * t
    p0 = np.stack([px - half_w * tx, py - half_w * ty], axis=-1)
    p1 = np.stack([px + half_w * tx, py + half_w * ty], axis=-1)

    # Heights from elevation angles
    h = d * np.tan(theta)

    return azimuths, p0, p1, h, w


def prepare_neighbor_shading_for_idf(
    building: Polygon | str,
    neighbors: Sequence[Polygon | str | None],
    neighbor_heights: Sequence[float | int | None],
    *,
    azimuthal_angle: float = 2 * np.pi / 48,
    fence_radius: float = 100,
    outward_offset: float = 2,
    f2f_height: float,
) -> tuple[list[Polygon], list[int]]:
    """Prepare neighbor polygons and floor counts for match_idf_to_building_and_neighbors.

    Computes a shading mask from the building and neighbors, converts it to shading fence
    quadrilaterals, and returns polygons plus floor counts suitable for IDF shading blocks.

    Args:
        building: The building polygon (or WKT string).
        neighbors: Neighbor polygons (or WKT strings).
        neighbor_heights: Heights of each neighbor [m].
        azimuthal_angle: Angular spacing for shading rays (default 2π/48).
        fence_radius: Radius for shading fence tangency points.
        outward_offset: Distance to extend fence quadrilaterals outward.
        f2f_height: Floor-to-floor height for converting heights to floor counts.

    Returns:
        mask_polys: List of Shapely Polygons (quadrilaterals) for each shading fence.
        neighbor_floors: List of floor counts (int) for each fence.
    """
    shading_mask = compute_shading_mask(
        building, neighbors, neighbor_heights, azimuthal_angle
    )
    az, p0, p1, h, _w = shading_fence_closed_ring(
        elevations=shading_mask, d=fence_radius
    )

    building_geom = building if isinstance(building, Polygon) else from_wkt(building)
    centroid = building_geom.centroid
    cx, cy = centroid.x, centroid.y

    angles = 2 * np.pi * np.arange(len(az)) / len(az)
    outward = np.stack([np.cos(angles), np.sin(angles)], axis=-1)
    p2 = p1 + outward_offset * outward
    p3 = p0 + outward_offset * outward

    mask_polys = [
        Polygon([
            (p0[i, 0] + cx, p0[i, 1] + cy),
            (p1[i, 0] + cx, p1[i, 1] + cy),
            (p2[i, 0] + cx, p2[i, 1] + cy),
            (p3[i, 0] + cx, p3[i, 1] + cy),
            (p0[i, 0] + cx, p0[i, 1] + cy),
        ])
        for i in range(len(az))
    ]
    neighbor_floors = [int(h[i] // f2f_height) for i in range(len(h))]

    return mask_polys, neighbor_floors


ZoningType = Literal["core/perim", "by_storey"]


class SceneContext(BaseModel, arbitrary_types_allowed=True):
    """A context for the scene."""

    building: Polygon = Field(..., description="The building polygon to match.")
    neighbors: list[Polygon] = Field(..., description="The neighbor polygons to match.")
    neighbor_heights: list[float] = Field(
        ..., description="The heights of the neighbors."
    )
    orientation: float = Field(
        ...,
        description="The orientation of the building's long edge (radians).",
    )
    azimuthal_angle: float = Field(
        default=2 * np.pi / 48,
        description="The azimuthal angle for the shading mask (radians).",
    )


class ShoeboxGeometry(BaseModel):
    """A simple shoebox constructor for the IDF model.

    Can create gables, basements, and various zoning strategies.
    """

    x: float
    y: float
    w: float
    d: float
    h: float
    num_stories: int = Field(
        ...,
        title="Number of stories",
        ge=1,
        description="The number of stories in the building.",
    )
    zoning: ZoningType = Field(
        ...,
        title="Zoning type",
        description="Whether to use core/perim or full-floor zones.",
    )
    perim_depth: float = Field(
        default=3,
        title="Perimeter depth",
        description="Sets the perimeter depth when using core/perim zoning.  Ignored otherwise.",
    )
    roof_height: float | None = Field(
        default=None,
        title="Roof gable height",
        description="The height of the roof gable.  If None, a flat roof is assumed.",
    )
    basement: bool = Field(
        default=False,
        title="Basement",
        description="Whether or not to use a basement with same f2f height as building.",
    )
    exposed_basement_frac: float = Field(
        default=0.0,
        title="Exposed basement fraction",
        description="The fraction of the basement that is exposed.",
        ge=0,
        lt=1,
    )
    wwr: float = Field(
        default=0.15,
        title="Window-to-wall ratio",
        description="The window-to-wall ratio of the building.",
        ge=0,
        le=1,
    )
    scene_context: SceneContext | None = Field(
        default=None, description="The context for the scene."
    )

    @property
    def basement_storey_count(self) -> int:
        """Return the number of basement stories."""
        return 1 if self.basement else 0

    @property
    def attic_storey_count(self) -> int:
        """Return the number of attic stories."""
        return 1 if self.roof_height else 0

    @property
    def zones_height(self) -> float:
        """Return the total height of the zones, excluding any gabling."""
        return self.h * (self.num_stories)

    @property
    def total_height_with_gabling(self) -> float:
        """Return the total height of the building, including any gabling."""
        return self.zones_height + (self.roof_height or 0)

    @property
    def footprint_area(self) -> float:
        """Return the total floor area of the building."""
        return self.w * self.d

    @property
    def total_living_area(self) -> float:
        """Return the total living area of the building (does not include attic/basement)."""
        return self.footprint_area * self.num_stories

    @property
    def total_area(self) -> float:
        """Return the total area of the building."""
        return (
            self.total_living_area
            + self.footprint_area * self.basement_storey_count
            + self.footprint_area * (1 if self.roof_height else 0)
        )

    @property
    def basement_suffix(self) -> str:
        """Return the basement suffix for the building."""
        if not self.basement:
            msg = "Building has no basement."
            raise ValueError(msg)
        return "Storey 0" if self.zoning == "core/perim" else "Storey -1"

    @property
    def zones_per_storey(self) -> int:
        """Return the number of zones per storey."""
        if self.zoning == "core/perim":
            return 5
        else:
            return 1

    def add(self, doc: IDFDocument) -> IDFDocument:
        """Constructs a simple shoebox geometry in the IDF document.

        Zones are built with idfkit's `create_block`; the result reproduces the
        geometry, zone names and zone order of the geomeppy implementation it
        replaces.

        Can create gables, basements, and various zoning strategies.

        Args:
            doc: The IDF document to add the geometry to.

        Returns:
            The IDF document with the added geometry.
        """
        footprint = [
            (self.x, self.y),
            (self.x + self.w, self.y),
            (self.x + self.w, self.y + self.d),
            (self.x, self.y + self.d),
        ]
        storey_count = self.num_stories + self.basement_storey_count
        created = create_block(
            doc,
            name="shoebox",
            footprint=footprint,
            floor_to_floor=self.h,
            num_stories=storey_count,
            zoning=ZoningScheme.CORE_PERIMETER
            if self.zoning == "core/perim"
            else ZoningScheme.BY_STOREY,
            perimeter_depth=self.perim_depth,
        )
        zones = [obj for obj in created if obj.obj_type == "Zone"]
        surfaces = [
            obj for obj in created if obj.obj_type == "BuildingSurface:Detailed"
        ]
        if len(zones) != storey_count * self.zones_per_storey:
            msg = (
                f"Expected {storey_count * self.zones_per_storey} zones but found "
                f"{len(zones)}; the perimeter depth may be too large for the footprint."
            )
            raise ValueError(msg)

        if self.basement:
            # idfkit builds no below-ground storeys: the lowest storey becomes the
            # basement by moving the block down one storey and burying its walls.
            self._bury_lowest_storey(zones[: self.zones_per_storey], surfaces)

        attic_floors = self._add_attic(doc, surfaces) if self.roof_height else []

        # create_block's surfaces already share exact vertices; a fine snapping
        # grid keeps them exact (the default 0.1 mm grid shifts diagonal walls).
        report = intersect_and_match(doc, MatchOptions(snap_tol=1e-9))
        if report.surfaces_split or report.fragments_created:
            msg = (
                "Surface matching unexpectedly split the shoebox surfaces "
                f"({report.surfaces_split} split, {report.fragments_created} created)."
            )
            raise ValueError(msg)
        for floor in attic_floors:
            if floor.outside_boundary_condition.lower() != "surface":
                msg = f"Attic floor {floor.name} was not matched to a ceiling below."
                raise ValueError(msg)

        self._rename_like_geomeppy(doc, zones, surfaces, attic_floors)

        _set_default_constructions(doc)

        # Handle Windows
        if self.wwr:
            window_walls = [
                w
                for w in doc["BuildingSurface:Detailed"]
                if (w.outside_boundary_condition or "").lower() == "outdoors"
                and "attic" not in (w.zone_name or "").lower()
                and (
                    not (w.zone_name or "")
                    .lower()
                    .endswith(self.basement_suffix.lower())
                    if self.basement
                    else True
                )
                and (w.surface_type or "").lower() == "wall"
            ]
            for wall in window_walls:
                _add_window(doc, wall, self.wwr)

        if self.scene_context:
            mask_polys, neighbor_floors = prepare_neighbor_shading_for_idf(
                building=self.scene_context.building,
                neighbors=self.scene_context.neighbors,
                neighbor_heights=self.scene_context.neighbor_heights,
                azimuthal_angle=self.scene_context.azimuthal_angle,
                fence_radius=100,
                outward_offset=2,
                f2f_height=self.h,
            )
            original_building_area = _total_floor_area(doc)
            doc = match_idf_to_building_and_neighbors(
                doc,
                building=self.scene_context.building,
                neighbor_polys=mask_polys,
                neighbor_floors=neighbor_floors,
                neighbor_f2f_height=self.h,
                target_short_length=self.d,
                target_long_length=self.w,
                rotation_angle=self.scene_context.orientation,
                allow_no_height=True,
            )
            new_building_area = _total_floor_area(doc)
            if not np.isclose(original_building_area, new_building_area):
                msg = f"Total building area mismatch after matching to building and neighbors: {original_building_area} != {new_building_area}"
                raise ValueError(msg)

        return doc

    def _bury_lowest_storey(
        self, basement_zones: list[IDFObject], surfaces: list[IDFObject]
    ) -> None:
        """Move the block down one storey and put its lowest storey in the ground."""
        offset = Vector3D(0, 0, -self.h)
        for srf in surfaces:
            set_surface_coords(
                srf, cast(Polygon3D, get_surface_coords(srf)).translate(offset)
            )
        basement_zone_names = {zone.name for zone in basement_zones}
        for srf in surfaces:
            if (
                srf.zone_name in basement_zone_names
                and srf.outside_boundary_condition.lower() == "outdoors"
            ):
                srf.outside_boundary_condition = "Ground"
                srf.sun_exposure = "NoSun"
                srf.wind_exposure = "NoWind"

    def _add_attic(
        self, doc: IDFDocument, surfaces: list[IDFObject]
    ) -> list[IDFObject]:
        """Add a gabled attic zone on top of the block.

        The block's roofs become ceilings, and the attic gets one floor per
        ceiling with the same footprint so that matching pairs them one to one.

        Returns:
            The attic floor surfaces.
        """
        # we need to convert the old roof surfaces to ceilings;
        # additionally, we will track them so that we can create the
        # corresponding floor surfaces for the attic in a manner
        # that avoids having to subdivide surfaces with intersect/match
        old_roof_srfs = [srf for srf in surfaces if srf.surface_type.lower() == "roof"]
        if len(old_roof_srfs) not in [1, 5]:
            msg = (
                "Too many roof surfaces were found; expected 1 (by_storey) or 5 "
                f" (core/perim), but found {len(old_roof_srfs)}."
            )
            raise ValueError(msg)
        for srf in old_roof_srfs:
            srf.surface_type = "Ceiling"

        # create the zone
        doc.add("Zone", "Attic")

        # we always want the centerline of a gable to be paralle to the longer
        # edge
        centerline_parallel_to = "w" if self.w > self.d else "d"

        # the centerline is the midpoint of the shorter edge
        # since it is parallel to the longer edge
        roof_centerline = (
            (self.x + self.w / 2)
            if centerline_parallel_to == "d"
            else (self.y + self.d / 2)
        )
        x0, x1 = self.x, self.x + self.w
        y0, y1 = self.y, self.y + self.d
        z_eave, z_ridge = self.zones_height, self.total_height_with_gabling

        if centerline_parallel_to == "d":
            # the gables run from the left and right edges of the building to the
            # ridge at the midpoint of the x-axis; each starts at the eave and
            # goes counter clockwise, then up to the ridge.
            gable1 = [
                (x0, y1, z_eave),
                (x0, y0, z_eave),
                (roof_centerline, y0, z_ridge),
                (roof_centerline, y1, z_ridge),
            ]
            gable2 = [
                (x1, y0, z_eave),
                (x1, y1, z_eave),
                (roof_centerline, y1, z_ridge),
                (roof_centerline, y0, z_ridge),
            ]
            # triangular endcaps
            endcap1 = [
                (x0, y0, z_eave),
                (x1, y0, z_eave),
                (roof_centerline, y0, z_ridge),
            ]
            endcap2 = [
                (x1, y1, z_eave),
                (x0, y1, z_eave),
                (roof_centerline, y1, z_ridge),
            ]
        else:
            # the gables run from the ridge at the middle of the left edge counter
            # clockwise down to the eave and back up.
            gable1 = [
                (x0, roof_centerline, z_ridge),
                (x0, y0, z_eave),
                (x1, y0, z_eave),
                (x1, roof_centerline, z_ridge),
            ]
            gable2 = [
                (x0, roof_centerline, z_ridge),
                (x1, roof_centerline, z_ridge),
                (x1, y1, z_eave),
                (x0, y1, z_eave),
            ]
            # triangular endcaps
            endcap1 = [
                (x0, y0, z_eave),
                (x0, roof_centerline, z_ridge),
                (x0, y1, z_eave),
            ]
            endcap2 = [
                (x1, y0, z_eave),
                (x1, y1, z_eave),
                (x1, roof_centerline, z_ridge),
            ]

        for name, surface_type, vertices in (
            ("Gable1", "Roof", gable1),
            ("Gable2", "Roof", gable2),
            ("Endcap1", "Wall", endcap1),
            ("Endcap2", "Wall", endcap2),
        ):
            srf = doc.add(
                "BuildingSurface:Detailed",
                name,
                surface_type=surface_type,
                construction_name="",
                zone_name="Attic",
                outside_boundary_condition="Outdoors",
                sun_exposure="SunExposed",
                wind_exposure="WindExposed",
                # like create_block's surfaces: no construction or vertices yet
                validate=False,
            )
            set_surface_coords(srf, Polygon3D.from_tuples(vertices))

        # We will create identical floor surfaces for the attic to match
        # the zone below.  While we could just add a single plane and let
        # the surface matching handle it, this is more robust; it avoids
        # numerical floating point errors where a very small overhang area
        # is created with an outside boundary condition.
        # we use a vertex order of 1, 4, 3, 2 to match the orientation of the
        # roof surfaces below it, i.e. CCW vs CW.
        attic_floors = []
        for i, srf in enumerate(old_roof_srfs):
            v = cast(Polygon3D, get_surface_coords(srf)).vertices
            floor = doc.add(
                "BuildingSurface:Detailed",
                f"attic_bottom_plane_{i}",
                surface_type="Floor",
                construction_name="",
                zone_name="Attic",
                outside_boundary_condition="Outdoors",
                sun_exposure="NoSun",
                wind_exposure="NoWind",
                validate=False,
            )
            set_surface_coords(floor, Polygon3D([v[0], v[3], v[2], v[1]]))
            attic_floors.append(floor)
        return attic_floors

    def _rename_like_geomeppy(
        self,
        doc: IDFDocument,
        zones: list[IDFObject],
        surfaces: list[IDFObject],
        attic_floors: list[IDFObject],
    ) -> None:
        """Give the block's zones and surfaces geomeppy's names, in geomeppy's zone order.

        Surface names keep the zone name in them, which the construction
        handlers rely on (e.g. the basement suffix and "attic").

        `create_block` lists zones storey by storey while geomeppy listed
        core/perim zones zone by zone. The zone objects hold nothing but their
        name, so they are reordered by pointing each surface at its geomeppy
        zone name and then naming the zone objects in geomeppy's order.
        """
        zones_per_storey = self.zones_per_storey
        index_of = {zone.name: k for k, zone in enumerate(zones)}
        new_zone_names = [
            _geomeppy_zone_name(
                k // zones_per_storey, k % zones_per_storey, self.zoning, self.basement
            )
            for k in range(len(zones))
        ]
        for srf in surfaces:
            k = index_of[srf.zone_name]
            is_perimeter = self.zoning == "core/perim" and k % zones_per_storey < 4
            new_name = _geomeppy_surface_name(
                new_zone_names[k],
                srf.name.removeprefix(f"{srf.zone_name} "),
                is_perimeter,
            )
            if srf.outside_boundary_condition.lower() == "surface":
                new_name += "_1"
            doc.rename("BuildingSurface:Detailed", srf.name, new_name)
            srf.zone_name = new_zone_names[k]
        for floor in attic_floors:
            # geomeppy's surface matching suffixed every matched surface with _1
            doc.rename("BuildingSurface:Detailed", floor.name, f"{floor.name}_1")

        ordered_names = [
            new_zone_names[k]
            for k in sorted(
                range(len(zones)),
                key=lambda k: (k % zones_per_storey, k // zones_per_storey),
            )
        ]
        for zone, new_name in zip(zones, ordered_names, strict=True):
            doc.rename("Zone", zone.name, new_name)


_DEFAULT_MATERIAL = Material(
    Name="DefaultMaterial",
    Roughness="Rough",
    Thickness=0.1,
    Conductivity=0.1,
    Density=1000,
    Specific_Heat=1000,
)
_DEFAULT_OPAQUE_CONSTRUCTIONS = (
    "Project Wall",
    "Project Partition",
    "Project Floor",
    "Project Flat Roof",
    "Project Ceiling",
    "Project Door",
)
_DEFAULT_WINDOW_CONSTRUCTION = Construction(
    name="Project External Window",
    layers=[
        SimpleGlazingMaterial(
            Name="DefaultGlazing",
            UFactor=2.7,
            Solar_Heat_Gain_Coefficient=0.763,
            Visible_Transmittance=0.8,
        )
    ],
)


def _default_construction_name(surface: IDFObject) -> str | None:
    """The placeholder construction geomeppy gave a building surface, by type."""
    surface_type = (surface.surface_type or "").lower()
    if surface_type == "wall":
        boundary = (surface.outside_boundary_condition or "").lower()
        return (
            "Project Wall"
            if boundary in ("outdoors", "ground")
            else "Project Partition"
        )
    return {
        "floor": "Project Floor",
        "roof": "Project Flat Roof",
        "ceiling": "Project Ceiling",
    }.get(surface_type)


def _set_default_constructions(doc: IDFDocument) -> None:
    """Create geomeppy's placeholder constructions and assign them by surface type.

    The constructions ("Project Wall", "Project Floor", ..., and "Project
    External Window" for the windows added later) use a single generic
    material, so the geometry simulates on its own until real constructions
    are assigned.
    """
    for name in _DEFAULT_OPAQUE_CONSTRUCTIONS:
        Construction(name=name, layers=[_DEFAULT_MATERIAL]).add(doc)
    _DEFAULT_WINDOW_CONSTRUCTION.add(doc)
    for surface in doc["BuildingSurface:Detailed"]:
        construction = _default_construction_name(surface)
        if construction is not None:
            surface.construction_name = construction


_CORE_PERIM_ZONE_NAMES = (
    "Perimeter_Zone_1",
    "Perimeter_Zone_2",
    "Perimeter_Zone_3",
    "Perimeter_Zone_4",
    "Core_Zone",
)


def _geomeppy_zone_name(
    storey: int, zone_index: int, zoning: ZoningType, basement: bool
) -> str:
    """Name a block zone the way geomeppy's `add_block` did.

    Args:
        storey: Storey index counted from 0 at the lowest storey (the basement, if any).
        zone_index: Index of the zone in its storey, in `create_block`'s order:
            the perimeter zones along the footprint edges starting from the
            south edge, then the core.
        zoning: The zoning type.
        basement: Whether the lowest storey is a basement.

    Returns:
        The zone name.
    """
    if zoning == "by_storey":
        # geomeppy numbered below-ground storeys from -1
        return f"Block shoebox Storey {storey - (1 if basement else 0)}"
    # with core/perim the basement was an ordinary storey moved down one storey
    return f"Block {_CORE_PERIM_ZONE_NAMES[zone_index]} Storey {storey}"


def _geomeppy_surface_name(zone_name: str, suffix: str, is_perimeter: bool) -> str:
    """Name a block surface the way geomeppy's `add_block` did, before matching.

    Args:
        zone_name: The (geomeppy) name of the surface's zone.
        suffix: The surface name `create_block` gave, without the zone name,
            e.g. "Wall 2", "Floor", "Ceiling" or "Roof".
        is_perimeter: Whether the zone is a core/perim perimeter zone; geomeppy
            numbered their walls from the inner corner, one ahead of idfkit.

    Returns:
        The surface name.
    """
    match = re.fullmatch(r"Wall (\d+)", suffix)
    if match is None:
        return f"{zone_name} {suffix} 0001"
    number = int(match.group(1))
    if is_perimeter:
        number = number % 4 + 1
    return f"{zone_name} Wall {number:04d}"


def _add_window(
    doc: IDFDocument,
    wall: IDFObject,
    wwr: float,
    construction: str = "Project External Window",
) -> IDFObject:
    """Add geomeppy's ribbon window to a wall.

    The window is the wall shrunk about its vertex average: by the
    window-to-wall ratio vertically and by 0.999 horizontally, which keeps it
    0.05% inside the wall edges.

    Args:
        doc: The IDF document.
        wall: The wall to add the window to.
        wwr: The window-to-wall ratio.
        construction: The window construction name.

    Returns:
        The window surface.
    """
    vertices = cast(Polygon3D, get_surface_coords(wall)).vertices
    average_x = sum([v.x for v in vertices]) / len(vertices)
    average_y = sum([v.y for v in vertices]) / len(vertices)
    average_z = sum([v.z for v in vertices]) / len(vertices)
    window_vertices = [
        (
            ((v.x - average_x) * 0.999) + average_x,
            ((v.y - average_y) * 0.999) + average_y,
            ((v.z - average_z) * wwr) + average_z,
        )
        for v in vertices
    ]
    fields = {
        "surface_type": "Window",
        "construction_name": construction,
        "building_surface_name": wall.name,
        "view_factor_to_ground": "Autocalculate",
        "number_of_vertices": len(window_vertices),
    } | {
        f"vertex_{i}_{axis}_coordinate": value
        for i, vertex in enumerate(window_vertices, 1)
        for axis, value in zip("xyz", vertex, strict=True)
    }
    return doc.add("FenestrationSurface:Detailed", f"{wall.name} window", fields)


def get_zone_floor_area(doc: IDFDocument, zone_name: str) -> float:
    """Get the floor area of a zone by iterating over building surfaces that are of type 'floor'.

    If more than one floor is found, for now we will return an error; it could be possible in an
    attic where the floor below has perim/core zoning...

    Args:
        doc (IDFDocument): The IDF document to get the floor area from.
        zone_name (str): The name of the zone to get the floor area from.

    Returns:
        area (float): The floor area of the zone [m2].
    """
    area = 0
    area_ct = 0
    for srf in doc["BuildingSurface:Detailed"]:
        # TODO: ensure that this still works for basements and attics.
        if srf.zone_name == zone_name and (srf.surface_type or "").lower() == "floor":
            srf_area = calculate_surface_area(srf)
            if srf_area == 0:
                raise ValueError(f"INVALID_FLOOR:{zone_name}:{srf.name}")
            area += srf_area
            area_ct += 1
    if area_ct not in [1, 5]:
        raise ValueError(f"TOO_MANY_FLOORS:{zone_name}:{area_ct}")
    if area == 0 or area_ct == 0:
        raise ValueError(f"NO_AREA:{zone_name}")

    return area


def get_zone_glazed_area(doc: IDFDocument, zone_name: str) -> float:
    """Calculate the total area of windows for a specific zone in the IDF document.

    Args:
        doc (IDFDocument): The IDF document.
        zone_name (str): The name of the zone to calculate the window area for.

    Returns:
        float: The total area of windows in the specified zone.
    """
    total_window_area = 0.0
    total_windows = 0

    for window in doc["FenestrationSurface:Detailed"]:
        parent_name = window.building_surface_name or ""
        parent_srf = doc["BuildingSurface:Detailed"].get(parent_name)
        if parent_srf is None:
            msg = f"BuildingSurface:Detailed:{parent_name} not found"
            raise ValueError(msg)
        if (parent_srf.zone_name or "").lower() == zone_name.lower() and (
            window.surface_type or ""
        ).lower() == "window":
            total_window_area += calculate_surface_area(window)
            total_windows += 1

    if total_windows not in [0, 1, 4]:
        msg = f"TOO_MANY_WINDOWS:{zone_name}:{total_windows}"
        raise ValueError(msg)

    return total_window_area
