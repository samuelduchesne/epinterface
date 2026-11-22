"""Geometry utilities for the UBEM construction."""

import itertools
import re
import warnings
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np
from idfkit import (
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
from idfkit.zoning import ZoneFootprint, ZoningScheme, create_block
from numpy.typing import ArrayLike
from pydantic import BaseModel, Field, field_validator
from shapely import LineString, Polygon, from_wkt
from shapely.affinity import translate

from epinterface.document import EPDocument, add_construction, add_or_replace

if TYPE_CHECKING:
    # The object classes exist only in idfkit's stubs.
    from idfkit.document import (
        AnyBuildingSurfaceDetailed,
        AnyFenestrationSurfaceDetailed,
        AnyZone,
    )


def _total_floor_area(doc: EPDocument) -> float:
    """Sum the areas of all floor surfaces in the document [m2]."""
    return sum(
        calculate_surface_area(srf)
        for srf in doc["BuildingSurface:Detailed"]
        if (srf.surface_type or "").lower() == "floor"
    )


def match_idf_to_building_and_neighbors(
    doc: EPDocument,
    building: Polygon | str,
    neighbor_polys: Sequence[Polygon | str | None],
    neighbor_floors: Sequence[float | int | None],
    neighbor_f2f_height: float,
    target_short_length: float,
    target_long_length: float,
    rotation_angle: float,
    allow_no_height: bool = False,
) -> EPDocument:
    """Match an IDF model to a building and neighbors by scaling and rotating the IDF model and adding shading blocks for neighbors.

    Args:
        doc (EPDocument): The IDF document to match.
        building (Polygon | str): The building to match.
        neighbor_polys (list[Polygon | str | None]): The neighbors to inject as shading.
        neighbor_floors (list[float | int | None]): The counts of the neighbors.
        neighbor_f2f_height (float | None): The height of the building to match
        target_short_length (float): The target short length of the building.
        target_long_length (float): The target long length of the building.
        rotation_angle (float): The rotation angle of the building (radians).
        allow_no_height (bool): Whether to allow no height for neighbors.

    Returns:
        doc (EPDocument): The matched IDF document.
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
    doc: EPDocument, name: str, footprint: list[tuple[float, float]], height: float
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

GroupExposure = Literal["core", "perimeter"]

GROUP_SHARE_TOLERANCE = 1e-6
"""Tolerance on the sum of the floor-area shares of a shoebox's zone groups."""

_MIN_PIECE_LENGTH = 2e-3
"""Pieces of a group footprint shorter than this [m] are absorbed by their neighbour."""


def perimeter_depth_for_share(w: float, d: float, share: float) -> float:
    """The perimeter depth that gives a perimeter floor-area share on a footprint.

    A `w` by `d` footprint with perimeter depth `p` has a perimeter area of
    `w*d - (w - 2p)(d - 2p)`. This solves that area equal to `share * w * d` for
    the root with `0 < p < min(w, d) / 2`.

    Args:
        w: Footprint width [m].
        d: Footprint depth [m].
        share: Perimeter share of the floor area, in (0, 1).

    Returns:
        perim_depth: The perimeter depth [m].

    Raises:
        ValueError: If the share is not strictly between 0 and 1.
    """
    if not 0 < share < 1:
        msg = f"A perimeter share must be strictly between 0 and 1 to leave a core; got {share!r}."
        raise ValueError(msg)
    s = w + d
    return (s - float(np.sqrt(s * s - 4 * share * w * d))) / 4


class ZoneGroupLayout(BaseModel, frozen=True):
    """One zone group of a shoebox: its share of each storey's floor area and its exposure.

    A shoebox with zone groups has one zone per group on each storey. See
    `ShoeboxGeometry.group_footprints` for how the zones are laid out.
    """

    share: float = Field(
        ..., gt=0, le=1, description="Share of each storey's floor area, in (0, 1]."
    )
    exposure: GroupExposure | None = Field(
        default=None,
        description=(
            "`perimeter`: the group shares the perimeter ring; `core`: the core. "
            "None: the group is not tied to an exposure."
        ),
    )


Rectangle = tuple[float, float, float, float]
"""An axis-aligned rectangle `(x0, y0, x1, y1)`."""


def _split_lengths(total: float, shares: Sequence[float]) -> list[float]:
    """Cut points along a length, at the cumulative shares, snapped to its ends."""
    cuts = [0.0]
    acc = 0.0
    weight = sum(shares)
    for share in shares[:-1]:
        acc += share
        cuts.append(total * acc / weight)
    cuts.append(total)
    return cuts


def _strips(rect: Rectangle, shares: Sequence[float]) -> list[list[Rectangle]]:
    """Cut a rectangle across its long axis into strips with areas proportional to shares."""
    x0, y0, x1, y1 = rect
    along_x = (x1 - x0) >= (y1 - y0)
    length = (x1 - x0) if along_x else (y1 - y0)
    cuts = _split_lengths(length, shares)
    strips: list[list[Rectangle]] = []
    for a, b in itertools.pairwise(cuts):
        if along_x:
            strips.append([(x0 + a, y0, x0 + b, y1)])
        else:
            strips.append([(x0, y0 + a, x1, y0 + b)])
    return strips


def _ring_pieces(
    x0: float, y0: float, w: float, d: float, p: float, shares: Sequence[float]
) -> list[list[Rectangle]]:
    """Cut a perimeter ring of depth `p` into chains of rectangles proportional to shares.

    The ring is four rectangles of depth `p` in a pinwheel, walked counter-clockwise
    from the south-west corner: south, east, north and west. Each has an area of
    `p` times its length, so cutting the walk at the cumulative shares of its total
    length gives pieces of the right area. Every piece touches the facade.
    """
    x1, y1 = x0 + w, y0 + d

    def south(a: float, b: float) -> Rectangle:
        return (x0 + a, y0, x0 + b, y0 + p)

    def east(a: float, b: float) -> Rectangle:
        return (x1 - p, y0 + a, x1, y0 + b)

    def north(a: float, b: float) -> Rectangle:
        return (x1 - b, y1 - p, x1 - a, y1)

    def west(a: float, b: float) -> Rectangle:
        return (x0, y1 - b, x0 + p, y1 - a)

    sides = [(south, w - p), (east, d - p), (north, w - p), (west, d - p)]
    starts = list(itertools.accumulate([0.0] + [length for _, length in sides]))
    total = starts[-1]
    cuts = _split_lengths(total, shares)
    # snap cuts near a side's end onto it, so no piece is a sliver
    for i, cut in enumerate(cuts):
        nearest = min(starts, key=lambda s: abs(s - cut))
        if abs(nearest - cut) < _MIN_PIECE_LENGTH:
            cuts[i] = nearest
    pieces: list[list[Rectangle]] = []
    for a, b in itertools.pairwise(cuts):
        rects: list[Rectangle] = []
        for (make, _length), start, end in zip(
            sides, starts[:-1], starts[1:], strict=True
        ):
            lo, hi = max(a, start), min(b, end)
            if hi - lo > 0:
                rects.append(make(lo - start, hi - start))
        pieces.append(rects)
    return pieces


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
    zone_groups: list[ZoneGroupLayout] | None = Field(
        default=None,
        description=(
            "Zone groups: one zone per group on each storey, with floor areas "
            "proportional to the shares. None: the zones follow `zoning`. With "
            "groups, `zoning` and `perim_depth` are ignored."
        ),
    )

    @field_validator("zone_groups", mode="after")
    @classmethod
    def check_zone_groups(
        cls, v: list[ZoneGroupLayout] | None
    ) -> list[ZoneGroupLayout] | None:
        """Shares sum to 1, and exposures are all set or all unset.

        Raises:
            ValueError
        """
        if v is None:
            return v
        if not v:
            msg = "zone_groups needs at least one group; use None for no groups."
            raise ValueError(msg)
        total = sum(g.share for g in v)
        if abs(total - 1) > GROUP_SHARE_TOLERANCE:
            msg = f"The zone group shares must sum to 1; they sum to {total!r}."
            raise ValueError(msg)
        exposures = {g.exposure for g in v}
        if None in exposures and len(exposures) > 1:
            msg = (
                "Either every zone group has an exposure or none has; got "
                f"{[g.exposure for g in v]}."
            )
            raise ValueError(msg)
        return v

    def group_footprints(self) -> list[list[Rectangle]]:
        """The footprint of each zone group's zone on a storey, as rectangles.

        - With both `perimeter` and `core` groups, the perimeter depth is the one
          that gives the perimeter groups' total share
          (`perimeter_depth_for_share`). The perimeter ring is cut, walking
          counter-clockwise from the south-west corner, into one piece per
          perimeter group, in order. Each piece touches the facade. The core is
          cut across its long axis into one strip per core group.
        - Otherwise (no exposures, or a single kind), the footprint is cut across
          its long axis into one strip per group, each spanning the full depth.

        Every piece's area is the group's share of the footprint area.

        Returns:
            footprints: For each group, in order, the rectangles `(x0, y0, x1, y1)`
                that make up its zone.

        Raises:
            ValueError: If the geometry has no zone groups.
        """
        groups = self.zone_groups
        if groups is None:
            msg = "The geometry has no zone groups."
            raise ValueError(msg)
        exposures = {g.exposure for g in groups}
        rect = (self.x, self.y, self.x + self.w, self.y + self.d)
        if exposures != {"core", "perimeter"}:
            return _strips(rect, [g.share for g in groups])
        perimeter = [i for i, g in enumerate(groups) if g.exposure == "perimeter"]
        core = [i for i, g in enumerate(groups) if g.exposure == "core"]
        p = perimeter_depth_for_share(
            self.w, self.d, sum(groups[i].share for i in perimeter)
        )
        footprints: list[list[Rectangle]] = [[] for _ in groups]
        ring = _ring_pieces(
            self.x, self.y, self.w, self.d, p, [groups[i].share for i in perimeter]
        )
        for i, piece in zip(perimeter, ring, strict=True):
            footprints[i] = piece
        x0, y0, x1, y1 = rect
        strips = _strips(
            (x0 + p, y0 + p, x1 - p, y1 - p), [groups[i].share for i in core]
        )
        for i, piece in zip(core, strips, strict=True):
            footprints[i] = piece
        footprints = [
            [
                (round(a, 9), round(b, 9), round(c, 9), round(e, 9))
                for a, b, c, e in piece
            ]
            for piece in footprints
        ]
        for i, piece in enumerate(footprints):
            if not piece:
                msg = f"Zone group {i} is too small to place on the shoebox."
                raise ValueError(msg)
        return footprints

    @staticmethod
    def group_zone_name(group_index: int, storey: int) -> str:
        """The name of a zone group's zone on a storey.

        Args:
            group_index: Index of the group in `zone_groups`, from 0.
            storey: Storey index from 0 at the lowest storey (the basement, if any).

        Returns:
            name: `"Block Group{group_index + 1} Storey {storey}"`.
        """
        return f"Block Group{group_index + 1} Storey {storey}"

    @staticmethod
    def zone_group_index(zone_name: str) -> int | None:
        """The index of the zone group a zone belongs to, from its name.

        Args:
            zone_name: The zone name.

        Returns:
            group_index: The index in `zone_groups`, or None if the zone is not a
                group zone (for example the attic).
        """
        match = re.fullmatch(r"Block Group(\d+) Storey \d+", zone_name)
        return int(match.group(1)) - 1 if match else None

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
        if self.zone_groups is not None:
            return "Storey 0"
        return "Storey 0" if self.zoning == "core/perim" else "Storey -1"

    @property
    def zones_per_storey(self) -> int:
        """Return the number of zones per storey."""
        if self.zone_groups is not None:
            return len(self.zone_groups)
        if self.zoning == "core/perim":
            return 5
        else:
            return 1

    def add(self, doc: EPDocument) -> EPDocument:  # noqa: C901
        """Constructs a simple shoebox geometry in the IDF document.

        Zones are built with idfkit's `create_block`; the result reproduces the
        geometry, zone names and zone order of the geomeppy implementation it
        replaces. With `zone_groups`, each storey instead has one zone per group,
        named with `group_zone_name`, laid out as `group_footprints` describes.

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
        if self.zone_groups is not None:
            zones, surfaces, pieces = self._create_group_block(
                doc, footprint, storey_count
            )
        else:
            zones, surfaces = self._create_zoned_block(doc, footprint, storey_count)
            pieces = None

        if self.basement:
            # idfkit builds no below-ground storeys: the lowest storey becomes the
            # basement by moving the block down one storey and burying its walls.
            lowest = (
                [z for z in zones if pieces[z.name][1] == 0]
                if pieces is not None
                else zones[: self.zones_per_storey]
            )
            self._bury_lowest_storey(lowest, surfaces)

        attic_floors = self._add_attic(doc, surfaces) if self.roof_height else []

        # create_block's surfaces already share exact vertices; a fine snapping
        # grid keeps them exact (the default 0.1 mm grid shifts diagonal walls).
        report = intersect_and_match(doc, MatchOptions(snap_tol=1e-9))
        if pieces is None and (report.surfaces_split or report.fragments_created):
            msg = (
                "Surface matching unexpectedly split the shoebox surfaces "
                f"({report.surfaces_split} split, {report.fragments_created} created)."
            )
            raise ValueError(msg)
        for floor in attic_floors:
            if floor.outside_boundary_condition.lower() != "surface":
                msg = f"Attic floor {floor.name} was not matched to a ceiling below."
                raise ValueError(msg)

        if pieces is not None:
            self._merge_group_pieces(doc, zones, pieces, attic_floors)
        else:
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

    def _create_zoned_block(
        self, doc: EPDocument, footprint: list[tuple[float, float]], storey_count: int
    ) -> tuple[Sequence["AnyZone"], Sequence["AnyBuildingSurfaceDetailed"]]:
        """Create the block zoned by storey or core/perimeter, with `create_block`."""
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
        # The created objects, typed and in creation order, from their collections.
        created_ids = {id(obj) for obj in created}
        zones = [zone for zone in doc["Zone"] if id(zone) in created_ids]
        surfaces = [
            srf for srf in doc["BuildingSurface:Detailed"] if id(srf) in created_ids
        ]
        if len(zones) != storey_count * self.zones_per_storey:
            msg = (
                f"Expected {storey_count * self.zones_per_storey} zones but found "
                f"{len(zones)}; the perimeter depth may be too large for the footprint."
            )
            raise ValueError(msg)
        return zones, surfaces

    def _create_group_block(
        self, doc: EPDocument, footprint: list[tuple[float, float]], storey_count: int
    ) -> tuple[
        Sequence["AnyZone"],
        Sequence["AnyBuildingSurfaceDetailed"],
        dict[str, tuple[int, int]],
    ]:
        """Create one zone per rectangle of every group's footprint, on every storey.

        Returns:
            zones: The created zones.
            surfaces: The created surfaces.
            pieces: For each created zone name, its group index and storey index.
        """
        custom_zones = [
            ZoneFootprint(
                name_suffix=f"G{gi}_{pi}",
                polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            )
            for gi, rects in enumerate(self.group_footprints())
            for pi, (x0, y0, x1, y1) in enumerate(rects)
        ]
        created = create_block(
            doc,
            name="shoebox",
            footprint=footprint,
            floor_to_floor=self.h,
            num_stories=storey_count,
            zoning=ZoningScheme.CUSTOM,
            custom_zones=custom_zones,
        )
        created_ids = {id(obj) for obj in created}
        zones = [zone for zone in doc["Zone"] if id(zone) in created_ids]
        surfaces = [
            srf for srf in doc["BuildingSurface:Detailed"] if id(srf) in created_ids
        ]
        pieces: dict[str, tuple[int, int]] = {}
        for zone in zones:
            match = re.fullmatch(r"shoebox (?:Story (\d+) )?G(\d+)_\d+", zone.name)
            if match is None:
                msg = f"Unexpected zone name {zone.name!r} from create_block."
                raise ValueError(msg)
            storey = int(match.group(1) or 1) - 1
            pieces[zone.name] = (int(match.group(2)), storey)
        if len(zones) != storey_count * len(custom_zones):
            msg = (
                f"Expected {storey_count * len(custom_zones)} zones but found "
                f"{len(zones)}."
            )
            raise ValueError(msg)
        return zones, surfaces, pieces

    def _merge_group_pieces(  # noqa: C901
        self,
        doc: EPDocument,
        zones: Sequence["AnyZone"],
        pieces: dict[str, tuple[int, int]],
        attic_floors: Sequence["AnyBuildingSurfaceDetailed"],
    ) -> None:
        """Merge each group's pieces on a storey into one zone, and name it.

        The surfaces of a group's pieces move to one zone, and the matched walls
        between two pieces of the same zone are removed, so the zone is enclosed by
        its outer surfaces only. Zones are named with `group_zone_name`, surfaces
        `"<zone name> <type> <n>"`, so they keep the zone name in them as the
        construction handlers expect.
        """
        keeper: dict[tuple[int, int], str] = {}
        target_of: dict[str, str] = {}
        for zone in zones:
            key = pieces[zone.name]
            keeper.setdefault(key, zone.name)
            target_of[zone.name] = keeper[key]
        surfaces = doc["BuildingSurface:Detailed"]
        for srf in surfaces:
            if srf.zone_name in target_of:
                srf.zone_name = target_of[srf.zone_name]
        for zone in list(zones):
            if target_of[zone.name] != zone.name:
                doc.removeidfobject(zone)
        zone_of = {srf.name: srf.zone_name for srf in surfaces}
        internal = [
            srf
            for srf in surfaces
            if (srf.outside_boundary_condition or "").lower() == "surface"
            and zone_of.get(srf.outside_boundary_condition_object or "")
            == srf.zone_name
        ]
        for srf in internal:
            doc.removeidfobject(srf)
        for key, name in sorted(keeper.items()):
            doc.rename("Zone", name, self.group_zone_name(*key))
        counts: dict[tuple[str, str], int] = {}
        for srf in list(surfaces):
            if "attic" in (srf.zone_name or "").lower():
                continue
            kind = (srf.surface_type or "").title()
            n = counts[srf.zone_name, kind] = counts.get((srf.zone_name, kind), 0) + 1
            new_name = f"{srf.zone_name} {kind} {n:04d}"
            if new_name != srf.name:
                doc.rename("BuildingSurface:Detailed", srf.name, new_name)
        for floor in attic_floors:
            doc.rename("BuildingSurface:Detailed", floor.name, f"{floor.name}_1")

    def _bury_lowest_storey(
        self,
        basement_zones: Sequence["AnyZone"],
        surfaces: Sequence["AnyBuildingSurfaceDetailed"],
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
        self, doc: EPDocument, surfaces: Sequence["AnyBuildingSurfaceDetailed"]
    ) -> list["AnyBuildingSurfaceDetailed"]:
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
        if self.zone_groups is None and len(old_roof_srfs) not in [1, 5]:
            msg = (
                "Too many roof surfaces were found; expected 1 (by_storey) or 5 "
                f" (core/perim), but found {len(old_roof_srfs)}."
            )
            raise ValueError(msg)
        for srf in old_roof_srfs:
            srf.surface_type = "Ceiling"

        # create the zone
        doc["Zone"].add("Attic")

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

        attic_surfaces: list[tuple[str, Literal["Roof", "Wall"], list]] = [
            ("Gable1", "Roof", gable1),
            ("Gable2", "Roof", gable2),
            ("Endcap1", "Wall", endcap1),
            ("Endcap2", "Wall", endcap2),
        ]
        for name, surface_type, vertices in attic_surfaces:
            srf = doc["BuildingSurface:Detailed"].add(
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
            floor = doc["BuildingSurface:Detailed"].add(
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
        doc: EPDocument,
        zones: Sequence["AnyZone"],
        surfaces: Sequence["AnyBuildingSurfaceDetailed"],
        attic_floors: Sequence["AnyBuildingSurfaceDetailed"],
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


_DEFAULT_MATERIAL_NAME = "DefaultMaterial"
_DEFAULT_MATERIAL: dict[str, Any] = {
    "roughness": "Rough",
    "thickness": 0.1,
    "conductivity": 0.1,
    "density": 1000.0,
    "specific_heat": 1000.0,
}
_DEFAULT_OPAQUE_CONSTRUCTIONS = (
    "Project Wall",
    "Project Partition",
    "Project Floor",
    "Project Flat Roof",
    "Project Ceiling",
    "Project Door",
)
_DEFAULT_WINDOW_CONSTRUCTION = "Project External Window"
_DEFAULT_GLAZING_NAME = "DefaultGlazing"
_DEFAULT_GLAZING: dict[str, Any] = {
    "u_factor": 2.7,
    "solar_heat_gain_coefficient": 0.763,
    "visible_transmittance": 0.8,
}


def _default_construction_name(surface: "AnyBuildingSurfaceDetailed") -> str | None:
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


def _set_default_constructions(doc: EPDocument) -> None:
    """Create geomeppy's placeholder constructions and assign them by surface type.

    The constructions ("Project Wall", "Project Floor", ..., and "Project
    External Window" for the windows added later) use a single generic
    material, so the geometry simulates on its own until real constructions
    are assigned.
    """
    for name in _DEFAULT_OPAQUE_CONSTRUCTIONS:
        add_or_replace(doc["Material"].add, _DEFAULT_MATERIAL_NAME, **_DEFAULT_MATERIAL)
        add_construction(doc, name, [_DEFAULT_MATERIAL_NAME])
    add_or_replace(
        doc["WindowMaterial:SimpleGlazingSystem"].add,
        _DEFAULT_GLAZING_NAME,
        **_DEFAULT_GLAZING,
    )
    add_construction(doc, _DEFAULT_WINDOW_CONSTRUCTION, [_DEFAULT_GLAZING_NAME])
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
    doc: EPDocument,
    wall: "AnyBuildingSurfaceDetailed",
    wwr: float,
    construction: str = "Project External Window",
) -> "AnyFenestrationSurfaceDetailed":
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
    fields: dict[str, Any] = {
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
    return doc["FenestrationSurface:Detailed"].add(f"{wall.name} window", **fields)


def get_zone_floor_area(doc: EPDocument, zone_name: str) -> float:
    """Get the floor area of a zone by iterating over building surfaces that are of type 'floor'.

    The zone may have several floor surfaces, as the attic above core/perimeter
    zones or the zone of a zone group (see `ShoeboxGeometry.zone_groups`) do.

    Args:
        doc (EPDocument): The IDF document to get the floor area from.
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
    if area_ct == 0:
        raise ValueError(f"TOO_MANY_FLOORS:{zone_name}:{area_ct}")
    if area == 0 or area_ct == 0:
        raise ValueError(f"NO_AREA:{zone_name}")

    return area


def get_zone_glazed_area(doc: EPDocument, zone_name: str) -> float:
    """Calculate the total area of windows for a specific zone in the IDF document.

    Args:
        doc (EPDocument): The IDF document.
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

    return total_window_area
