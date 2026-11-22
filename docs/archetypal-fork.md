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
| UP-2, schema version | Archetype files record schema 1.1; 1.0 files still load; newer files are refused for their version. |
| UP-2, ratios by orientation | `BuildingGeometry.WindowToWallRatio` is applied by the builder: `ShoeboxGeometry.wwr_by_orientation`. |
| UP-2, week slots | Holiday and design-day slots on `WeekComponent`. |
| UP-2, infiltration schedule | An hourly schedule on `InfiltrationComponent`. |
| UP-2, heat recovery | Numeric sensible and latent heat-recovery effectiveness on `VentilationComponent`. |
| UP-8 | Specific fan power and a fan end use, the ideal loads' supply-air temperature limits, and an energy input ratio linear in outdoor temperature. |
| UP-9, fractional year sum | `YearComponent.fractional_year_sum` counts the real weekdays of each month (a defect fix). |
| UP-9, provider `Both` | `Provider="Both"` gives natural and mechanical ventilation (a defect fix). |
| UP-9, natural-ventilation limits | Outdoor temperature and humidity limits, an indoor limit and wind and buoyancy switches on `VentilationComponent`. |
| UP-9, scheduled ventilation | Air changes, schedule and minimum zone temperature of scheduled ventilation on `VentilationComponent`. |
| UP-9, mechanical ventilation schedule | A schedule of the mechanical outdoor air on `VentilationComponent`. |
| UP-9, ideal-loads limits | Heating and cooling limit types, flows and capacities per floor area on `ConditioningSystemsComponent`. |
| UP-9, availability | Heating and cooling availability schedules on `ConditioningSystemsComponent`. |
| UP-9, adiabatic assemblies | Adiabatic facade, roof, ground, partition and slab flags on `EnvelopeAssemblyComponent`. |
| UP-9, internal partitions | Partition area per floor area on `EnvelopeAssemblyComponent`, written as internal mass. |

## Classes

All classes are pydantic v2 models in `epinterface.sbem.archetype`. Field names follow
SBEM's PascalCase. `ZoneGroup`, `BuildingGeometry` and `Archetype` forbid unknown
fields.

### `Archetype`

