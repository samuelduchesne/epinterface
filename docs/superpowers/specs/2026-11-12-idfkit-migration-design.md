# Replace archetypal/eppy/geomeppy with idfkit

Date: 2026-11-12
Status: draft, awaiting approval

## Intent

Remove archetypal (and with it eppy and geomeppy) from epinterface entirely.
Every EnergyPlus model epinterface builds, edits, simulates and reads is handled
through idfkit's own API: `IDFDocument`, `doc["Zone"]`, `doc.add(...)`,
`idfkit.geometry` / `idfkit.zoning` / `idfkit.geometry_builders`,
`idfkit.schedules`, `idfkit.simulation.simulate` and its `SQLResult`. The
eppy-compatibility layer idfkit also ships (`addidfobject`, `idfobjects`-style
access, `idfkit.compat`) is **not** used.

The main consumer is GLOBi (`MITSustainableDesignLab/globi`). Its results must
not change.

## Goals

1. archetypal, eppy and geomeppy are gone from `pyproject.toml`, `uv.lock` and
   every import in `epinterface/`, `tests/`, `scripts/`, `notebooks/` and
   `benchmarking/`.
2. idfkit is a direct dependency, used through its native API.
3. The part of the public interface GLOBi uses keeps working with no change
   other than one line (see "GLOBi contract").
4. For the same inputs, `Model.run` gives the same `energy_and_peak` and
   overheating results as today, within a stated tolerance, and the hourly
   frame has the same shape and labels. A new regression test proves this.

## Non-goals

- New modelling features, or changes to the physics, components or database
  schema.
- Fixing existing TODOs in the builders (e.g. occupied area vs conditioned
  area), unless the migration forces it.
- Keeping epinterface's public functions accepting or returning archetypal or
  eppy objects. That part of the interface breaks on purpose (see below).

## Anti-goals (failure even if it "works")

- An eppy-shaped compatibility layer inside epinterface: wrappers that mimic
  `idfobjects`, `newidfobject`, `Sql.timeseries_by_name`, etc.
- GLOBi's numbers silently drifting. Passing tests that never compare
  simulation outputs do not count as proof.
- Keeping archetypal as a hidden or optional dependency "just for" one helper.

## GLOBi contract

What GLOBi uses today (from `src/globi/pipelines.py`, `src/globi/models/tasks.py`,
`src/globi/allocate.py`, `src/globi/gis/utils.py`, `src/globi/models/configs.py`):

| GLOBi uses | Touches archetypal? | After migration |
|---|---|---|
| `Model(...)`, `BasementAssumptions`, `AtticAssumptions`, `construct_zone_def` | no (pydantic inputs) | unchanged |
| `ShoeboxGeometry(...)`, `SceneContext(...)`, `compute_shading_mask` | no (inputs) | unchanged |
| `model.run(eplus_parent_dir=..., overheating_config=...)` | no (arguments) | unchanged |
| `run_result.energy_and_peak`, `run_result.overheating_results.{edh,basic_oh,hi,consecutive_e_zone}` | no (pandas) | unchanged, same values within tolerance |
| `model.total_conditioned_area` | no (calculated from geometry) | unchanged |
| `SemanticModelFields`, `check_model_existence`, `OverheatingAnalysisConfig`, `AvailableHourlyVariables` | no | unchanged |
| `run_result.sql.timeseries_by_name(names, reporting_frequency="Hourly")` (`pipelines.py:210`) | **yes** | replaced by `run_result.hourly_timeseries(names)` |

`ModelRunResults.hourly_timeseries(names: list[str]) -> pd.DataFrame` returns
exactly the frame `Sql.timeseries_by_name(names, reporting_frequency="Hourly")`
returns today: same index (hourly timesteps; GLOBi renames it to "Timestep"),
same three column levels in the same order (unnamed/"Trash", key value/"Group",
variable name/"Meter"), same value labels and units. GLOBi changes that one line
when it moves its pin from `epinterface>=1.4,<1.5` to the new major version.

### What breaks on purpose

These expose archetypal or eppy objects today and switch to idfkit types
(`IDFDocument`, `IDFObject`, `SQLResult`):

- `ModelRunResults.idf` (now `IDFDocument`) and `ModelRunResults.sql` (now
  idfkit's `SQLResult`; kept as an attribute so callers can still reach raw
  results, but with idfkit's API, not archetypal's).
- `Model.build()` returns `IDFDocument`; `Model.simulate()` returns
  `(IDFDocument, SQLResult)`.
- `post_geometry_callback: Callable[[IDFDocument], IDFDocument]`.
- Every `add_to_idf(idf)` / similar method on sbem components, the
  `epinterface/interface.py` classes, `epinterface/builder.py`,
  `climate_studio/`, and `geometry.py` now takes an `IDFDocument`.
- `EnergyPlusSettings.archetypal_energyplus_version` is removed (see Settings).

