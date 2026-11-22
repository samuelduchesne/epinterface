"""Tests for the multi-group SBEM archetype and its shoebox placement.

None of these tests needs a Prisma database; the zone definition is read from a
committed JSON file. Only the build test needs an EnergyPlus version setting.
"""

import math
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from epinterface.data import DefaultEPWZipPath
from epinterface.geometry import (
    ShoeboxGeometry,
    ZoneGroupLayout,
    get_zone_floor_area,
)
from epinterface.sbem.archetype import (
    ARCHETYPE_SCHEMA_VERSION,
    ORIENTATIONS,
    Archetype,
    AtticAssumptions,
    BasementAssumptions,
    BuildingGeometry,
    ZoneGroup,
    orientation_of,
)
from epinterface.sbem.builder import (
    Model,
    SimulationPathConfig,
    perimeter_depth_for_share,
)
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings

ZONE_PATH = Path(__file__).parent / "data" / "sbem_zone.json"


@pytest.fixture(scope="module")
def zone() -> ZoneComponent:
    """The seed's default zone definition."""
    return ZoneComponent.model_validate_json(ZONE_PATH.read_text())


@pytest.fixture
def core_zone(zone: ZoneComponent) -> ZoneComponent:
    """A zone definition that differs from `zone` by its lighting density."""
    core = zone.model_copy(deep=True)
    core.Name = "core_zone"
    core.Operations.SpaceUse.Lighting.PowerDensity = 2.5
    return core


def _geometry(**kwargs) -> ShoeboxGeometry:
    return ShoeboxGeometry(**{
        "x": 0,
        "y": 0,
        "w": 20,
        "d": 12,
        "h": 3,
        "wwr": 0.3,
        "num_stories": 2,
        "basement": False,
        "zoning": "core/perim",
        "roof_height": None,
        **kwargs,
    })


def _archetype(zone: ZoneComponent, core_zone: ZoneComponent, **kwargs) -> Archetype:
    return Archetype(**{
        "Name": "office",
        "Groups": [
            ZoneGroup(
                Name="perimeter", Zone=zone, FloorAreaShare=0.6, Exposure="perimeter"
            ),
            ZoneGroup(Name="core", Zone=core_zone, FloorAreaShare=0.4, Exposure="core"),
        ],
        "Geometry": BuildingGeometry(
            Storeys=2,
            ConditionedFloorArea=480.0,
            WindowToWallRatio=BuildingGeometry.uniform(0.3),
            FacadeAreaPerFloorArea=dict.fromkeys(ORIENTATIONS, 0.05),
        ),
        **kwargs,
    })


# --- the model ---------------------------------------------------------------


def test_defaults(zone: ZoneComponent):
    """One group, no attic or basement use, unknown geometry, current schema."""
    a = Archetype(
        Name="a", Groups=[ZoneGroup(Name="all", Zone=zone, FloorAreaShare=1.0)]
    )
    assert a.SchemaVersion == ARCHETYPE_SCHEMA_VERSION
    assert a.Attic == AtticAssumptions(UseFraction=None, Conditioned=False)
    assert a.Basement == BasementAssumptions(UseFraction=None, Conditioned=False)
    assert a.Geometry == BuildingGeometry()
    assert a.group("all").Zone == zone
    with pytest.raises(KeyError):
        a.group("missing")


def test_shares_must_sum_to_one(zone: ZoneComponent):
    """Shares summing to anything but 1 are refused, within a small tolerance."""
    groups = [
        ZoneGroup(Name="a", Zone=zone, FloorAreaShare=0.5),
        ZoneGroup(Name="b", Zone=zone, FloorAreaShare=0.4),
    ]
    with pytest.raises(ValidationError, match="sum to 1"):
        Archetype(Name="x", Groups=groups)
    groups[1] = ZoneGroup(Name="b", Zone=zone, FloorAreaShare=0.5 + 1e-9)
    Archetype(Name="x", Groups=groups)


@pytest.mark.parametrize("share", [0.0, -0.1, 1.1])
def test_share_range(zone: ZoneComponent, share: float):
    """A share is in (0, 1]."""
    with pytest.raises(ValidationError):
        ZoneGroup(Name="a", Zone=zone, FloorAreaShare=share)