A building described by its zone groups and building-level characteristics.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `Name` | `str` | required | Name of the archetype. |
| `SchemaVersion` | `str` | `"1.1"` (`ARCHETYPE_SCHEMA_VERSION`) | Version of the file format. Versions in `SUPPORTED_ARCHETYPE_SCHEMA_VERSIONS` (`"1.0"`, `"1.1"`) are read and become `"1.1"`; any other is refused. |
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
- `Archetype.load(path)` reads a file written by `save`, checking its schema
  version first (see [Schema versions](#schema-versions-up-2)).
- `Archetype.schema_version_of(path) -> str` returns the version a file
  records, without validating the rest.
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
| `WindowToWallRatio` | `dict[Orientation, float] \| None` | Window-to-wall ratio of each orientation, in [0, 1]. Applied by `Model.from_archetype` (see below). |
| `FacadeAreaPerFloorArea` | `dict[Orientation, float] \| None` | Gross exterior wall area of each orientation (windows included) per floor area. |
| `RoofAreaPerFloorArea` | `float \| None` | Exterior roof area per floor area. |
| `ExposedFloorAreaPerFloorArea` | `float \| None` | Floor area exposed to outdoor air per floor area. |
| `GroundContactAreaPerFloorArea` | `float \| None` | Floor and wall area in contact with the ground per floor area. |

`Orientation` is one of `"N"`, `"NE"`, `"E"`, `"SE"`, `"S"`, `"SW"`, `"W"`, `"NW"`:
eight 45° sectors of azimuth centred on those directions (`ORIENTATIONS`,
`orientation_of(azimuth_deg)`). They are defined in `epinterface.geometry` and
re-exported by `epinterface.sbem.archetype`. An orientation map must give all eight; it is stored in
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

When the archetype's `Geometry.WindowToWallRatio` is set, `from_archetype`
copies it to the geometry's `wwr_by_orientation`, which replaces `wwr`; see
[Window-to-wall ratios by orientation](#window-to-wall-ratios-by-orientation-up-2).

`Model.CoreZone` (default `None`) is the zone definition of the core zones of a
core/perimeter shoebox; `Model.zone_definition(zone_name)` returns the definition a
zone gets. With one or two groups, the envelope assemblies, window, ground
temperatures and the attic and basement zones follow `Model.Zone`, the perimeter
group, which holds the facade. Of the archetype's `Geometry`, `from_archetype`
reads only `WindowToWallRatio`; the other characteristics are descriptive.

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

## Schema versions (UP-2)

An archetype file records the version of its format in `SchemaVersion`, so a
reader can tell whether it understands the file.

| Version | Written by | Adds |
|---|---|---|
| `1.0` | the fork up to UP-4 | Zone groups, unset shares, geometry characteristics. |
| `1.1` | this fork | The optional fields of UP-8 and of UP-2's extras on this page: specific fan power, supply-air limits, the energy input ratio's slope and reference, heat-recovery effectiveness, the infiltration schedule, and the holiday and design-day slots. |

Every 1.0 file is a valid 1.1 file: the added fields are optional and their
defaults reproduce the 1.0 behaviour. Reading works as follows.

| File records | Result |
|---|---|
| `"1.0"`, `"1.1"`, or no `SchemaVersion` (read as `"1.0"`) | Loaded; the archetype's `SchemaVersion` becomes `"1.1"`, so saving it again writes `"1.1"`. |
| Any other version | `ArchetypeSchemaVersionError` (a `ValueError`), raised by `Archetype.from_json` and `Archetype.load` before the rest of the file is read, so a newer file is refused for its version rather than for fields this version lacks. In `Archetype.model_validate` it surfaces as a `ValidationError` with the same message. |

Constants: `ARCHETYPE_SCHEMA_VERSION = "1.1"`,
`SUPPORTED_ARCHETYPE_SCHEMA_VERSIONS = ("1.0", "1.1")`.
`tests/data/archetype_v1_0.sbem.json.gz` is a file written by the 1.0 fork; a
test loads it.

## Window-to-wall ratios by orientation (UP-2)

The archetype already held the envelope and window ratios by orientation
(`BuildingGeometry.FacadeAreaPerFloorArea` and `WindowToWallRatio`), but the
shoebox had one `wwr`. The shoebox now takes a ratio per orientation.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `ShoeboxGeometry.wwr_by_orientation` (`epinterface.geometry`) | `dict[Orientation, float] \| None`, all eight orientations, each in [0, 1] | – | `None` | Window-to-wall ratio of each orientation. `None`: `wwr` for every wall. |

Each exterior wall of a main zone takes the ratio of the sector its outward
normal faces in the final model: the azimuth is corrected for the scene
context's rotation (`ShoeboxGeometry.window_to_wall_ratio(azimuth_deg)`). A
wall with a ratio of 0 gets no window. The window keeps its ribbon shape, so
its area is 0.999 × ratio × wall area. An unrotated shoebox faces N, E, S and W
only, so the four intermediate ratios apply only to rotated scenes.

`Model.from_archetype` copies `BuildingGeometry.WindowToWallRatio`, when set, to
`wwr_by_orientation`. `FacadeAreaPerFloorArea` stays descriptive: a shoebox's
facade areas follow from its width, depth, height and storeys, and opposite
facades are always equal, so eight independent areas cannot be honoured.

## Holiday and design-day slots (UP-2)

An SBEM week had seven days only. The builder filled the holiday slot of each
`Schedule:Week:Daily` with Sunday and the design-day slots with Monday (or with a
day the caller chose, such as the thermostat's constant setpoint). A week can
now say what those days are.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `WeekComponent.Holiday` | `DayComponent \| None` | the week's | `None` | Day used on holidays. `None`: Sunday. |
| `WeekComponent.SummerDesignDay` | `DayComponent \| None` | the week's | `None` | Day used on summer design days. `None`: the caller's design day, else Monday. |
| `WeekComponent.WinterDesignDay` | `DayComponent \| None` | the week's | `None` | Day used on winter design days. `None`: the caller's design day, else Monday. |

Each set slot must have the week's type limits. `add_week_to_idf` writes it to
the matching field of `Schedule:Week:Daily`; a week's own design day wins over
the one the caller passes. `WeekComponent.Days`, `AverageValue` and `bounds`
still cover the seven weekdays only. Holidays take effect only on the days the
run declares as holidays (`RunPeriodControl:SpecialDays`, or the weather file's
when the run period uses them).

## Infiltration schedule (UP-2)

SBEM's infiltration was constant in time: the builder gave it a schedule of 1.
A detailed model's infiltration often follows a schedule (fans on, doors open),
so `InfiltrationComponent` now carries one.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `InfiltrationComponent.Schedule` | `YearComponent \| None` | – (multiplier) | `None` | Hourly multiplier of the infiltration flow. Its type limits must be `Fraction` or `AnyNumber`. `None`: constant flow. |

The builder writes the schedule as a `Schedule:Year` and uses it as the
`ZoneInfiltration:DesignFlowRate` schedule. The attic and basement
infiltration components take their own `Schedule`. `YearScheduleCategory` gains
`"Infiltration"` for such schedules.

## Heat-recovery effectiveness (UP-2)

SBEM's `VentilationComponent.HRV` is a category (`NoHRV`, `Sensible`,
`Enthalpy`); the effectiveness was a constant of epinterface. UMI and detailed
models hold numbers, so the component now holds them too.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `VentilationComponent.SensibleHeatRecoveryEffectiveness` | `float \| None`, in [0, 1] | – | `None` | Sensible effectiveness at 100% airflow. Used when `HRV` is not `NoHRV`. `None`: the assumed constant 0.70. |
| `VentilationComponent.LatentHeatRecoveryEffectiveness` | `float \| None`, in [0, 1] | – | `None` | Latent effectiveness at 100% airflow. Used when `HRV` is `Enthalpy`. `None`: the assumed constant 0.65. |

The builder writes them to each zone's ideal loads template
(`sensible_heat_recovery_effectiveness`, `latent_heat_recovery_effectiveness`);
EnergyPlus ignores them when `HRV` is `NoHRV`. The properties
`sensible_heat_recovery_effectiveness` and `latent_heat_recovery_effectiveness`
return the value used.

## SBEM energy beyond a constant COP (UP-8)

SBEM converts the ideal loads' delivered energy to consumed energy. Without UP-8 it
divides by one constant `SystemCOP × DistributionCOP` per mode and reports no fan
energy. UP-8 adds three things, all optional; their defaults reproduce the earlier
results exactly.

### `ConditioningSystemsComponent` (`epinterface.sbem.components.systems`)

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `MaximumHeatingSupplyAirTemperature` | `float`, in (0, 100) | °C | `30.0` | The ideal loads' maximum supply air temperature when heating (`HVACTemplate:Zone:IdealLoadsAirSystem`). Must be above the cooling limit. |
| `MinimumCoolingSupplyAirTemperature` | `float`, in (-100, 50) | °C | `13.0` | The ideal loads' minimum supply air temperature when cooling. |
| `SpecificFanPower` | `float \| None`, ≥ 0 | W/(m³/s) | `None` | Fan electric power per volume flow of supply air. `None`: no fan end use. |

The defaults are the values the builder wrote before UP-8.

### `ThermalSystemComponent` (`epinterface.sbem.components.systems`)

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `EIRTemperatureSlope` | `float` | 1/K | `0.0` | Change of the energy input ratio (1/`SystemCOP`) per kelvin of outdoor dry-bulb temperature above the reference. `0`: a constant COP. |
| `EIRReferenceTemperature` | `float \| None` | °C | `None` | Outdoor temperature at which the energy input ratio is 1/`SystemCOP`. Required when the slope is not 0. |

`ThermalSystemComponent.energy_input_ratio(t_out)` returns, for each outdoor
temperature `T`,

```text
EIR(T) = max(0, 1/SystemCOP + EIRTemperatureSlope × (T − EIRReferenceTemperature)) / DistributionCOP
```

The ratio is clipped at 0 so that no hour consumes negative energy.

### What the builder does with them

- **Supply limits.** Each zone's ideal loads template takes the two temperatures of
  the zone's conditioning.
- **Fan end use.** When any zone definition sets `SpecificFanPower`, the model also
  requests the hourly output `Zone Ideal Loads Supply Air Standard Density Volume
  Flow Rate` (`SUPPLY_AIR_VOLUME_VARIABLE`). `Model.fan_energy_hourly(sql)` sums,
  over zones, the hour's mean flow times the specific fan power of the zone's
  conditioning (`Model.conditioning_definition(zone_name)`: the group's definition,
  or `Zone` for the attic and basement), and divides by the conditioned floor area.
  `standard_results_postprocess` then adds a `Fans` end use, counted as
  `Electricity` in the utilities and peaks. Without a specific fan power the
  results have no `Fans` entry, as before.
- **Temperature-dependent efficiency.** When the reference zone's heating or
  cooling system has a non-zero slope, each hour's use is that hour's delivered
  energy times `EIR(T_out)`, with `T_out` from `Site Outdoor Air Drybulb
  Temperature`; monthly use is the sum of the hours. Like the constant COP, the
  slope applies to the whole building's heating or cooling meter.

`epinterface.analysis.energy_and_peak.standard_results_postprocess` takes the
matching optional arguments `heat_eir_hourly`, `cool_eir_hourly` (consumed ÷
delivered, one value per hour) and `fan_hourly` (kWh/m² per hour).

## Fraction of a year schedule (UP-9)

`YearComponent.fractional_year_sum(year)` returns a schedule's mean value over
every hour of a calendar year; the builder divides each zone's mean hot-water
flow by it to get the `WaterUse:Equipment` peak flow. It counted each month's
weekdays as if every month began on a Tuesday, which skewed the peak flow of
any schedule whose weekdays differ. It now counts the weekdays of the given
year's real calendar, so the result equals the hour-by-hour mean of the
schedule. The builder still evaluates the schedule over 2018.

## Ventilation provider `Both` (UP-9)

`VentilationComponent.Provider` accepts `"Both"`, natural and mechanical
ventilation, but the builder gave it mechanical ventilation only. It now
writes both: the ideal loads' outdoor air (as for `"Mechanical"`) and the
`ZoneVentilation:WindandStackOpenArea` through the zone's windows (as for
`"Natural"`, see `ZoneOperationsComponent.add_natural_ventilation_to_idf_zone`).
`Ventilation.Schedule` opens the windows in both cases.

## Natural-ventilation limits and switches (UP-9)

SBEM opened the windows between fixed outdoor temperatures of 12 and 25 °C,
with wind but no stack effect. `VentilationComponent`
(`epinterface.sbem.components.systems`) now holds these settings. The names
are UMI's `ZoneVentilation` names.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `NatVentMinOutdoorAirTemp` | `float`, in [-100, 100] | °C | `12.0` | Windows stay closed below this outdoor dry-bulb temperature. |
| `NatVentMaxOutdoorAirTemp` | `float`, in [-100, 100] | °C | `25.0` | Windows stay closed above it. Must be above the minimum. |
| `NatVentMaxRelHumidity` | `float \| None`, in [0, 100] | % | `None` | Windows stay closed while the outdoor relative humidity is above it. `None`: no limit. |
| `NatVentZoneTempSetpoint` | `float \| None`, in [-100, 100] | °C | `None` | Windows stay closed while the zone air is colder. `None`: no indoor limit. |
| `IsWindOn` | `bool` | – | `True` | Wind drives air through the open windows. |
| `IsBuoyancyOn` | `bool` | – | `False` | The stack effect drives air through the open windows. `False` reproduces the earlier model, which had none (UMI's default is `True`). |

The builder writes them to each zone's `ZoneVentilation:WindandStackOpenArea`
(used when `Provider` is `Natural` or `Both`):

- the temperatures go to its minimum and maximum outdoor temperatures and its
  minimum indoor temperature;
- without wind, the opening effectiveness is 0, which removes the wind term;
- with buoyancy, the height difference is half the height of the zone's
  tallest window (EnergyPlus's neutral plane at mid-height of a single
  opening); without it, 0, which removes the stack term;
- with neither, no object is written;
- the humidity limit is an EMS program that sets the object's air exchange
  flow rate (actuator `Zone Ventilation`, `Air Exchange Flow Rate`) to 0 while
  `Site Outdoor Air Relative Humidity` is above the limit, called at
  `BeginTimestepBeforePredictor`.

`epinterface.geometry.get_zone_windows(doc, zone_name)` returns a zone's
windows.

## Scheduled ventilation (UP-9)

UMI zones can have scheduled ventilation, outdoor air at a set number of air
changes (a night flush, for example), on top of their natural or mechanical
ventilation. `VentilationComponent` now holds it, under UMI's names.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `IsScheduledVentilationOn` | `bool` | – | `False` | Whether the zone has scheduled ventilation, whatever `Provider` is. |
| `ScheduledVentilationAch` | `float`, ≥ 0 | 1/h | `0.0` | Air changes per hour. 0: nothing is written. |
| `ScheduledVentilationSchedule` | `YearComponent \| None` | – (multiplier) | `None` | Hourly multiplier (Fraction or AnyNumber type limits). `None`: constant. |
| `ScheduledVentilationSetpoint` | `float \| None`, in [-100, 100] | °C | `None` | Scheduled ventilation stops while the zone air is colder. `None`: no indoor limit. |

The builder writes a `ZoneVentilation:DesignFlowRate` per zone with
`AirChanges/Hour`, ventilation type `Natural` (no fan energy), coefficients
1/0/0/0 (a flow independent of weather), the schedule (or a constant schedule
of 1) and the setpoint as minimum indoor temperature. Unconditioned attic and
basement zones, whose ventilation provider the builder sets to `None`, get no
scheduled ventilation either.

## Mechanical ventilation schedule (UP-9)

SBEM's mechanical outdoor air was constant: `VentilationComponent.Schedule`
opens the windows of natural ventilation only. UMI's `ZoneConditioning`
schedules the mechanical outdoor air (`MechVentSchedule`), so the component
now holds such a schedule.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `VentilationComponent.MechVentSchedule` | `YearComponent \| None`, Fraction type limits | – (fraction) | `None` | Fraction of the design outdoor air (per person plus per floor area) supplied each hour, when `Provider` is `Mechanical` or `Both`. `None`: constant. |

With a schedule, the builder sets the ideal loads' outdoor air method to
`DetailedSpecification` and writes a `DesignSpecification:OutdoorAir`
(`<zone>_<ventilation>_OUTDOOR_AIR`) with method `Sum`, the same flows per
person and per floor area, and the schedule. Without one it writes `Sum` as
before.

## Ideal-loads limits (UP-9)

SBEM always limited the ideal loads' air flow and capacity to autosized
values. `ConditioningSystemsComponent` now holds the limits, per floor area as
UMI's `ZoneConditioning` does.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `HeatingLimitType` | `"NoLimit" \| "LimitFlowRate" \| "LimitCapacity" \| "LimitFlowRateAndCapacity"` | – | `"LimitFlowRateAndCapacity"` | What limits heating (UMI `HeatingLimitType`). |
| `CoolingLimitType` | same | – | `"LimitFlowRateAndCapacity"` | What limits cooling (UMI `CoolingLimitType`). |
| `MaxHeatingFlowPerFloorArea` | `float \| None`, ≥ 0 | m³/(s·m²) | `None` | Maximum heating supply air flow (UMI `MaxHeatFlow`). `None`: autosized. |
| `MaxCoolingFlowPerFloorArea` | `float \| None`, ≥ 0 | m³/(s·m²) | `None` | Maximum cooling supply air flow (UMI `MaxCoolFlow`). `None`: autosized. |
| `MaxHeatingCapacityPerFloorArea` | `float \| None`, ≥ 0 | W/m² | `None` | Maximum sensible heating capacity (UMI `MaxHeatingCapacity`). `None`: autosized. |
| `MaxCoolingCapacityPerFloorArea` | `float \| None`, ≥ 0 | W/m² | `None` | Maximum total cooling capacity (UMI `MaxCoolingCapacity`). `None`: autosized. |

The builder writes each zone's limits to its ideal loads template, the values
per floor area multiplied by the zone's floor area. EnergyPlus uses a flow or
capacity only when the limit type names it. The defaults reproduce the
earlier template.

## Heating and cooling availability (UP-9)

SBEM's heating and cooling were available all year whenever the system
existed. `ConditioningSystemsComponent` now holds availability schedules, UMI's
`ZoneConditioning.HeatingSchedule` and `CoolingSchedule`.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `HeatingAvailabilitySchedule` | `YearComponent \| None`, Fraction type limits | – (0 off, else on) | `None` | When heating is available. `None`: always. |
| `CoolingAvailabilitySchedule` | `YearComponent \| None`, Fraction type limits | – (0 off, else on) | `None` | When cooling is available. `None`: always. |

The builder writes each set schedule as a `Schedule:Year` and uses it as the
ideal loads' heating or cooling availability schedule. Its design days are
"always on" (`d_AllOn_00`), so that sizing sees an available system, unless
the week sets its own design-day slots. A missing system stays `AlwaysOff`,
whatever its schedule.

## Adiabatic assemblies (UP-9)

A UMI template can declare any of its assemblies adiabatic, for example the
facade of a terraced house's party walls. `EnvelopeAssemblyComponent`
(`epinterface.sbem.components.envelope`) now holds UMI's five flags.

| Field | Type | Unit | Default | Surfaces made adiabatic |
|---|---|---|---|---|
| `IsFacadeAdiabatic` | `bool` | – | `False` | Exterior walls (`Outdoors` walls). Their windows are removed. |
| `IsRoofAdiabatic` | `bool` | – | `False` | Exterior roofs. |
| `IsGroundAdiabatic` | `bool` | – | `False` | Floors and walls on the ground. |
| `IsPartitionAdiabatic` | `bool` | – | `False` | Walls between two zones. |
| `IsSlabAdiabatic` | `bool` | – | `False` | Floors and ceilings between two main zones (not those of the attic or basement). |

After the constructions are assigned, `Model.apply_adiabatic_boundaries` sets
each such surface's outside boundary condition to `Adiabatic` (no sun, no
wind), following the assemblies of its zone's definition
(`Model.conditioning_definition`: the group's for a main zone, `Zone` for the
attic and basement). An interzone surface takes its partner with it, so both
sides agree. The construction stays: it still stores heat.

EnergyPlus allows no window on an adiabatic surface, so before the zone
definitions are written `Model.remove_adiabatic_facade_windows` removes the
windows of exterior walls whose zone has an adiabatic facade; such a zone
then has no solar gains through windows and no natural ventilation.

## Internal partitions (UP-9)

A shoebox zone has partitions only where it meets another zone. UMI's
`BuildingTemplate.PartitionRatio` describes the partitions inside the zones,
which store heat. `EnvelopeAssemblyComponent` now holds them.

| Field | Type | Unit | Default | Meaning |
|---|---|---|---|---|
| `PartitionAreaPerFloorArea` | `float`, ≥ 0 | m²/m² | `0.0` | Area of internal partitions exposed to the zone per floor area (both faces count, as for EnergyPlus internal mass). 0: none. |

The builder writes, for each zone, an `InternalMass` named
`<zone>_Partitions` of `PartitionAssembly`, with this ratio times the zone's
floor area. It does so for the same zones as the internal mass: every zone
with the reference envelope, and each group's zones with the group's
envelope. A UMI translator converts its ratio to this area.

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
