# Multi-group archetypes (SBEM fork)

This page describes what this fork of epinterface adds for archetypal: an SBEM
archetype made of several zone groups, saved to and loaded from a JSON file, and placed
on a shoebox by the SBEM builder. Every change here is also offered upstream.

| Roadmap item | What it adds |
|---|---|
| UP-1 | idfkit replaces archetypal and eppy. `epinterface.sbem.components`, `epinterface.sbem.archetype` and `epinterface.sbem.builder` import without archetypal, eppy or a generated Prisma client. PyYAML is declared. |
| UP-2, zone groups | `epinterface.sbem.archetype`: `Archetype`, `ZoneGroup`, `BuildingGeometry`, save and load. `Model.from_archetype` and `Model.CoreZone` in the builder. |
| UP-2, unset shares | Floor-area shares may all be `None`: the geometry sets them when the archetype is applied. |
| UP-2, any number of groups | `Model.from_archetype` places any number of groups: one zone per group on each storey, each with its group's zone definition. |

## Classes

All classes are pydantic v2 models in `epinterface.sbem.archetype`. Field names follow
SBEM's PascalCase. `ZoneGroup`, `BuildingGeometry` and `Archetype` forbid unknown
fields.

### `Archetype`

A building described by its zone groups and building-level characteristics.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `Name` | `str` | required | Name of the archetype. |
| `SchemaVersion` | `str` | `"1.0"` | Version of the file format. Any other value is refused on load. |
| `Groups` | `list[ZoneGroup]` | required, at least one | The zone groups. |
| `Geometry` | `BuildingGeometry` | all fields `None` | Geometry characteristics of the building. |
| `Attic` | `AtticAssumptions` | unused, unconditioned | Attic assumptions. |
| `Basement` | `BasementAssumptions` | unused, unconditioned | Basement assumptions. |

Validation:

- group names are unique;
- either every `FloorAreaShare` is set and the shares sum to 1 within `1e-6`
  (`SHARE_SUM_TOLERANCE`), or every share is `None`;
- with unset shares and more than one group, each group has an `Exposure` and no two
  groups have the same one, since a geometry can only split floor area between core
  and perimeter.

Methods and properties:

- `save(path) -> Path` writes indented JSON, keys in model order, ending with a newline.
  Two saves of the same archetype are byte-identical. The conventional suffix is
  `.sbem.json` (`ARCHETYPE_FILE_SUFFIX`).
- `Archetype.load(path)` reads a file written by `save`.
- `to_json() -> str` and `Archetype.from_json(text)` do the same on text.
- `group(name) -> ZoneGroup` returns a group by name (`KeyError` if absent).
- `shares_set -> bool` tells whether the shares are set.

### `ZoneGroup`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `Name` | `str` | required | Unique within the archetype, for example `"office/perimeter"`. |
| `Zone` | `ZoneComponent` | required | The SBEM zone definition (`Operations`, `Envelope`). |
| `FloorAreaShare` | `float \| None` | `None` | Share of conditioned floor area, in (0, 1]. `None`: set by the geometry when applied. |
| `Exposure` | `"core" \| "perimeter" \| None` | `None` | Where the group's zones sit. `None`: not tied to an exposure, for example a single-zone or space-use-only layout. |

### `BuildingGeometry`

Geometry characteristics, as intensities. They describe the building and do not
generate geometry. Every field is optional; `None` means not known. Areas are relative
to the conditioned floor area.

| Field | Type | Meaning |
|---|---|---|
| `Storeys` | `int \| None` | Number of storeys above ground, at least 1. |
| `ConditionedFloorArea` | `float \| None` | Conditioned floor area, m². |
| `WindowToWallRatio` | `dict[Orientation, float] \| None` | Window-to-wall ratio of each orientation, in [0, 1]. |
| `FacadeAreaPerFloorArea` | `dict[Orientation, float] \| None` | Gross exterior wall area of each orientation (windows included) per floor area. |
| `RoofAreaPerFloorArea` | `float \| None` | Exterior roof area per floor area. |
| `ExposedFloorAreaPerFloorArea` | `float \| None` | Floor area exposed to outdoor air per floor area. |
| `GroundContactAreaPerFloorArea` | `float \| None` | Floor and wall area in contact with the ground per floor area. |

`Orientation` is one of `"N"`, `"NE"`, `"E"`, `"SE"`, `"S"`, `"SW"`, `"W"`, `"NW"`:
eight 45° sectors of azimuth centred on those directions (`ORIENTATIONS`,
`orientation_of(azimuth_deg)`). An orientation map must give all eight; it is stored in
that order.