Version bump: major (`1.5.0` → `2.0.0`), with a changelog entry listing the
items above and the GLOBi one-line change.

## Approaches considered

1. **Freeze reference outputs, then switch everything on one branch (chosen).**
   Before touching anything, extend `tests/test_components/test_builder.py`
   into a regression test and save its outputs under archetypal. Then switch the
   model type to idfkit everywhere, in dependency order, on one branch. Done
   when the regression test matches within tolerance and archetypal is gone.
   Cheap, and the final result is verified. Downside: the suite is red partway
   through, and the regression test shows *that* numbers drifted, not *where*.
2. **Module by module with a temporary bridge.** Convert between archetypal and
   idfkit models by round-tripping IDF text at each boundary so tests stay green
   after every step. Rejected: lots of throwaway bridge code, slow, and can hide
   differences that only appear once the whole model is built natively.
3. **New idfkit builder next to the old one.** Run both in the same test and
   compare object by object, then delete the old one. Best diagnostics, but
   duplicates about 4,000 lines for a while and every interim fix is made
   twice. Rejected; its object-by-object comparison stays available as a one-off
   debugging step if the regression test drifts (dump both models to IDF text
   and diff object counts and key fields).

The existing tests alone were considered insufficient: only `test_builder.py`
runs EnergyPlus end to end, and it asserts nothing about outputs.

## Regression test (written first, before any migration code)

Turn `tests/test_components/test_builder.py` into a parametrized regression
test over about three configurations of `Model` using the preseeded test DB
(`preseeded_readonly_db`, `default_zone`) and `DefaultEPWZipPath`:

