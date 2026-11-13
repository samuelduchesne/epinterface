# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-11-13

### Changed

- **Breaking:** [idfkit](https://pypi.org/project/idfkit/) replaces archetypal, eppy and geomeppy. Models are built,
  edited, simulated and read through idfkit's own API. archetypal, eppy and
  geomeppy are no longer dependencies.
- **Breaking:** `ModelRunResults.idf` is now an idfkit `IDFDocument`, and
  `ModelRunResults.sql` is now idfkit's `SQLResult` (it was archetypal's `Sql`).
- **Breaking:** `Model.build()` returns an `IDFDocument`; `Model.simulate()`
  returns `(IDFDocument, SQLResult)`.
- **Breaking:** `post_geometry_callback` is now
  `Callable[[IDFDocument], IDFDocument]`.
- **Breaking:** every `add_to_idf(idf)` and similar method on the sbem
  components, the `epinterface/interface.py` classes, `epinterface/builder.py`,
  `epinterface/climate_studio/` and `epinterface/geometry.py` now takes an
  `IDFDocument` instead of an archetypal `IDF`.
- **Breaking:** `EnergyPlusSettings.archetypal_energyplus_version` is replaced by
  `EnergyPlusSettings.version_tuple`.
- The default EnergyPlus version is the newest installed supported major
  version. Set `EPINTERFACE_ENERGYPLUS_VERSION` to pin one.
- Simulation outputs match the archetypal-based 1.x results within a stated
  tolerance; the committed fixtures in `tests/data/regression` are the evidence.

### Added

- `ModelRunResults.hourly_timeseries(names)` returns the hourly variables as a
  DataFrame, with the same index and column levels as archetypal's
  `Sql.timeseries_by_name(names, reporting_frequency="Hourly")`.
- Regression tests that compare built models, geometry and simulation results
  with fixtures captured under archetypal.

### Removed

- **Breaking:** `ddy_interface_bayes` (unused).
- archetypal, eppy and geomeppy objects in the public interface (see Changed).

### Fixed

- Shoebox geometry for some storey heights (for example 4.321 m with a
  three-storey core/perimeter layout) is now matched correctly. geomeppy paired
  some walls wrongly at those heights.
- The legacy `epinterface/builder.py` (`SimpleResidentialModel`) now simulates
  end to end. It no longer requests plant sizing.
- climate_studio results use the "District Heating" label on all EnergyPlus
  versions. Before, they failed on EnergyPlus 23 and later.

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