def test_group_names_unique(zone: ZoneComponent):
    """Two groups cannot share a name."""
    groups = [
        ZoneGroup(Name="a", Zone=zone, FloorAreaShare=0.5),
        ZoneGroup(Name="a", Zone=zone, FloorAreaShare=0.5),
    ]
    with pytest.raises(ValidationError, match="unique"):
        Archetype(Name="x", Groups=groups)


def test_needs_a_group():
    """An archetype has at least one group."""
    with pytest.raises(ValidationError):
        Archetype(Name="x", Groups=[])


def test_extra_fields_forbidden(zone: ZoneComponent, core_zone: ZoneComponent):
    """Unknown fields are refused, so a misspelt field is not silently dropped."""
    data = _archetype(zone, core_zone).model_dump()
    data["Unknown"] = 1
    with pytest.raises(ValidationError):
        Archetype.model_validate(data)


def test_unsupported_schema_version(zone: ZoneComponent, core_zone: ZoneComponent):
    """A file from another schema version is refused with both versions named."""
    data = _archetype(zone, core_zone).model_dump()
    data["SchemaVersion"] = "9.0"
    with pytest.raises(ValidationError, match="'9.0' is not supported"):
        Archetype.model_validate(data)


# --- geometry characteristics -------------------------------------------------


def test_orientation_dicts_need_every_orientation():
    """Partial orientation maps are refused."""
    with pytest.raises(ValidationError, match="missing"):
        BuildingGeometry(WindowToWallRatio={"N": 0.2})


def test_orientation_dicts_are_reordered():
    """Orientation maps are stored in canonical order, for byte-identical files."""
    g = BuildingGeometry(
        WindowToWallRatio={o: 0.1 for o in reversed(ORIENTATIONS)}  # noqa: C420
    )
    assert g.WindowToWallRatio is not None
    assert tuple(g.WindowToWallRatio) == ORIENTATIONS


def test_wwr_range():
    """A window-to-wall ratio is within [0, 1]."""
    with pytest.raises(ValidationError):
        BuildingGeometry(WindowToWallRatio=BuildingGeometry.uniform(1.2))


def test_window_area_and_overall_ratio():
    """Window area is facade area times ratio; the overall ratio is area-weighted."""
    facade = dict.fromkeys(ORIENTATIONS, 0.0)
    facade.update(N=0.1, S=0.3)
    wwr = BuildingGeometry.uniform(0.0)
    wwr.update(N=0.2, S=0.4)
    g = BuildingGeometry(WindowToWallRatio=wwr, FacadeAreaPerFloorArea=facade)
    assert g.WindowAreaPerFloorArea is not None
    assert g.WindowAreaPerFloorArea["S"] == pytest.approx(0.12)
    assert g.OverallWindowToWallRatio == pytest.approx((0.02 + 0.12) / 0.4)
    assert BuildingGeometry().WindowAreaPerFloorArea is None
    assert BuildingGeometry(
        WindowToWallRatio=BuildingGeometry.uniform(0.25)
    ).OverallWindowToWallRatio == pytest.approx(0.25)


@pytest.mark.parametrize(
    ("azimuth", "expected"),
    [
        (0, "N"),
        (22.4, "N"),
        (22.5, "NE"),
        (90, "E"),
        (180, "S"),
        (337.5, "N"),
        (-90, "W"),
    ],
)
def test_orientation_of(azimuth: float, expected: str):
    """Azimuths fall in 45-degree sectors centred on the eight directions."""
    assert orientation_of(azimuth) == expected


# --- save and load ------------------------------------------------------------


def test_save_load_round_trip(
    zone: ZoneComponent, core_zone: ZoneComponent, tmp_path: Path
):
    """An archetype reads back equal, and writing it twice gives the same bytes."""
    a = _archetype(
        zone, core_zone, Attic=AtticAssumptions(UseFraction=0.5, Conditioned=False)
    )
    path = a.save(tmp_path / "office.sbem.json")
    b = Archetype.load(path)
    assert b == a
    assert b.save(tmp_path / "again.sbem.json").read_bytes() == path.read_bytes()
    text = path.read_text()
    assert text.endswith("}\n")
    assert f'"SchemaVersion": "{ARCHETYPE_SCHEMA_VERSION}"' in text
    assert Archetype.from_json(a.to_json()) == a


