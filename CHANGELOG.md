# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-11-13

### Changed

- **Breaking:** [idfkit](https://pypi.org/project/idfkit/) replaces archetypal, eppy and geomeppy. Models are built,
  edited, simulated and read through idfkit's own API. archetypal, eppy and
  geomeppy are no longer dependencies.
- **Breaking:** the model is now `ModelRunResults.doc`, an idfkit
  `IDFDocument`, and `ModelRunResults.sql` is now idfkit's `SQLResult` (it was
  archetypal's `Sql`). `ModelRunResults.idf` still returns the document but
  warns that it is deprecated. Every parameter that takes an `IDFDocument` is
  named `doc`.
- **Breaking:** `Model.build()` returns an `IDFDocument`; `Model.simulate()`
  returns `(IDFDocument, SQLResult)`.
- **Breaking:** `post_geometry_callback` is now
  `Callable[[IDFDocument], IDFDocument]`.
- **Breaking:** every `add_to_idf` and similar method on the sbem
  components, the `epinterface/interface.py` classes, `epinterface/builder.py`,
  `epinterface/climate_studio/` and `epinterface/geometry.py` now takes an
  `IDFDocument` instead of an archetypal `IDF`.
- **Breaking:** `EnergyPlusSettings.archetypal_energyplus_version` is replaced by
  `EnergyPlusSettings.version_tuple`.
- The default EnergyPlus version is the newest installed supported major
  version. Set `EPINTERFACE_ENERGYPLUS_VERSION` to pin one.
- The base model is now built programmatically with idfkit for any supported
  EnergyPlus version (`minimal_document`). The packaged `Minimal.idf`, its
  `DefaultMinimalIDFPath`, and the IDFVersionUpdater transition step are gone,
  so the first build in a process no longer spends about 37 s migrating the
  file, and the EnergyPlus transition binaries are no longer needed.
- Simulation outputs match the archetypal-based 1.x results on EnergyPlus
  25.2.0 within a relative tolerance of 1e-3 and an absolute tolerance of 1e-6;
  per-zone geometry matches within a relative tolerance of 1e-9 and an absolute
  tolerance of 0.01. The committed fixtures in `tests/data/regression` are the
  evidence.
- idfkit is pinned to `>=1.3.0rc1,<1.4`.
- Documents are typed for the EnergyPlus releases epinterface supports, 22.2
  to 25.2, instead of idfkit's latest release (26.2), which epinterface never
  builds. `epinterface.document.EPDocument`, the union of idfkit's
  `IDFDocumentV22_2` to `IDFDocumentV25_2`, annotates every parameter and return
  value that takes a document, so pyright offers only the object types and
  fields that all of those releases have. `as_supported(doc)` types a document
  as one, checking its version at run time, and `load_document(path, version)`
  loads a file as one. A pre-commit hook also runs `idfkit check` on those
  releases, which lints the object types and choice values in string-keyed
  calls such as `doc.add("Lights", ...)`.
- **Breaking:** `minimal_document` raises `TypeError` for an EnergyPlus version
  outside 22.2 to 25.2, before building anything. Such a version used to fail
  later: 22.1 when an infiltration or ventilation object was written (22.1
  names their zone and flow fields differently), other majors when the results
  were read.

### Added

- `ModelRunResults.hourly_timeseries(names)` returns the hourly variables as a
  DataFrame, with the same index and column levels as archetypal's
  `Sql.timeseries_by_name(names, reporting_frequency="Hourly")`.
- Regression tests that compare built models, geometry and simulation results
  with fixtures captured under archetypal.
- The test seed's thermostat setpoints are now 21 degC heating and 24 degC
  cooling `Temperature` schedules (they were constant 0.5 fraction schedules,
  so the regression models never really heated or cooled). The regression
  baseline was recaptured from the archetypal-era code on that seed, and the
  `neighbors_overheating` regression case now uses overheating thresholds the
  conditioned zones cross (heat 23 and 26 degC, cold 22.5 degC).

### Removed

- **Breaking:** `ddy_interface_bayes` (unused).
- **Breaking:** the `epinterface.interface` classes that mirrored one
  EnergyPlus object each: `ScheduleTypeLimits`, `SimulationControl`,
  `RunPeriod`, `Timestep`, `SizingParameters`, `SiteGroundTemperature`,
  `InternalMass`, `Material`, `SimpleGlazingMaterial`, `AirGapMaterial`,
  `NoMassMaterial`, `Construction`, `HVACTemplateThermostat`,
  `HVACTemplateZoneIdealLoadsAirSystem`, `WaterUseEquipment`,
  `ElectricEquipment`, `Lights`, `ZoneVentilationWindAndStackOpenArea`,
  `ZoneInfiltrationDesignFlowRate`, `People`, `ScheduleDayHourly`,
  `ScheduleWeekDaily`, `ScheduleYear`, `ZoneList` and their base `BaseObj`
  (with its `extract()` readers). Write objects with idfkit's `doc.add` and
  idfkit's snake_case field names instead, or with
  `epinterface.document.add_or_replace`, which reuses an identical object of
  the same name and replaces a different one. `watts_per_area` keys a
  `Lights` or `ElectricEquipment` design level by the field name of the
  document's EnergyPlus version, `add_construction` writes a
  layered construction, and `add_site_ground_temperature`, `add_zone_list`
  and `BaseMaterial.add_layer_to_idf` replace
  `SiteGroundTemperature.FromValues`, `ZoneList` and `BaseMaterial.as_layer`.
  The literal types, the default material library and the schedule helpers
  stay in `epinterface.interface`. The written models are unchanged.
- **Breaking:** methods that returned those classes now write and return the
  idfkit object: `ConstructionLayerComponent.ep_material` is replaced by
  `add_to_idf(doc)`, climate_studio's
  `OpaqueConstructionLayer.dereference_to_material` by
  `add_material_to_idf(idf, material_defs)`, and
  `ZoneOperationsComponent.add_thermostat_to_idf_zone` returns the
  `HVACTemplate:Thermostat` object. `AddedZoneLists` holds lists of zone names,
  climate_studio's zone lists are the written `ZoneList` objects, and
  `TypeLimits` entries are `TypeLimitsSpec` dataclasses with the same
  `Lower_Limit_Value` and `Upper_Limit_Value` attributes.

### Fixed

- Shoebox geometry for some storey heights (for example 4.321 m with a
  three-storey core/perimeter layout) is now matched correctly. geomeppy paired
  some walls wrongly at those heights.
- The legacy `epinterface/builder.py` (`SimpleResidentialModel`) now simulates
  end to end. It no longer requests plant sizing.
- climate_studio results use the "District Heating" label on all EnergyPlus
  versions. Before, they failed on EnergyPlus 23 and later.
- `Model.run()` (sbem and climate_studio) no longer leaves the results file
  open in its temporary run directory, which made the directory's deletion
  fail on Windows. Without `eplus_parent_dir`, sbem's `ModelRunResults.sql`
  now reads a copy of the results file in the system temporary directory,
  deleted when the result is closed.

### Notes

- `SizingPeriod:WeatherFileConditionType` objects are now written in a fixed
  order, winter first. archetypal's order came from set iteration and could
  change between processes, which could change results (notably core/perimeter
  models with a basement and attic).

### Migrating from 1.x (GLOBi)

One line changes:

```python
# before
run_result.sql.timeseries_by_name(names, reporting_frequency="Hourly")
# after
run_result.hourly_timeseries(names)
```

Move the pin from `epinterface>=1.4,<1.5` to `epinterface>=2.0,<3`. Code that
passes archetypal or eppy objects to epinterface, or reads them from `Model`
results, must switch to `IDFDocument` and `SQLResult`.