Helpers: `BuildingGeometry.uniform(value)` gives the same value for every orientation;
`WindowAreaPerFloorArea` is facade area times ratio for each orientation;
`OverallWindowToWallRatio` is the facade-area-weighted ratio (the plain mean when facade
areas are unknown).

### `AtticAssumptions` and `BasementAssumptions`

Unchanged from the builder, which re-exports them: `UseFraction: float | None` in
[0, 1] and `Conditioned: bool`.

## Placing an archetype on a shoebox

`Model.from_archetype(archetype, geometry, **kwargs)` in `epinterface.sbem.builder`
returns a `Model` for a `ShoeboxGeometry`. `kwargs` are other `Model` fields, such as
`Weather`.

| Groups | Shares | Result |
|---|---|---|
| One | set or unset | Its zone definition is used for every zone. The geometry is unchanged. |
| `perimeter` and `core` | set | The perimeter group's zone definition becomes `Model.Zone`, the core group's `Model.CoreZone`. The geometry must be core/perimeter. Its `perim_depth` is replaced by the depth that gives the perimeter share (`perimeter_depth_for_share(w, d, share)`). |
| `perimeter` and `core` | unset | As above, but the geometry is unchanged: core and perimeter areas follow from `w`, `d` and `perim_depth`. |
| Any other set | set | One zone per group on each storey (see below). Any `zoning` is accepted. |
| Any other set | unset | `ValueError`: the archetype's validation already refuses most of these. |
| Exposures set for some groups only | | `ValueError`. |

`Model.CoreZone` (default `None`) is the zone definition of the core zones of a
core/perimeter shoebox; `Model.zone_definition(zone_name)` returns the definition a
zone gets. With one or two groups, the envelope assemblies, window, ground
temperatures and the attic and basement zones follow `Model.Zone`, the perimeter
group, which holds the facade. The archetype's `Geometry` is descriptive:
`from_archetype` does not read it.

### One zone per group

For any other set of groups, `from_archetype` copies the geometry with
`zone_groups`, one `ZoneGroupLayout(share, exposure)` per archetype group, in
order, and sets `Model.GroupZones` to the groups' zone definitions, in the same
order.

On each storey, basement included, the shoebox then has one zone per group,
named `"Block Group{n} Storey {k}"` (`ShoeboxGeometry.group_zone_name(i, k)`, with
`n = i + 1` and storey `k` counted from 0 at the lowest storey).
`ShoeboxGeometry.zone_group_index(name)` returns the group index of a zone, or
`None` for the attic. `ShoeboxGeometry.group_footprints()` gives each group's
footprint as rectangles:

- **Perimeter and core groups.** The perimeter depth is the one that gives the
  perimeter groups' total share. The perimeter ring is four rectangles of that
  depth in a pinwheel (south, east, north, west, counter-clockwise from the
  south-west corner). Walking it, the ring is cut at the perimeter groups'
  cumulative shares, so each perimeter group gets a chain of rectangles that all
  touch the facade. The core is cut across its long axis into one strip per core
  group.
- **No exposures, or one kind only.** The footprint is cut across its long axis
  into one strip per group, each spanning the full depth.

Each group's floor area is its share of the footprint, to within a cut snapped
by at most 2 mm onto a ring corner. A group's rectangles are built as separate
zones, matched with their neighbours, and then merged into one zone; the walls
between two rectangles of the same zone are removed.

Each zone takes its group's zone definition: loads, schedules, conditioning and
envelope. After the reference envelope is assigned to every surface,
`assign_zone_envelope` gives each group's facade, roof, ground slab and ground
walls, floors and ceilings (between its storeys, to the basement and to the
attic), windows and internal mass its group's assemblies. Walls between two
groups keep the partition assembly of `Model.Zone`, the reference group, so both
sides of a partition match. The reference group is the largest perimeter group
(the largest group without exposures); it also sets the attic and basement zone
definitions, the ground temperatures and the COPs and fuels of
`standard_results_postprocess`.

## Example

```python
from epinterface.sbem.archetype import Archetype, BuildingGeometry, ZoneGroup

archetype = Archetype(
    Name="office",
    Groups=[
        ZoneGroup(Name="perimeter", Zone=perimeter_zone, Exposure="perimeter"),
        ZoneGroup(Name="core", Zone=core_zone, Exposure="core"),
    ],
    Geometry=BuildingGeometry(WindowToWallRatio=BuildingGeometry.uniform(0.3)),
)
archetype.save("office.sbem.json")
assert Archetype.load("office.sbem.json") == archetype
```

## Compatibility with upstream epinterface

Upstream epinterface has no archetype model, so an archetype file is readable only by
this fork until upstream accepts these changes. `SchemaVersion` lets a reader tell
which version wrote a file.