# --- placing an archetype on a shoebox ------------------------------------------


@pytest.mark.parametrize(("w", "d"), [(20, 12), (10, 10), (50, 6)])
@pytest.mark.parametrize("share", [0.05, 0.4, 0.95])
def test_perimeter_depth_for_share(w: float, d: float, share: float):
    """The depth reproduces the share and leaves a core."""
    p = perimeter_depth_for_share(w, d, share)
    assert 0 < p < min(w, d) / 2
    assert (w * d - (w - 2 * p) * (d - 2 * p)) / (w * d) == pytest.approx(share)


@pytest.mark.parametrize("share", [0.0, 1.0])
def test_perimeter_depth_needs_a_core(share: float):
    """A share of 0 or 1 leaves no perimeter or no core."""
    with pytest.raises(ValueError, match="strictly between"):
        perimeter_depth_for_share(10, 10, share)


def test_from_archetype_one_group(zone: ZoneComponent):
    """One group is used for every zone, and the geometry is unchanged."""
    a = Archetype(
        Name="a",
        Groups=[ZoneGroup(Name="all", Zone=zone, FloorAreaShare=1.0)],
        Basement=BasementAssumptions(UseFraction=None, Conditioned=False),
    )
    geometry = _geometry(zoning="by_storey")
    m = Model.from_archetype(a, geometry, Weather=DefaultEPWZipPath)
    assert m.Zone == zone
    assert m.CoreZone is None
    assert m.geometry == geometry
    assert m.zone_definition("Block Core_Zone Storey 0") == zone


def test_from_archetype_core_and_perimeter(
    zone: ZoneComponent, core_zone: ZoneComponent
):
    """Perimeter and core groups map to Zone and CoreZone; the depth follows the shares."""
    m = Model.from_archetype(
        _archetype(zone, core_zone), _geometry(), Weather=DefaultEPWZipPath
    )
    assert m.Zone == zone
    assert m.CoreZone == core_zone
    g = m.geometry
    core_area = (g.w - 2 * g.perim_depth) * (g.d - 2 * g.perim_depth)
    assert 1 - core_area / (g.w * g.d) == pytest.approx(0.6)
    assert m.zone_definition("Block Core_Zone Storey 1") == core_zone
    assert m.zone_definition("Block Perimeter_Zone_2 Storey 1") == zone


def test_from_archetype_refuses_unplaceable_groups(
    zone: ZoneComponent, core_zone: ZoneComponent
):
    """Groups a shoebox cannot place, or a geometry without a core, are refused."""
    mixed = Archetype(
        Name="x",
        Groups=[
            ZoneGroup(Name="a", Zone=zone, FloorAreaShare=0.25, Exposure="perimeter"),
            ZoneGroup(Name="b", Zone=zone, FloorAreaShare=0.25, Exposure="core"),
            ZoneGroup(Name="c", Zone=zone, FloorAreaShare=0.5),
        ],
    )
    with pytest.raises(ValueError, match="every zone group has an exposure"):
        Model.from_archetype(mixed, _geometry(), Weather=DefaultEPWZipPath)
    with pytest.raises(ValueError, match="core/perimeter geometry"):
        Model.from_archetype(
            _archetype(zone, core_zone),
            _geometry(zoning="by_storey"),
            Weather=DefaultEPWZipPath,
        )


