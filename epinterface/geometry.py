"""Geometry utilities for the UBEM construction."""

import warnings
from collections.abc import Sequence
from typing import Literal, cast

import numpy as np
from archetypal.idfclass import IDF
from geomeppy.geom.vectors import Vector2D
from idfkit import IDFDocument, calculate_surface_area
from numpy.typing import ArrayLike
from pydantic import BaseModel, Field
from shapely import LineString, Polygon, from_wkt
from shapely.affinity import translate


def match_idf_to_building_and_neighbors(
    idf: IDF,
    building: Polygon | str,
    neighbor_polys: Sequence[Polygon | str | None],
    neighbor_floors: Sequence[float | int | None],
    neighbor_f2f_height: float,
    target_short_length: float,
    target_long_length: float,
    rotation_angle: float,
    allow_no_height: bool = False,
) -> IDF:
    """Match an IDF model to a building and neighbors by scaling and rotating the IDF model and adding shading blocks for neighbors.

    Args:
        idf (IDF): The IDF model to match.
        building (Polygon | str): The building to match.
        neighbor_polys (list[Polygon | str | None]): The neighbors to inject as shading.
        neighbor_floors (list[float | int | None]): The counts of the neighbors.
        neighbor_f2f_height (float | None): The height of the building to match
        target_short_length (float): The target short length of the building.
        target_long_length (float): The target long length of the building.
        rotation_angle (float): The rotation angle of the building (radians).
        allow_no_height (bool): Whether to allow no height for neighbors.

    Returns:
        idf (IDF): The matched IDF model.
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
    idf_lengths = {(e.p1 - e.p2).length for e in idf.bounding_box().edges}
    idf_x_coords = [e.p1.x for e in idf.bounding_box().edges]
    x_span = max(idf_x_coords) - min(idf_x_coords)
    idf_y_coords = [e.p1.y for e in idf.bounding_box().edges]
    y_span = max(idf_y_coords) - min(idf_y_coords)
    # TODO: better handling for boxes that aren't [(0,0),...]
    if x_span < y_span:
        raise NotImplementedError(
            "This function assumes that the long edge is the x-axis, which is not the case."
        )
    x_min = min(idf_x_coords)
    y_min = min(idf_y_coords)
    if abs(x_min) > 1e-3 or abs(y_min) > 1e-3:
        raise NotImplementedError(
            "This function assumes that the building has the lowerleft corner at the origin, which is not the case."
        )
    if len(idf_lengths) > 2:
        raise NotImplementedError(
            "The IDF model is not a rectangle, which is not yet supported."
        )

    long_length = max(idf_lengths)
    short_length = min(idf_lengths)

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
    idf.scale(target_long_length / long_length, anchor=Vector2D(0, 0), axes="x")
    idf.scale(target_short_length / short_length, anchor=Vector2D(0, 0), axes="y")
    idf.translate((
        -target_long_length / 2,
        -target_short_length / 2,
        0,
    ))  # This translation makes an assumption that the source building is at [(0,0),(0,w),...]
    idf.rotate(rotation_angle * 180 / np.pi)
    for i, (geom, height) in enumerate(translated_neighbors):
        if not height and not allow_no_height:
            height = 3.5 * 2
        if np.isnan(height):
            height = 3.5 * 2
        if height != 0:
            idf.add_shading_block(
                name=f"shading_{i}",
                coordinates=[Vector2D(*coord) for coord in geom.exterior.coords[:-1]],
                height=height,
            )
    return idf


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

    def add(self, idf: IDF) -> IDF:  # noqa: C901
        """Constructs a simple shoebox geometry in the IDF model.

        Takes advantage of the geomeppy methods to do so.

        Can create gables, basements, and various zoning strategies.

        Args:
            idf: The IDF model to add the geometry to.

        Returns:
            The IDF model with the added geometry.
        """
        lower_left_corner = (self.x, self.y)
        lower_right_corner = (self.x + self.w, self.y)
        upper_right_corner = (self.x + self.w, self.y + self.d)
        upper_left_corner = (self.x, self.y + self.d)
        bottom_plane = [
            lower_left_corner,
            lower_right_corner,
            upper_right_corner,
            upper_left_corner,
        ]
        idf.add_block(
            name="shoebox",
            coordinates=bottom_plane,
            height=self.zones_height
            + (self.h if self.basement and self.zoning == "core/perim" else 0),
            num_stories=self.num_stories + self.basement_storey_count,
            zoning=self.zoning,
            perim_depth=self.perim_depth,
            below_ground_stories=self.basement_storey_count,
            below_ground_storey_height=self.h,
        )
        if self.basement and self.zoning == "core/perim":
            idf.translate((0, 0, -self.h))

        if self.roof_height:
            # we need to convert the old roof surfaces to ceilings;
            # additionally, we will track them so that we can create the
            # corresponding floor surfaces for the attic in a manner
            # that avoids having to subdivide surfaces with intersect/match
            old_roof_srfs = []
            for srf in idf.idfobjects["BUILDINGSURFACE:DETAILED"]:
                if srf.Surface_Type.lower() == "roof":
                    srf.Surface_Type = "ceiling"
                    old_roof_srfs.append(srf)
            if len(old_roof_srfs) not in [1, 5]:
                msg = "Too many roof surfaces were found; expected 1 (by_storey) or 5 "
                f" (core/perim), but found {len(old_roof_srfs)}."
                raise ValueError(msg)

            # create the zone
            idf.newidfobject("ZONE", Name="Attic")

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

            if centerline_parallel_to == "d":
                # this gable goes from the left edge of the building to
                # the midpoint on the x-axis
                # it starts in the "upper left" corner in plan
                # and goes counter clockwise to the "lower left" corner
                # then to the roof centerline (and up in the z-axis)
                vert_0 = (self.x, self.y + self.d, self.zones_height)
                vert_1 = (self.x, self.y, self.zones_height)
                vert_2 = (roof_centerline, self.y, self.total_height_with_gabling)
                vert_3 = (
                    roof_centerline,
                    self.y + self.d,
                    self.total_height_with_gabling,
                )
            else:
                # this gable goes from the middle of the left edge at the top of the
                # gable and goes counter clockwise down to the lower left corner
                # then the lower right corner, and then back up.
                vert_0 = (self.x, roof_centerline, self.total_height_with_gabling)
                vert_1 = (self.x, self.y, self.zones_height)
                vert_2 = (self.x + self.w, self.y, self.zones_height)
                vert_3 = (
                    self.x + self.w,
                    roof_centerline,
                    self.total_height_with_gabling,
                )

            idf.newidfobject(
                "BUILDINGSURFACE:DETAILED",
                Name="Gable1",
                Surface_Type="Roof",
                Number_of_Vertices=4,
                View_Factor_to_Ground=0,
                Vertex_1_Xcoordinate=vert_0[0],
                Vertex_1_Ycoordinate=vert_0[1],
                Vertex_1_Zcoordinate=vert_0[2],
                Vertex_2_Xcoordinate=vert_1[0],
                Vertex_2_Ycoordinate=vert_1[1],
                Vertex_2_Zcoordinate=vert_1[2],
                Vertex_3_Xcoordinate=vert_2[0],
                Vertex_3_Ycoordinate=vert_2[1],
                Vertex_3_Zcoordinate=vert_2[2],
                Vertex_4_Xcoordinate=vert_3[0],
                Vertex_4_Ycoordinate=vert_3[1],
                Vertex_4_Zcoordinate=vert_3[2],
                Zone_Name="Attic",
            )

            if centerline_parallel_to == "d":
                vert_0 = (self.x + self.w, self.y, self.zones_height)
                vert_1 = (self.x + self.w, self.y + self.d, self.zones_height)
                vert_2 = (
                    roof_centerline,
                    self.y + self.d,
                    self.total_height_with_gabling,
                )
                vert_3 = (
                    roof_centerline,
                    self.y,
                    self.total_height_with_gabling,
                )
            else:
                vert_0 = (self.x, roof_centerline, self.total_height_with_gabling)
                vert_1 = (
                    self.x + self.w,
                    roof_centerline,
                    self.total_height_with_gabling,
                )
                vert_2 = (
                    self.x + self.w,
                    self.y + self.d,
                    self.zones_height,
                )
                vert_3 = (
                    self.x,
                    self.y + self.d,
                    self.zones_height,
                )

            idf.newidfobject(
                "BUILDINGSURFACE:DETAILED",
                Name="Gable2",
                Surface_Type="Roof",
                Number_of_Vertices=4,
                View_Factor_to_Ground=0,
                Vertex_1_Xcoordinate=vert_0[0],
                Vertex_1_Ycoordinate=vert_0[1],
                Vertex_1_Zcoordinate=vert_0[2],
                Vertex_2_Xcoordinate=vert_1[0],
                Vertex_2_Ycoordinate=vert_1[1],
                Vertex_2_Zcoordinate=vert_1[2],
                Vertex_3_Xcoordinate=vert_2[0],
                Vertex_3_Ycoordinate=vert_2[1],
                Vertex_3_Zcoordinate=vert_2[2],
                Vertex_4_Xcoordinate=vert_3[0],
                Vertex_4_Ycoordinate=vert_3[1],
                Vertex_4_Zcoordinate=vert_3[2],
                Zone_Name="Attic",
            )

            # make triangular endcaps
            if centerline_parallel_to == "d":
                vert_0 = (self.x, self.y, self.zones_height)
                vert_1 = (self.x + self.w, self.y, self.zones_height)
                vert_2 = (roof_centerline, self.y, self.total_height_with_gabling)
            else:
                vert_0 = (self.x, self.y, self.zones_height)
                vert_1 = (self.x, roof_centerline, self.total_height_with_gabling)
                vert_2 = (self.x, self.y + self.d, self.zones_height)

            idf.newidfobject(
                "BUILDINGSURFACE:DETAILED",
                Name="Endcap1",
                Surface_Type="Wall",
                Number_of_Vertices=3,
                Vertex_1_Xcoordinate=vert_0[0],
                Vertex_1_Ycoordinate=vert_0[1],
                Vertex_1_Zcoordinate=vert_0[2],
                Vertex_2_Xcoordinate=vert_1[0],
                Vertex_2_Ycoordinate=vert_1[1],
                Vertex_2_Zcoordinate=vert_1[2],
                Vertex_3_Xcoordinate=vert_2[0],
                Vertex_3_Ycoordinate=vert_2[1],
                Vertex_3_Zcoordinate=vert_2[2],
                Zone_Name="Attic",
            )

            if centerline_parallel_to == "d":
                vert_0 = (self.x + self.w, self.y + self.d, self.zones_height)
                vert_1 = (self.x, self.y + self.d, self.zones_height)
                vert_2 = (
                    roof_centerline,
                    self.y + self.d,
                    self.total_height_with_gabling,
                )
            else:
                vert_0 = (self.x + self.w, self.y, self.zones_height)
                vert_1 = (self.x + self.w, self.y + self.d, self.zones_height)
                vert_2 = (
                    self.x + self.w,
                    roof_centerline,
                    self.total_height_with_gabling,
                )

            idf.newidfobject(
                "BUILDINGSURFACE:DETAILED",
                Name="Endcap2",
                Surface_Type="Wall",
                Number_of_Vertices=3,
                Vertex_1_Xcoordinate=vert_0[0],
                Vertex_1_Ycoordinate=vert_0[1],
                Vertex_1_Zcoordinate=vert_0[2],
                Vertex_2_Xcoordinate=vert_1[0],
                Vertex_2_Ycoordinate=vert_1[1],
                Vertex_2_Zcoordinate=vert_1[2],
                Vertex_3_Xcoordinate=vert_2[0],
                Vertex_3_Ycoordinate=vert_2[1],
                Vertex_3_Zcoordinate=vert_2[2],
                Zone_Name="Attic",
            )

            # We will create identical floor surfaces for the attic to match
            # the zone below.  While we could just add a single plane and let
            # the `intersect_match` handle it, this is more robust; the geomeppy
            # method occasionally results in numerical floating point errors where
            # very small overhang area is created with an outside boundary
            # condition.
            # we use a vertex order of 1, 4, 3, 2 to match the orientation of the
            # roof surfaces below it, i.e. CCW vs CW.
            for i, srf in enumerate(old_roof_srfs):
                idf.newidfobject(
                    "BUILDINGSURFACE:DETAILED",
                    Name=f"attic_bottom_plane_{i}",
                    Surface_Type="Floor",
                    Number_of_Vertices=4,
                    Vertex_1_Xcoordinate=srf.Vertex_1_Xcoordinate,
                    Vertex_1_Ycoordinate=srf.Vertex_1_Ycoordinate,
                    Vertex_1_Zcoordinate=srf.Vertex_1_Zcoordinate,
                    Vertex_2_Xcoordinate=srf.Vertex_4_Xcoordinate,
                    Vertex_2_Ycoordinate=srf.Vertex_4_Ycoordinate,
                    Vertex_2_Zcoordinate=srf.Vertex_4_Zcoordinate,
                    Vertex_3_Xcoordinate=srf.Vertex_3_Xcoordinate,
                    Vertex_3_Ycoordinate=srf.Vertex_3_Ycoordinate,
                    Vertex_3_Zcoordinate=srf.Vertex_3_Zcoordinate,
                    Vertex_4_Xcoordinate=srf.Vertex_2_Xcoordinate,
                    Vertex_4_Ycoordinate=srf.Vertex_2_Ycoordinate,
                    Vertex_4_Zcoordinate=srf.Vertex_2_Zcoordinate,
                    Zone_Name="Attic",
                )

        idf.intersect_match()

        idf.set_default_constructions()

        # Handle Windows
        window_walls = [
            w
            for w in idf.idfobjects["BUILDINGSURFACE:DETAILED"]
            if w.Outside_Boundary_Condition.lower() == "outdoors"
            and "attic" not in w.Zone_Name.lower()
            and (
                not w.Zone_Name.lower().endswith(self.basement_suffix.lower())
                if self.basement
                else True
            )
            and w.Surface_Type.lower() == "wall"
        ]
        idf.set_wwr(
            wwr=self.wwr,
            construction="Project External Window",
            force=True,
            surfaces=window_walls,
        )

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
            original_building_area = idf.total_building_area
            idf = match_idf_to_building_and_neighbors(
                idf,
                building=self.scene_context.building,
                neighbor_polys=mask_polys,
                neighbor_floors=neighbor_floors,
                neighbor_f2f_height=self.h,
                target_short_length=self.d,
                target_long_length=self.w,
                rotation_angle=self.scene_context.orientation,
                allow_no_height=True,
            )
            new_building_area = idf.total_building_area
            if not np.isclose(original_building_area, new_building_area):
                msg = f"Total building area mismatch after matching to building and neighbors: {original_building_area} != {new_building_area}"
                raise ValueError(msg)

        return idf


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


def get_zone_glazed_area_alt(idf: IDF, zone_name: str) -> float:
    """Calculate the total area of windows for a specific zone in the IDF model.

    Args:
        idf (IDF): The IDF model.
        zone_name (str): The name of the zone to calculate the window area for.

    Returns:
        float: The total area of windows in the specified zone.
    """
    total_window_area = 0.0
    total_windows = 0

    for window in idf.idfobjects["FENESTRATIONSURFACE:DETAILED"]:
        parent_srf = idf.getobject(
            "BUILDINGSURFACE:DETAILED", window.Building_Surface_Name
        )
        if parent_srf is None:
            msg = f"BUILDINGSURFACE:DETAILED:{window.Building_Surface_Name} not found"
            raise ValueError(msg)
        if (
            parent_srf.Zone_Name.lower() == zone_name.lower()
            and window.Surface_Type.lower() == "window"
        ):
            vertices = [
                (
                    window.Vertex_1_Xcoordinate,
                    window.Vertex_1_Ycoordinate,
                    window.Vertex_1_Zcoordinate,
                ),
                (
                    window.Vertex_2_Xcoordinate,
                    window.Vertex_2_Ycoordinate,
                    window.Vertex_2_Zcoordinate,
                ),
                (
                    window.Vertex_3_Xcoordinate,
                    window.Vertex_3_Ycoordinate,
                    window.Vertex_3_Zcoordinate,
                ),
                (
                    window.Vertex_4_Xcoordinate,
                    window.Vertex_4_Ycoordinate,
                    window.Vertex_4_Zcoordinate,
                ),
            ]
            # Assuming the window is a quadrilateral, calculate its area
            # This is a simplified calculation assuming the window is a rectangle
            width = (
                (vertices[1][0] - vertices[0][0]) ** 2
                + (vertices[1][1] - vertices[0][1]) ** 2
                + (vertices[1][2] - vertices[0][2]) ** 2
            ) ** 0.5
            height = (
                (vertices[2][0] - vertices[1][0]) ** 2
                + (vertices[2][1] - vertices[1][1]) ** 2
                + (vertices[2][2] - vertices[1][2]) ** 2
            ) ** 0.5
            area = width * height
            total_window_area += area
            total_windows += 1

    if total_windows not in [0, 1, 4]:
        msg = f"TOO_MANY_WINDOWS:{zone_name}:{total_windows}"
        raise ValueError(msg)

    alt_window_area = get_zone_glazed_area_alt(idf, zone_name)
    if not np.allclose(total_window_area, alt_window_area):
        msg = f"GLAZED_AREA_MISMATCH:{zone_name}:{total_window_area}:{alt_window_area}"
        raise ValueError(msg)
    return total_window_area


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