- two-storey, `by_storey` zoning, no basement or attic (today's case);
- core/perimeter zoning with a conditioned basement and an attic with
  `roof_height` set;
- one with neighbour shading via `SceneContext` and an `OverheatingAnalysisConfig`.

For each, save from the archetypal run:

- `energy_and_peak` (full Series, index and values);
- each overheating frame (index and values), where enabled;
- the hourly frame from `sql.timeseries_by_name(AVAILABLE_HOURLY_VARIABLES subset, "Hourly")`:
  index length, column `MultiIndex` levels and labels, and the values.

Store as small parquet/CSV fixtures under `tests/data/regression/`, plus a
script (`scripts/capture_regression_baseline.py`) that regenerates them, so
the capture is reproducible and reviewable.

After the migration, the test compares against the fixtures: labels and shapes
exactly; values with `rtol=1e-3` and a small `atol` for near-zero entries
(builder's call on exact atol). If a configuration cannot meet tolerance, the
difference must be explained (e.g. a known geomeppy vs idfkit surface-ordering
difference that does not change physics) and approved before loosening it.

EnergyPlus version: baselines are captured with one EnergyPlus version (the
newest one in the CI matrix that archetypal 2.18.10 supports, currently 25.2.0)
and the regression test is skipped on other versions. *Builder's call, see
below.*

## Order of work

1. Regression test and fixtures, captured on `main`'s code (archetypal).
2. Add `idfkit` to dependencies (pin `>=1.2,<2`).
3. **Settings** (`settings.py`): replace `EnergyPlusVersion` with idfkit's
   version registry (`idfkit.versions`, `find_closest_version`,
   `version_string`) and EnergyPlus discovery (`idfkit.simulation`'s
   `EnergyPlusConfig` / `find_energyplus`). Keep the `EPINTERFACE_ENERGYPLUS_VERSION`
   env var and its normalisation. Default: the installed EnergyPlus version.
   Replace `archetypal_energyplus_version` with a property returning a
   `(major, minor, patch)` tuple, used by `DESIRED_METERS_FOR_VERSION` etc.
4. **Schedules**: replace `archetypal.schedule.Schedule` and `ScheduleTypeLimits`
   (`from_values`, `constant_schedule`, `to_year_week_day`, `add_year_to_idf`,
   `bounds`, `.Values`, `from_epbunch`). Use `idfkit.schedules`
   (`create_schedule_type_limits`, `create_constant_schedule`,
   `create_compact_schedule_from_values`, `values`/`evaluate`) where they fit.
   Where epinterface needs Schedule:Year/Week/Day objects (to keep today's
   object structure and names), write a small epinterface-owned helper that
   emits them with `doc.add(...)`. That is epinterface's own logic, not an
   eppy shim. Builder's call which output form to use, as long as the
   regression test passes.
5. **Component writers**: `sbem/components/*`, `epinterface/interface.py`,
   `epinterface/builder.py`, `climate_studio/interface.py`: rewrite
   `newidfobject`, `idfobjects[...]`, `getobject`, `removeidfobject`,
   `copyidfobject` to `doc.add`, `doc["Type"]`, `doc["Type"][name]`,
   `doc.removeidfobject` (native), `doc.copy`, etc. Field access moves to
   idfkit's field names (snake_case per epJSON schema) as idfkit recommends.
6. **Geometry** (`geometry.py`): replace geomeppy `add_block` with
   `idfkit.zoning.create_block` (or lower-level builders where `ShoeboxGeometry`'s
   basement, attic/gable and core/perimeter rules need them); `intersect_match`
   → `idfkit.surface_matching.intersect_and_match`; `set_wwr`,
   `add_shading_block`, `set_default_constructions`, `bounding_box`,
   `scale_building`, `rotate_building`, `translate_building` → idfkit
   equivalents; `Polygon3D`/`Vector2D` from geomeppy → `idfkit.geometry`
   (`Polygon3D`, `Vector3D`) or plain tuples/shapely. Surface names will
   change: every place that matches on geomeppy-generated names (e.g.
   `builder.py:177`, "Project Wall") must match on idfkit's names or, better,
   on surface type/boundary condition. `tests/test_geometry.py` and
   `tests/test_neighbor_shading_geometry.py` are the guard here.
7. **Build, simulate, results** (`sbem/builder.py`, `climate_studio/builder.py`,
   `ddy_injector_bayes.py`, `analysis/energy_and_peak.py`,
   `analysis/overheating.py`):
   - Load the base IDF and DDY with `load_idf` (migrating with
     `idfkit.migrate` if the file version differs from the target version).
   - Output:Meter / Output:Variable objects are added with `doc.add`;
     today's `prep_outputs` behaviour (only desired meters/variables, plus SQL
     output) is reproduced explicitly.
   - `idf.simulate()` → `idfkit.simulation.simulate(doc, weather, output_dir=...)`;
     the `SimulationResult` gives the SQL and `.err` paths (replaces
     `idf.sql_file`, `idf.simulation_files`).
   - `Sql.timeseries_by_name` / `tabular_data_by_name` → `SQLResult.get_timeseries`
     / `get_tabular_data`. One private helper in `epinterface/analysis/` builds
     the `(key, name)`-indexed hourly/monthly frames in the same shape
     archetypal produced; `energy_and_peak`, overheating and
     `ModelRunResults.hourly_timeseries` all use it.
   - `ModelRunResults` gains `hourly_timeseries(names)`.
8. **Legacy and cleanup**: migrate `climate_studio/` (reachable via
   `actions.py` and the CLI) and `ddy_injector_bayes.py`. Delete
   `ddy_interface_bayes.py` (nothing imports it). Update tests, `scripts/`,
   `notebooks/`, `benchmarking/`, `README.md`, `docs/`, and the
   `pyproject.toml` description (which currently names Archetypal and Eppy).
9. Remove archetypal from `pyproject.toml`, re-lock, confirm
   `grep -rn "archetypal\|eppy\|geomeppy"` finds nothing in code (comments
   referring to history in the changelog are fine).
10. Full suite plus the regression test green; pyright (standard mode) clean.

### Other consumers: sbem-ui

sbem-ui (`MITSustainableDesignLab/globi-toolkit`, `apps/sbem-ui`) follows the
epinterface version GLOBi pins and shares the component database. It uses only
the pydantic component models, the composer (`construct_graph`,
`construct_composer_model`, `ComponentNameConstructor`), `ComponentLibrary`,
`PrismaSettings`, the schedule component models (`DayComponent`,
`WeekComponent`, `YearComponent`) and `SemanticModelFields`. It never calls
`add_to_idf`, `Model.build`/`run`/`simulate` or anything returning an archetypal
object, so it needs no change beyond moving to 2.0 alongside GLOBi.

## Constraints

- Python `>=3.10,<3.13` (idfkit supports `>=3.10`).
- CI runs EnergyPlus 22.2.0, 24.2.0 and 25.2.0 (`.github/workflows/main.yml`);
  the migrated code must still run on all three. idfkit's schema registry
  covers these versions.
- `pandas>=2.2,<2.3` stays; idfkit's pandas extra is satisfied by it.
- The component database (`prisma`) and its schema are shared with sbem-ui
  (per GLOBi's pin comment) and must not change.

## Calls made in this document (please check)

- Major version bump to 2.0.0.
- `ModelRunResults.sql` kept as an attribute but now idfkit's `SQLResult`,
  rather than removed.
- Regression tolerance `rtol=1e-3`; baselines captured against a single
  EnergyPlus version, test skipped on others.
- `ddy_interface_bayes.py` deleted; `climate_studio/` migrated, not deleted.
- Year/Week/Day schedule objects may be emitted by an epinterface-owned
  helper if idfkit's compact-schedule builder doesn't reproduce today's results.
- Field access uses idfkit's native field names, not eppy's capitalised names.

## Left to the builder

- Exact mapping of each geomeppy/archetypal call to its idfkit equivalent, and
  any small helpers needed (kept inside epinterface, idfkit-native).
- How `ShoeboxGeometry` composes idfkit's zoning/builders to reproduce
  basement, attic and core/perimeter layouts.
- Regression fixture format and `atol`.
- Whether to use idfkit's simulation cache.