def test_core_zone_needs_core_perimeter_zoning(
    zone: ZoneComponent, core_zone: ZoneComponent
):
    """A Model with a CoreZone must have core zones."""
    with pytest.raises(ValidationError, match="CoreZone"):
        Model(
            geometry=_geometry(zoning="by_storey"),
            Zone=zone,
            CoreZone=core_zone,
            Attic=AtticAssumptions(UseFraction=None, Conditioned=False),
            Basement=BasementAssumptions(UseFraction=None, Conditioned=False),
            Weather=DefaultEPWZipPath,
        )


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version (EPINTERFACE_ENERGYPLUS_VERSION)",
)
def test_build_writes_each_group_to_its_zones(
    zone: ZoneComponent, core_zone: ZoneComponent, tmp_path: Path
):
    """Core zones get the core group's loads, perimeter zones the perimeter group's."""
    m = Model.from_archetype(
        _archetype(zone, core_zone), _geometry(), Weather=DefaultEPWZipPath
    )
    doc = m.build(SimulationPathConfig(output_dir=tmp_path))
    field = (
        "watts_per_floor_area"
        if doc.version >= (24, 1, 0)
        else "watts_per_zone_floor_area"
    )
    density = {
        lights.zone_or_zonelist_or_space_or_spacelist_name: getattr(lights, field)
        for lights in doc.get_collection("Lights")
    }
    core = {k: v for k, v in density.items() if "Core_Zone" in k}
    perimeter = {k: v for k, v in density.items() if "Perimeter_Zone" in k}
    assert len(core) == 2
    assert len(perimeter) == 8
    assert all(math.isclose(v, 2.5) for v in core.values())
    expected = zone.Operations.SpaceUse.Lighting.PowerDensity
    assert all(math.isclose(v, expected) for v in perimeter.values())


# --- unset floor-area shares (set by the geometry) ------------------------------


def _unset(zone: ZoneComponent, core_zone: ZoneComponent) -> Archetype:
    return Archetype(
        Name="umi",
        Groups=[
            ZoneGroup(Name="perimeter", Zone=zone, Exposure="perimeter"),
            ZoneGroup(Name="core", Zone=core_zone, Exposure="core"),
        ],
    )


def test_unset_shares_accepted(zone: ZoneComponent, core_zone: ZoneComponent):
    """Every share None is valid when each group has its own exposure."""
    a = _unset(zone, core_zone)
    assert not a.shares_set
    assert _archetype(zone, core_zone).shares_set
    single = Archetype(Name="one", Groups=[ZoneGroup(Name="all", Zone=zone)])
    assert not single.shares_set


def test_mixed_shares_refused(zone: ZoneComponent):
    """Some shares set and others unset is refused, naming the unset groups."""
    groups = [
        ZoneGroup(Name="a", Zone=zone, FloorAreaShare=1.0, Exposure="perimeter"),
        ZoneGroup(Name="b", Zone=zone, Exposure="core"),
    ]
    with pytest.raises(
        ValidationError, match=r"every group or for none; unset for \['b'\]"
    ):
        Archetype(Name="x", Groups=groups)


@pytest.mark.parametrize(
    "exposures", [("perimeter", None), ("core", "core"), (None, None)]
)
def test_unset_shares_need_distinct_exposures(
    zone: ZoneComponent, exposures: tuple[str | None, str | None]
):
    """With unset shares, the geometry can only tell groups apart by exposure."""
    groups = [
        ZoneGroup(Name=f"g{i}", Zone=zone, Exposure=e)  # pyright: ignore[reportArgumentType]
        for i, e in enumerate(exposures)
    ]
    with pytest.raises(ValidationError, match="its own Exposure"):
        Archetype(Name="x", Groups=groups)


def test_unset_shares_round_trip(
    zone: ZoneComponent, core_zone: ZoneComponent, tmp_path: Path
):
    """Unset shares are written as null and read back as None."""
    a = _unset(zone, core_zone)
    path = a.save(tmp_path / "umi.sbem.json")
    assert '"FloorAreaShare": null' in path.read_text()
    assert Archetype.load(path) == a


def test_from_archetype_unset_shares_keeps_geometry(
    zone: ZoneComponent, core_zone: ZoneComponent
):
    """With unset shares the shoebox's own perimeter depth sets the areas."""
    geometry = _geometry(perim_depth=4.0)
    m = Model.from_archetype(
        _unset(zone, core_zone), geometry, Weather=DefaultEPWZipPath
    )
    assert m.geometry == geometry
    assert m.Zone == zone
    assert m.CoreZone == core_zone
    with pytest.raises(ValueError, match="core/perimeter geometry"):
        Model.from_archetype(
            _unset(zone, core_zone),
            _geometry(zoning="by_storey"),
            Weather=DefaultEPWZipPath,
        )


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version (EPINTERFACE_ENERGYPLUS_VERSION)",
)
def test_build_unset_shares_areas_follow_geometry(
    zone: ZoneComponent, core_zone: ZoneComponent, tmp_path: Path
):
    """Built core and perimeter floor areas are those of w, d and perim_depth."""
    from epinterface.geometry import get_zone_floor_area

    geometry = _geometry(perim_depth=4.0)
    m = Model.from_archetype(
        _unset(zone, core_zone), geometry, Weather=DefaultEPWZipPath
    )
    doc = m.build(SimulationPathConfig(output_dir=tmp_path))
    areas = {z.name: get_zone_floor_area(doc, z.name) for z in doc["Zone"]}
    core = sum(a for n, a in areas.items() if "Core_Zone" in n)
    total = sum(areas.values())
    assert core / total == pytest.approx((20 - 8) * (12 - 8) / (20 * 12), rel=1e-6)


# --- any number of zone groups ---------------------------------------------------

FOUR_GROUPS: list[tuple[str, float, str]] = [
    ("office/core", 0.30, "core"),
    ("office/perimeter", 0.35, "perimeter"),
    ("corridor/core", 0.10, "core"),
    ("lab/perimeter", 0.25, "perimeter"),
]


def _lab_zone(zone: ZoneComponent) -> ZoneComponent:
    """A zone definition with its own lighting density and facade assembly."""
    lab = zone.model_copy(deep=True)
    lab.Name = "lab_zone"
    lab.Operations.SpaceUse.Lighting.PowerDensity = 7.5
    assemblies = lab.Envelope.Assemblies
    assemblies.FacadeAssembly = assemblies.FacadeAssembly.model_copy(
        update={"Name": "lab facade"}
    )
    return lab


def _four_groups(zone: ZoneComponent, core_zone: ZoneComponent) -> Archetype:
    zones = {
        "office/core": core_zone,
        "office/perimeter": zone,
        "corridor/core": core_zone,
        "lab/perimeter": _lab_zone(zone),
    }
    return Archetype(
        Name="mixed",
        Groups=[
            ZoneGroup(Name=n, Zone=zones[n], FloorAreaShare=s, Exposure=e)  # pyright: ignore[reportArgumentType]
            for n, s, e in FOUR_GROUPS
        ],
    )


def _rect_area(r: tuple[float, float, float, float]) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def _touches_facade(r: tuple[float, float, float, float], g: ShoeboxGeometry) -> bool:
    x1, y1 = g.x + g.w, g.y + g.d
    return any(
        math.isclose(a, b, abs_tol=1e-9)
        for a, b in ((r[0], g.x), (r[1], g.y), (r[2], x1), (r[3], y1))
    )


@pytest.mark.parametrize(
    "layout",
    [
        [(s, e) for _, s, e in FOUR_GROUPS],
        [(0.5, None), (0.3, None), (0.2, None)],
        [(0.4, "perimeter"), (0.6, "perimeter")],
        [(0.7, "perimeter"), (0.3, "core")],
        [(0.6, "perimeter"), (0.1, "core"), (0.2, "core"), (0.1, "core")],
        [
            (0.1, "perimeter"),
            (0.2, "perimeter"),
            (0.3, "perimeter"),
            (0.1, "perimeter"),
            (0.3, "core"),
        ],
        [(1.0, None)],
    ],
)
def test_group_footprints_follow_shares(layout: list[tuple[float, str | None]]):
    """Each group's rectangles cover its share; perimeter groups touch the facade, core groups do not."""
    g = _geometry(
        zone_groups=[ZoneGroupLayout(share=s, exposure=e) for s, e in layout]  # pyright: ignore[reportArgumentType]
    )
    footprints = g.group_footprints()
    assert len(footprints) == len(layout)
    for (share, exposure), rects in zip(layout, footprints, strict=True):
        assert sum(map(_rect_area, rects)) == pytest.approx(
            share * g.footprint_area, rel=1e-8
        )
        if exposure == "perimeter" or exposure is None:
            assert all(_touches_facade(r, g) for r in rects)
        has_both = {e for _, e in layout} == {"core", "perimeter"}
        if exposure == "core" and has_both:
            assert not any(_touches_facade(r, g) for r in rects)


def test_zone_groups_validation():
    """Shares must sum to 1 and exposures be all set or all unset."""
    with pytest.raises(ValidationError, match="sum to 1"):
        _geometry(zone_groups=[ZoneGroupLayout(share=0.5)])
    with pytest.raises(ValidationError, match="every zone group has an exposure"):
        _geometry(
            zone_groups=[
                ZoneGroupLayout(share=0.5, exposure="core"),
                ZoneGroupLayout(share=0.5),
            ]
        )
    with pytest.raises(ValidationError, match="at least one group"):
        _geometry(zone_groups=[])


@pytest.mark.parametrize(
    ("basement", "roof_height"), [(False, None), (True, None), (True, 2.5)]
)
def test_group_geometry_zone_areas(doc, basement: bool, roof_height: float | None):
    """One zone per group per storey, with floor areas proportional to the shares."""
    g = _geometry(
        basement=basement,
        roof_height=roof_height,
        zone_groups=[ZoneGroupLayout(share=s, exposure=e) for _, s, e in FOUR_GROUPS],  # pyright: ignore[reportArgumentType]
    )
    g.add(doc)
    storeys = g.num_stories + (1 if basement else 0)
    names = {z.name for z in doc["Zone"]}
    expected = {
        g.group_zone_name(i, k) for i in range(len(FOUR_GROUPS)) for k in range(storeys)
    }
    assert names - {"Attic"} == expected
    assert ("Attic" in names) == (roof_height is not None)
    for name in expected:
        index = g.zone_group_index(name)
        assert index is not None
        assert get_zone_floor_area(doc, name) == pytest.approx(
            FOUR_GROUPS[index][1] * g.footprint_area, rel=1e-6
        )
    surfaces = doc["BuildingSurface:Detailed"]
    for srf in surfaces:
        if srf.outside_boundary_condition.lower() == "surface":
            other = surfaces.get(srf.outside_boundary_condition_object)
            assert other is not None
            assert other.zone_name != srf.zone_name
            assert srf.name.startswith(srf.zone_name) or "attic" in srf.name.lower()
    # every group zone above ground has a window on its facade, core zones none
    glazed = {
        surfaces.get(w.building_surface_name).zone_name
        for w in doc["FenestrationSurface:Detailed"]
    }
    for name in expected:
        index = g.zone_group_index(name)
        assert index is not None
        above_ground = not (basement and name.endswith("Storey 0"))
        assert (name in glazed) == (
            FOUR_GROUPS[index][2] == "perimeter" and above_ground
        )


def test_from_archetype_any_number_of_groups(
    zone: ZoneComponent, core_zone: ZoneComponent
):
    """Four groups become zone groups of the shoebox, each with its zone definition."""
    a = _four_groups(zone, core_zone)
    geometry = _geometry()
    m = Model.from_archetype(a, geometry, Weather=DefaultEPWZipPath)
    assert m.geometry.zone_groups == [
        ZoneGroupLayout(share=s, exposure=e)  # pyright: ignore[reportArgumentType]
        for _, s, e in FOUR_GROUPS
    ]
    assert m.GroupZones == [g.Zone for g in a.Groups]
    assert m.Zone == zone  # the largest perimeter group
    assert m.CoreZone is None
    for i, group in enumerate(a.Groups):
        assert m.zone_definition(m.geometry.group_zone_name(i, 1)) == group.Zone
    assert m.zone_definition("Attic") == zone


def test_from_archetype_groups_without_exposure(zone: ZoneComponent):
    """Groups without exposures are placed as strips; any zoning is accepted."""
    a = Archetype(
        Name="uses",
        Groups=[
            ZoneGroup(Name=n, Zone=zone, FloorAreaShare=s)
            for n, s in (("a", 0.2), ("b", 0.5), ("c", 0.3))
        ],
    )
    m = Model.from_archetype(
        a, _geometry(zoning="by_storey"), Weather=DefaultEPWZipPath
    )
    assert m.geometry.zone_groups is not None
    assert [g.exposure for g in m.geometry.zone_groups] == [None] * 3
    assert m.geometry.zones_per_storey == 3


def test_group_zones_need_zone_groups(zone: ZoneComponent):
    """GroupZones and the geometry's zone groups go together, one to one."""
    common = {
        "Zone": zone,
        "Attic": AtticAssumptions(UseFraction=None, Conditioned=False),
        "Basement": BasementAssumptions(UseFraction=None, Conditioned=False),
        "Weather": DefaultEPWZipPath,
    }
    with pytest.raises(ValidationError, match="set together"):
        Model(geometry=_geometry(), GroupZones=[zone], **common)
    grouped = _geometry(zone_groups=[ZoneGroupLayout(share=1.0)])
    with pytest.raises(ValidationError, match="set together"):
        Model(geometry=grouped, **common)
    with pytest.raises(ValidationError, match="1 zone groups"):
        Model(geometry=grouped, GroupZones=[zone, zone], **common)


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version (EPINTERFACE_ENERGYPLUS_VERSION)",
)
def test_build_four_groups_loads_and_envelope(
    zone: ZoneComponent, core_zone: ZoneComponent, tmp_path: Path
):
    """Each zone gets its group's loads, and its facade its group's assembly."""
    a = _four_groups(zone, core_zone)
    m = Model.from_archetype(a, _geometry(), Weather=DefaultEPWZipPath)
    doc = m.build(SimulationPathConfig(output_dir=tmp_path))
    field = (
        "watts_per_floor_area"
        if doc.version >= (24, 1, 0)
        else "watts_per_zone_floor_area"
    )
    density = {
        lights.zone_or_zonelist_or_space_or_spacelist_name: getattr(lights, field)
        for lights in doc.get_collection("Lights")
    }
    assert len(density) == 8
    for name, value in density.items():
        index = m.geometry.zone_group_index(name)
        assert index is not None
        expected = a.Groups[index].Zone.Operations.SpaceUse.Lighting.PowerDensity
        assert math.isclose(value, expected)
    facades = {}
    for srf in doc["BuildingSurface:Detailed"]:
        if (
            srf.outside_boundary_condition.lower() == "outdoors"
            and srf.surface_type.lower() == "wall"
        ):
            facades.setdefault(srf.zone_name, set()).add(srf.construction_name)
    lab = {m.geometry.group_zone_name(3, k) for k in range(2)}
    office = {m.geometry.group_zone_name(1, k) for k in range(2)}
    assert set(facades) == lab | office
    assert all(facades[n] == {"lab facade"} for n in lab)
    reference = zone.Envelope.Assemblies.FacadeAssembly.Name
    assert all(facades[n] == {reference} for n in office)


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="simulating needs EnergyPlus",
)
def test_simulate_four_groups_floor_areas_match_shares(
    zone: ZoneComponent, core_zone: ZoneComponent, tmp_path: Path
):
    """A four-group archetype simulates, and EnergyPlus's zone floor areas match the shares."""
    import sqlite3

    a = _four_groups(zone, core_zone)
    m = Model.from_archetype(
        a, _geometry(basement=True, roof_height=2.0), Weather=DefaultEPWZipPath
    )
    m.Basement = BasementAssumptions(UseFraction=None, Conditioned=False)
    result = m.run(eplus_parent_dir=tmp_path)
    result.sql.close()
    assert result.output_dir is not None
    assert "** Severe  **" not in result.err_text
    (sql_path,) = result.output_dir.glob("*.sql")
    with sqlite3.connect(sql_path) as conn:
        rows = conn.execute("SELECT ZoneName, FloorArea FROM Zones").fetchall()
    by_group: dict[int, float] = {}
    for name, area in rows:
        # zone names are upper-cased in the SQLite output
        match = re.fullmatch(r"BLOCK GROUP(\d+) STOREY (\d+)", name.upper())
        if match is None or match.group(2) == "0":
            continue  # the attic and the basement storey
        index = int(match.group(1)) - 1
        by_group[index] = by_group.get(index, 0.0) + area
    assert len(by_group) == len(FOUR_GROUPS)
    total = sum(by_group.values())
    assert total == pytest.approx(m.geometry.total_living_area, rel=1e-3)
    for index, (_, share, _) in enumerate(FOUR_GROUPS):
        assert by_group[index] / total == pytest.approx(share, rel=1e-3)
    assert result.energy_and_peak.notna().all()
