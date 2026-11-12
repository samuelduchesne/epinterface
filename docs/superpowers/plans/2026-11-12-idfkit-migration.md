# Replace archetypal/eppy/geomeppy with idfkit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove archetypal, eppy and geomeppy from epinterface and build, simulate and read every model through idfkit's native API, without changing GLOBi's results.

**Architecture:** First freeze today's outputs in a regression test (archetypal still installed). Then move the pieces that don't share the model object (settings, results reading) while the suite stays green. Then switch the model type to `idfkit.IDFDocument` everywhere in dependency order (legacy `interface.py` → sbem components → geometry → builders); the end-to-end suite is red from Task 5 until Task 8 turns the regression test green again. Finally migrate the legacy `climate_studio` path and remove archetypal.

**Tech Stack:** Python 3.10–3.12, idfkit `>=1.2,<2`, pandas 2.2, pydantic 2, pytest, uv, EnergyPlus 22.2/24.2/25.2 (CI).

**Spec:** `docs/superpowers/specs/2026-11-12-idfkit-migration-design.md`

## Global Constraints

- No archetypal, eppy or geomeppy import anywhere once Task 10 lands; none in any new file at any time.
- Use idfkit's native API (`load_idf`, `doc["Type"]`, `doc.add(...)`, `doc.rename(...)`, `idfkit.geometry`, `idfkit.zoning`, `idfkit.geometry_builders`, `idfkit.surface_matching`, `idfkit.schedules`, `idfkit.simulation`). Never `idfkit.compat` or eppy-style names (`newidfobject`, `idfobjects`, `getobject`, `copyidfobject`). Field access uses idfkit's snake_case field names.
- No eppy-shaped wrappers inside epinterface (nothing that mimics `idfobjects`, `newidfobject`, `Sql.timeseries_by_name`).
- GLOBi-facing interface unchanged except `run_result.sql.timeseries_by_name(names, reporting_frequency="Hourly")` → `run_result.hourly_timeseries(names)`, returning the identical frame.
- Zone names, and their order in the document, stay exactly as geomeppy produces them today.
- Regression tolerances: labels/shapes exact; geometry summary `rtol=1e-9`, `atol=0.01` (plan's call: EnergyPlus prints these with two decimals, so a last-digit rounding flip must not fail); energy, peak, overheating and hourly values `rtol=1e-3`, `atol=1e-6`. No loosening without the user's sign-off in PR review.
- Regression fixtures are captured with EnergyPlus 25.2.0; the regression test is skipped on any other version.
- Component database (prisma schema) unchanged.
- Release as 2.0.0 with a changelog entry listing the breaking changes from the spec's "What breaks on purpose".
- Commands run with `EPINTERFACE_ENERGYPLUS_VERSION=25.2.0` unless a step says otherwise.

## Review Focus

1. **Older EnergyPlus versions in CI (22.2, 24.2).** Users on those versions expect `Model.run` to work and `energy_and_peak` to have the same index labels as on 25.2 (meters differ by major version). → Task 8, `test_run_smoke_any_version`.
2. **Base file version.** `Minimal.idf` is version 22.2; with a newer target the document must be migrated, with 22.2 it must load untouched. → Task 4, `test_load_base_document_*`.
3. **Neighbours with height 0.** GLOBi passes `0` for unknown neighbour heights; a build must succeed and add no shading surface for that neighbour. → Task 7, `test_neighbor_with_zero_height_adds_no_shading`.
4. **Hourly variable not in the output.** archetypal returned an empty frame, not an error; GLOBi may ask for any `AvailableHourlyVariables`. → Task 3, `test_timeseries_frame_unknown_name_is_empty`.
5. **By-storey zoning with a basement.** Not in the three simulated configurations, but GLOBi uses it; zone names (suffix "Storey -1") must match. → Task 1 captures, Task 7 `test_zone_names_match_baseline`.

---

## File map

| File | Responsibility | Task |
|---|---|---|
| `tests/regression/configs.py` (new) | The three regression `Model` configurations + geometry-only grid | 1 |
| `tests/regression/summary.py` (new) | Library-agnostic readers: zone geometry summary from the SQL file (stdlib `sqlite3`) | 1 |
| `scripts/capture_regression_baseline.py` (new) | Regenerates `tests/data/regression/` | 1 |
| `tests/test_regression.py` (new) | Compares runs against fixtures | 1, 8 |
| `epinterface/settings.py` | EnergyPlus version via idfkit | 2 |
| `epinterface/results.py` (new) | `timeseries_frame`, `tabular_frame` over `SQLResult` | 3 |
| `epinterface/document.py` (new) | `load_base_document` | 4 |
| `epinterface/schedules.py` (new) | `add_values_schedule` (Year/Week/Day from 8760 values) | 4 |
| `epinterface/interface.py`, `epinterface/builder.py` | Legacy object writers on `IDFDocument` | 5 |
| `epinterface/sbem/components/*.py` | Component writers on `IDFDocument` | 6 |
| `epinterface/geometry.py` | Shoebox, attic, basement, shading, WWR on idfkit | 7 |
| `epinterface/sbem/builder.py`, `epinterface/sbem/flat_model.py`, `epinterface/ddy_injector_bayes.py` | Build, simulate, results | 8 |
| `epinterface/climate_studio/*`, `epinterface/actions.py`, `scripts/`, `notebooks/`, `benchmarking/` | Legacy path | 9 |
| `pyproject.toml`, `uv.lock`, `CHANGELOG.md` (new), `README.md`, `docs/` | Dependency removal, release notes | 10 |

---

### Task 1: Regression baseline (archetypal still in place)

**Files:**
- Create: `tests/regression/__init__.py`, `tests/regression/configs.py`, `tests/regression/summary.py`, `scripts/capture_regression_baseline.py`, `tests/test_regression.py`, `tests/data/regression/**`
- Modify: `epinterface/sbem/builder.py` (`ModelRunResults`, ~line 1292)

**Interfaces:**
- Produces:
  - `ModelRunResults.hourly_timeseries(self, names: Sequence[str]) -> pd.DataFrame` (here: `return self.sql.timeseries_by_name(list(names), reporting_frequency="Hourly")`; reimplemented in Task 3).
  - `tests.regression.configs.REGRESSION_CONFIGS: dict[str, Callable[[Prisma], tuple[Model, OverheatingAnalysisConfig | None]]]` with keys `"by_storey_plain"`, `"core_perim_basement_attic"`, `"neighbors_overheating"`.
  - `tests.regression.configs.GEOMETRY_GRID: dict[str, ShoeboxGeometry]` — every combination of `zoning in {"by_storey","core/perim"}`, `basement in {False, True}`, `roof_height in {None, 2.5}`, `num_stories in {1, 3}`, plus `"by_storey_neighbors"`: `by_storey`, 2 storeys, with a `SceneContext` (2 neighbours, heights `[10.0, 0.0]`). Other keys are `f"{zoning}-{basement}-{roof_height}-{num_stories}"`.
  - `tests.regression.summary.zone_geometry_summary(sql_path: Path) -> pd.DataFrame` — index zone name; columns `area`, `volume`, `gross_wall_area`, `window_glass_area` read from `TabularDataWithStrings` where `ReportName='InputVerificationandResultsSummary'` and `TableName='Zone Summary'`, excluding the `Total`/`Conditioned Total`/`Unconditioned Total`/`Not Part of Total` rows.
  - `tests.regression.summary.zone_names(doc_text: str) -> list[str]` — Zone object names in file order, parsed with a regex over IDF text (no library).
  - Fixtures, per config `<key>`: `tests/data/regression/<key>/energy_and_peak.parquet`, `hourly.parquet`, `geometry.parquet`, `built.idf`, and when overheating is on `edh.parquet`, `basic_oh.parquet`, `hi.parquet`, `consecutive_e_zone.parquet`; plus `tests/data/regression/geometry_baseline.json` (`{"zone_names": {grid_key: [zone names]}, "shading_counts": {grid_key: int}}`, the latter = number of `Shading:Building:Detailed` objects).

Configurations (all use `preseeded_readonly_db`, zone `"default_zone"`, `Weather=DefaultEPWZipPath`, `x=0, y=0, w=10, d=10, h=3, wwr=0.2`):

| key | geometry | Basement | Attic | overheating |
|---|---|---|---|---|
| `by_storey_plain` | `num_stories=2, zoning="by_storey", basement=False, roof_height=None` | `Conditioned=False, UseFraction=None` | `Conditioned=False, UseFraction=None` | `None` |
| `core_perim_basement_attic` | `w=20, d=15, num_stories=2, zoning="core/perim", basement=True, roof_height=2.5` | `Conditioned=True, UseFraction=None` | `Conditioned=False, UseFraction=None` | `None` |
| `neighbors_overheating` | `num_stories=3, zoning="by_storey"`, `scene_context=SceneContext(building=box(0,0,10,10), neighbors=[box(15,0,25,10), box(0,15,10,25)], neighbor_heights=[12.0, 0.0], orientation=0)` | as row 1 | as row 1 | `OverheatingAnalysisConfig()` |

If a model validator rejects a row, change only the conflicting assumption and record it in the config's docstring.

- [ ] **Step 1: Install EnergyPlus 25.2.0 locally** (skip if `/usr/local/EnergyPlus-25-2-0/energyplus` exists)

```bash
cd /tmp && curl -sSLO https://github.com/NREL/EnergyPlus/releases/download/v25.2.0/EnergyPlus-25.2.0-cf7368216c-Linux-Ubuntu22.04-x86_64.tar.gz && tar xzf EnergyPlus-25.2.0-cf7368216c-Linux-Ubuntu22.04-x86_64.tar.gz && sudo mv EnergyPlus-25.2.0-cf7368216c-Linux-Ubuntu22.04-x86_64 /usr/local/EnergyPlus-25-2-0
```

Expected: `/usr/local/EnergyPlus-25-2-0/energyplus --version` prints `EnergyPlus, Version 25.2.0`.

- [ ] **Step 2: Write `tests/test_regression.py` (fails: no fixtures yet)**

```python
pytestmark = pytest.mark.skipif(
    energyplus_settings.energyplus_version != "25.2.0",
    reason="Regression fixtures are captured with EnergyPlus 25.2.0",
)

@pytest.mark.parametrize("key", list(REGRESSION_CONFIGS))
def test_regression(key, preseeded_readonly_db, tmp_path):
    model, oh = REGRESSION_CONFIGS[key](preseeded_readonly_db)
    r = model.run(eplus_parent_dir=tmp_path, overheating_config=oh)
    base = FIXTURES / key
    assert_series_equal(r.energy_and_peak, pd.read_parquet(base / "energy_and_peak.parquet").iloc[:, 0], rtol=1e-3, atol=1e-6, check_names=False)
    hourly = r.hourly_timeseries(HOURLY_NAMES)
    assert_frame_equal(hourly, pd.read_parquet(base / "hourly.parquet"), rtol=1e-3, atol=1e-6, check_freq=False)
    sql_path = next((tmp_path / "eplus_simulation").rglob("*.sql"))
    assert_frame_equal(zone_geometry_summary(sql_path), pd.read_parquet(base / "geometry.parquet"), rtol=1e-9, atol=0.01)
    if oh is not None:
        for name in ("edh", "basic_oh", "hi", "consecutive_e_zone"):
            assert_frame_equal(getattr(r.overheating_results, name), pd.read_parquet(base / f"{name}.parquet"), rtol=1e-3, atol=1e-6)
```

`HOURLY_NAMES = ["Zone Mean Air Temperature", "Zone Air Relative Humidity"]` (both must be in `AVAILABLE_HOURLY_VARIABLES`; pick two that are if these aren't). Column labels, index labels and dtypes are compared exactly by the `assert_*_equal` defaults.

- [ ] **Step 3: Run it to confirm it fails**

Run: `EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run pytest tests/test_regression.py -v`
Expected: FAIL (`AttributeError: ... hourly_timeseries` or missing fixture file).

- [ ] **Step 4: Add `ModelRunResults.hourly_timeseries`, `configs.py`, `summary.py`, and `scripts/capture_regression_baseline.py`**

The script builds each config with the same DB the test fixture builds (reuse the fixture's seeding functions from `tests/conftest.py`; move them into `tests/regression/configs.py` if they aren't importable), runs it, and writes every fixture listed above. `built.idf` is the IDF EnergyPlus ran (copied from the run directory). `geometry_baseline.json` comes from building (not simulating) each `GEOMETRY_GRID` entry with `ShoeboxGeometry.add` on the `Minimal.idf` model and reading zone names in order and counting shading objects. After writing each parquet file the script reads it back and `assert_frame_equal`s it against the in-memory frame, so a lossy round trip (e.g. `None` keys in the `KeyValue` level for meters) fails at capture time, not in the test.

- [ ] **Step 5: Capture fixtures and run the test**

Run: `EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run python scripts/capture_regression_baseline.py && EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run pytest tests/test_regression.py -v`
Expected: 3 passed. Fixture directory total under ~10 MB (if larger, drop to `HOURLY_NAMES[:1]`).

- [ ] **Step 6: Commit**

```bash
git add tests/regression tests/test_regression.py tests/data/regression scripts/capture_regression_baseline.py epinterface/sbem/builder.py
git commit -m "test: capture archetypal regression baseline for idfkit migration"
```

---

### Task 2: idfkit dependency and EnergyPlus settings

**Files:**
- Modify: `pyproject.toml` (add `"idfkit>=1.2,<2"`), `uv.lock`, `epinterface/settings.py`, `epinterface/interface.py:641`, `epinterface/sbem/builder.py:844-893`
- Test: `tests/test_settings.py` (new)

**Interfaces:**
- Produces:
  - `EnergyPlusSettings.energyplus_version: str | None` (unchanged field, env `EPINTERFACE_ENERGYPLUS_VERSION`, same normalisation).
  - `EnergyPlusSettings.version_tuple -> tuple[int, int, int]` (property) — raises `EnergyPlusVersionNotSetError(ValueError)` (new, in `settings.py`) when the version is `None`.
  - Default factory: version of `idfkit.simulation.find_energyplus()` as `"X.Y.Z"`, or `None` on `idfkit.EnergyPlusNotFoundError`.
  - `archetypal_energyplus_version` is deleted; callers use `version_tuple[0]` for major and `idfkit.version_string(version_tuple)` for the dotted string.

- [ ] **Step 1: Write failing tests**

```python
def test_version_tuple_from_env(monkeypatch):
    monkeypatch.setenv("EPINTERFACE_ENERGYPLUS_VERSION", "24-2")
    assert EnergyPlusSettings().version_tuple == (24, 2, 0)

def test_version_tuple_unset_raises():
    with pytest.raises(EnergyPlusVersionNotSetError):
        EnergyPlusSettings(energyplus_version=None).version_tuple

def test_default_uses_installed_energyplus(monkeypatch):
    monkeypatch.delenv("EPINTERFACE_ENERGYPLUS_VERSION", raising=False)
    assert EnergyPlusSettings().energyplus_version is not None
```

- [ ] **Step 2: Run** `uv run pytest tests/test_settings.py -v` — Expected: FAIL (`ImportError: EnergyPlusVersionNotSetError`).
- [ ] **Step 3: Implement** per Interfaces; update the two callers.
- [ ] **Step 4: Run** `uv add "idfkit>=1.2,<2" && EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run pytest -v` — Expected: all pass, including `tests/test_regression.py`.
- [ ] **Step 5: Commit** — `git commit -am "feat: resolve EnergyPlus version through idfkit"` (add `tests/test_settings.py`).

---

### Task 3: Results reading on idfkit's `SQLResult`

**Files:**
- Create: `epinterface/results.py`, `tests/test_results.py`
- Modify: `epinterface/analysis/energy_and_peak.py` (`sql: Sql` → `sql: SQLResult`, lines ~102-104), `epinterface/analysis/overheating.py` (~1125), `epinterface/sbem/builder.py` (`simulate` builds `SQLResult(idf.sql_file)`; `ModelRunResults.sql: SQLResult`; `hourly_timeseries`)

**Interfaces:**
- Produces:
  - `timeseries_frame(sql: SQLResult, names: str | Sequence[str], frequency: str = "Hourly", environment_type: int = 3) -> pd.DataFrame` — same frame as archetypal's `Sql.timeseries_by_name`: column `MultiIndex` levels `["IndexGroup", "KeyValue", "Name"]`; index a `DatetimeIndex` built from `Month, Day, Hour, Minute` with year 2018, minus `Interval` minutes; warmup rows (`IFNULL(WarmupFlag,0)=1`) excluded; only `EnvironmentPeriods.EnvironmentType = environment_type`; empty `DataFrame` if no names match. Implemented with `sql.query(...)` (one query for the dictionary rows, one for the data) and a pandas pivot.
  - `tabular_frame(sql: SQLResult, report_name: str, table_name: str, report_for: str | None = None) -> pd.DataFrame` — `TabularDataWithStrings` pivoted to index `RowName`, columns `["ColumnName", "Units"]`, values coerced numeric where possible (long form if the pivot is not unique).
  - `ModelRunResults.hourly_timeseries(names)` → `timeseries_frame(self.sql, names, "Hourly")`.

- [ ] **Step 1: Write failing tests** using a fixture that creates a tiny SQLite file with tables `ReportDataDictionary`, `ReportData`, `Time`, `EnvironmentPeriods`, `TabularDataWithStrings` (only the columns the queries use): two zones × one variable × 3 hourly rows in a weather run period (type 3), one warmup row, one design-day row (type 1).

```python
def test_timeseries_frame_shape(tiny_sql):
    df = timeseries_frame(tiny_sql, ["Zone Mean Air Temperature"])
    assert list(df.columns.names) == ["IndexGroup", "KeyValue", "Name"]
    assert sorted(df.columns.get_level_values("KeyValue")) == ["ZONE A", "ZONE B"]
    assert len(df) == 3 and df.index[0] == pd.Timestamp("2018-01-01 00:00")

def test_timeseries_frame_excludes_warmup_and_design_days(tiny_sql): ...  # values equal the three run-period values only

def test_timeseries_frame_unknown_name_is_empty(tiny_sql):
    assert timeseries_frame(tiny_sql, ["Not A Variable"]).empty

def test_tabular_frame_pivot(tiny_sql):
    df = tabular_frame(tiny_sql, "AnnualBuildingUtilityPerformanceSummary", "End Uses")
    assert df.columns.names == ["ColumnName", "Units"] and df.loc["Heating", ("Electricity", "GJ")] == 1.5
```

- [ ] **Step 2: Run** `uv run pytest tests/test_results.py -v` — Expected: FAIL (`ModuleNotFoundError: epinterface.results`).
- [ ] **Step 3: Implement** `results.py`; switch both analysis modules and the builder to it.
- [ ] **Step 4: Run** `EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run pytest -v` — Expected: all pass, `tests/test_regression.py` included.
- [ ] **Step 5: Commit** — `git commit -m "feat: read simulation results through idfkit SQLResult"`.

---

### Task 4: Document loading and value schedules

**Files:**
- Create: `epinterface/document.py`, `epinterface/schedules.py`, `tests/test_document.py`, `tests/test_schedules.py`
- Modify: `tests/conftest.py` (add `doc` fixture; keep `idf` until Task 8)

**Interfaces:**
- Produces:
  - `load_base_document(path: Path, version: tuple[int, int, int]) -> IDFDocument` — `idfkit.load_idf`; if the file's version is older than `version`, `idfkit.migrate` it to `version` (raise `idfkit.MigrationError` through); never downgrade (raise `ValueError`).
  - `add_values_schedule(doc: IDFDocument, name: str, values: Sequence[float], type_limits: str) -> IDFObject` — writes one `Schedule:Year` named `name`, the de-duplicated `Schedule:Week:Daily` and `Schedule:Day:Hourly` objects it needs, for exactly 8760 hourly values (raise `ValueError` otherwise). Object names and structure follow archetypal's `to_year_week_day` as seen in `tests/data/regression/*/built.idf`. Returns the `Schedule:Year`.
  - Constant schedules use `idfkit.create_constant_schedule`; type limits use `idfkit.create_schedule_type_limits`.
  - Fixture `doc` → `load_base_document(EnergyPlusArtifactDir / "Minimal.idf", energyplus_settings.version_tuple)`.

- [ ] **Step 1: Write failing tests**

```python
def test_load_base_document_same_version():
    doc = load_base_document(MINIMAL, (22, 2, 0)); assert doc.version == (22, 2, 0)

def test_load_base_document_migrates_to_newer():
    doc = load_base_document(MINIMAL, energyplus_settings.version_tuple); assert doc.version == energyplus_settings.version_tuple

def test_add_values_schedule_round_trips(doc):
    vals = np.tile(np.r_[np.zeros(8), np.ones(10), np.zeros(6)], 365)
    add_values_schedule(doc, "occ", vals, type_limits="Fraction")
    assert np.allclose(idfkit.schedules.values(doc["Schedule:Year"]["occ"], year=2018, document=doc), vals)
    assert len(doc["Schedule:Day:Hourly"]) == 1

def test_add_values_schedule_rejects_wrong_length(doc):
    with pytest.raises(ValueError): add_values_schedule(doc, "x", [1.0] * 24, "Fraction")
```

(Match `idfkit.schedules.values`' actual parameters; the assertion is what matters.)

- [ ] **Step 2: Run** `uv run pytest tests/test_document.py tests/test_schedules.py -v` — Expected: FAIL (import errors).
- [ ] **Step 3: Implement** both modules and the fixture.
- [ ] **Step 4: Run** the same command — Expected: PASS. Full suite still green.
- [ ] **Step 5: Commit** — `git commit -m "feat: idfkit document loading and value schedules"`.

---

### Task 5: Legacy object writers (`interface.py`, `builder.py`) on `IDFDocument`

From here until Task 8 the end-to-end tests (`test_builder.py`, `test_regression.py`, `test_actions.py`) are expected to fail; every other test must pass at each commit.

**Files:**
- Modify: `epinterface/interface.py`, `epinterface/builder.py`
- Test: `tests/test_interface.py` (new)

**Interfaces:**
- Consumes: `add_values_schedule`, `create_constant_schedule`, `create_schedule_type_limits` (Task 4); `EnergyPlusSettings.version_tuple` (Task 2).
- Produces: every method that took `idf: IDF` now takes `doc: IDFDocument` and returns `IDFDocument` where it returned `IDF`. Names of the objects written are unchanged. `epinterface/builder.py:177` stops matching "Project Wall" and selects by surface type/boundary condition.

- [ ] **Step 1: Write failing tests** — for each writer class used by `sbem/components` (grep `from epinterface.interface import` there), one test that calls it on `doc` and asserts the object type, name and the two or three fields it sets, e.g.:

```python
def test_zone_list_writes_object(doc):
    ZoneList(Names=["A", "B"], Name="L").add(doc)
    assert [z.zone_name for z in doc["ZoneList"]["L"].zones] == ["A", "B"]
```

(Use the real class and field names from `interface.py`; extensible fields via idfkit's wrapper attribute.)

- [ ] **Step 2: Run** `uv run pytest tests/test_interface.py -v` — Expected: FAIL.
- [ ] **Step 3: Port both modules** (no `archetypal` import left in either).
- [ ] **Step 4: Run** `uv run pytest tests/test_interface.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "refactor: port legacy object writers to idfkit"`.

---

### Task 6: sbem components on `IDFDocument`

**Files:**
- Modify: `epinterface/sbem/components/{schedules,space_use,operations,envelope,systems,zones}.py`
- Test: `tests/test_components/test_{envelope_comps,operations,space_use_comps}.py` (switch `idf` → `doc`)

**Interfaces:**
- Consumes: Task 4 helpers, Task 5 writers.
- Produces: `add_to_idf(self, doc: IDFDocument, ...) -> IDFDocument` (and `add_day_to_idf` / `add_week_to_idf` / `add_year_to_idf` in `schedules.py`) — same names, same object names written. `Schedule.bounds` uses (`operations.py:178, 215`) come from the component's own `Values` (already on the pydantic model, `schedules.py:84`).

- [ ] **Step 1: Switch the three component test files to the `doc` fixture** and rewrite their assertions to idfkit access (`doc["People"][name].number_of_people_calculation_method`, etc.), keeping every asserted value.
- [ ] **Step 2: Run** `uv run pytest tests/test_components -v -k "not test_builder"` — Expected: FAIL (components still expect archetypal `IDF`).
- [ ] **Step 3: Port the components.**
- [ ] **Step 4: Run** the same command — Expected: PASS; `rg "archetypal" epinterface/sbem/components` finds nothing.
- [ ] **Step 5: Commit** — `git commit -m "refactor: port sbem components to idfkit"`.

---

### Task 7: Geometry on idfkit

**Files:**
- Modify: `epinterface/geometry.py`
- Test: `tests/test_geometry.py`, `tests/test_neighbor_shading_geometry.py` (switch to `doc`), `tests/test_geometry_zone_names.py` (new)

**Interfaces:**
- Produces:
  - `ShoeboxGeometry.add(self, doc: IDFDocument) -> IDFDocument`.
  - `match_idf_to_scene(...)` (line ~60) and the shading helpers take `doc: IDFDocument`.
  - Zones are built with `idfkit.zoning.create_block` (`ZoningScheme.BY_STOREY` / `CORE_PERIMETER`, `perimeter_depth=self.perim_depth`); the basement storey is built explicitly (idfkit has no below-ground storeys) as a storey at `base_elevation=-self.h`, then every zone is renamed with `doc.rename("Zone", old, new)` to the name and order in `geometry_baseline.json`. The renaming rule (storey index, core/perimeter suffix) is a private function `_geomeppy_zone_name(...)` derived from that fixture.
  - Rotation/scale/translate → `rotate_building`, `scale_building(doc, (sx, sy, 1.0), anchor=Vector3D(0,0,0))`, `translate_building`; neighbour blocks → `add_shading_block`; `intersect_match` → `intersect_and_match(doc)`; `set_default_constructions(doc)`.
  - Windows: idfkit's `set_wwr` has no surface filter, so windows go only on outdoor walls that are not attic or basement walls — either via `set_wwr` followed by removing windows on excluded walls, or a private `_add_window(doc, wall, wwr, construction="Project External Window")`. Window glass area per zone must match the fixture.
  - `geomeppy`'s `Polygon3D`/`Vector2D` → `idfkit.Polygon3D`/`Vector3D` (or plain tuples).

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("key", list(GEOMETRY_GRID))
def test_zone_names_match_baseline(key, doc):
    GEOMETRY_GRID[key].add(doc)
    assert [z.name for z in doc["Zone"]] == BASELINE["zone_names"][key]

def test_neighbor_with_zero_height_adds_no_shading(doc):
    geo = GEOMETRY_GRID["by_storey_neighbors"]  # heights [10.0, 0.0]
    geo.add(doc)
    assert len(doc["Shading:Building:Detailed"]) == BASELINE["shading_counts"]["by_storey_neighbors"]
```

Switch the existing geometry tests to `doc`; their asserted counts stay as they are.

- [ ] **Step 2: Run** `uv run pytest tests/test_geometry.py tests/test_neighbor_shading_geometry.py tests/test_geometry_zone_names.py -v` — Expected: FAIL.
- [ ] **Step 3: Port `geometry.py`.**
- [ ] **Step 4: Run** the same command — Expected: PASS; `rg "geomeppy|archetypal" epinterface/geometry.py` finds nothing.
- [ ] **Step 5: Commit** — `git commit -m "refactor: build shoebox geometry with idfkit, keep zone names"`.

---

### Task 8: Build, simulate and run on idfkit — regression green

**Files:**
- Modify: `epinterface/sbem/builder.py`, `epinterface/sbem/flat_model.py`, `epinterface/ddy_injector_bayes.py`, `tests/conftest.py` (remove `idf` fixture), `tests/test_components/test_builder.py`
- Test: `tests/test_regression.py`, `tests/test_builder_outputs.py` (new)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `Model.build(self, config: SimulationPathConfig, post_geometry_callback: Callable[[IDFDocument], IDFDocument] | None = None) -> IDFDocument`.
  - `Model.simulate(...) -> tuple[IDFDocument, SQLResult]` — runs `idfkit.simulation.simulate(doc, weather=epw_path, output_dir=config.output_dir, energyplus=find_energyplus(version=energyplus_settings.version_tuple))`; raises `idfkit.SimulationError` (unchanged behaviour: archetypal raised on failure too) when `result.success` is false.
  - `Model.get_warnings(self, output_dir: Path) -> str` — concatenated `*.err` text under `output_dir`.
  - `ModelRunResults.idf: IDFDocument`, `.sql: SQLResult`, `.hourly_timeseries(names)`.
  - `FlatModel.to_model() -> tuple[Model, Callable[[IDFDocument], IDFDocument]]`; the callback uses `rotate_building`.
  - `DDYSizingSpec.inject_ddy(doc: IDFDocument, ddy: IDFDocument)` copies objects with `doc.add(obj_type, name, fields)`.
  - Output objects reproduce archetypal's `prep_outputs`: exactly the `Output:*` objects (types, names, fields) present in `tests/data/regression/<key>/built.idf`, including `Output:SQLite` and the summary reports, then the desired meters/variables filter as today.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("key", list(REGRESSION_CONFIGS))
def test_output_objects_match_baseline(key, preseeded_readonly_db, tmp_path):
    model, _ = REGRESSION_CONFIGS[key](preseeded_readonly_db)
    doc = model.build(SimulationPathConfig(output_dir=tmp_path))
    base = load_idf(str(FIXTURES / key / "built.idf"))
    for t in [t for t in base.keys() if t.upper().startswith("OUTPUT")]:
        assert sorted(o.to_dict() for o in doc[t]) == sorted(o.to_dict() for o in base[t])  # use idfkit's dict export

def test_run_smoke_any_version(preseeded_readonly_db, tmp_path):
    model, _ = REGRESSION_CONFIGS["by_storey_plain"](preseeded_readonly_db)
    r = model.run(eplus_parent_dir=tmp_path)
    assert list(r.energy_and_peak.index) == list(pd.read_parquet(FIXTURES / "by_storey_plain" / "energy_and_peak.parquet").index)
    assert (tmp_path / "eplus_simulation").is_dir() and r.output_dir is not None
```

(Comparison of `to_dict` should ignore version-dependent default fields if `built.idf` is 25.2 and the doc differs only by defaults; the regression test is the real gate. The smoke test runs on every CI EnergyPlus version.)

- [ ] **Step 2: Run** `EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run pytest tests/test_builder_outputs.py tests/test_regression.py -v` — Expected: FAIL.
- [ ] **Step 3: Port the three modules.**
- [ ] **Step 4: Run** `EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run pytest -v --ignore=tests/test_actions.py` — Expected: all pass, including all three regression configurations. If a regression value misses `rtol=1e-3` while geometry matches: stop, write the explanation (which output, by how much, cause) into the PR description draft at `docs/superpowers/plans/regression-notes.md`, and ask the user before changing any tolerance.
- [ ] **Step 5: Run the smoke test on 22.2 or 24.2 if installed** — `EPINTERFACE_ENERGYPLUS_VERSION=24.2.0 uv run pytest tests/test_builder_outputs.py::test_run_smoke_any_version -v` (CI covers it otherwise).
- [ ] **Step 6: Commit** — `git commit -m "refactor: build, simulate and post-process sbem models with idfkit"`.

---

### Task 9: Legacy climate_studio path

**Files:**
- Modify: `epinterface/climate_studio/interface.py`, `epinterface/climate_studio/builder.py`, `epinterface/actions.py`, `scripts/*.py`, `notebooks/*.py`, `benchmarking/**/*.py` (any file that imports archetypal/eppy/geomeppy or `ddy_interface_bayes`)
- Delete: `epinterface/ddy_interface_bayes.py`
- Test: `tests/test_actions.py`

**Interfaces:**
- Consumes: Tasks 4–8 (document loading, schedules, simulate pattern, `results.py`).
- Produces: climate_studio builder returns `(IDFDocument, SQLResult)` where it returned `(IDF, Sql)`; `Values=...` on schedules (`interface.py:1704-1736`) built from component values, not archetypal `Schedule.Values`.

- [ ] **Step 1: Run** `uv run pytest tests/test_actions.py -v` — Expected: FAIL (archetypal types).
- [ ] **Step 2: Port the modules; delete `ddy_interface_bayes.py`.**
- [ ] **Step 3: Run** `uv run pytest -v` — Expected: whole suite passes.
- [ ] **Step 4: Commit** — `git commit -m "refactor: port climate_studio to idfkit, drop unused ddy_interface_bayes"`.

---

### Task 10: Remove archetypal, release 2.0.0

**Files:**
- Modify: `pyproject.toml` (remove `archetypal==2.18.10` and the commented `[tool.uv.sources]` archetypal line; `version = "2.0.0"`; description → "Dynamically generate EnergyPlus models in Python with idfkit."), `uv.lock`, `README.md`, `docs/**`
- Create: `CHANGELOG.md` (Keep a Changelog 1.1.0)

- [ ] **Step 1: Remove the dependency** — `uv remove archetypal`.
- [ ] **Step 2: Verify nothing references it** — Run: `rg -n "archetypal|eppy|geomeppy" --glob '!CHANGELOG.md' --glob '!docs/superpowers/**' --glob '!uv.lock' .` — Expected: no output; and `rg -n "archetypal|eppy|geomeppy" uv.lock` — Expected: no output.
- [ ] **Step 3: Write `CHANGELOG.md`** with a `## [2.0.0]` entry: *Changed* — idfkit replaces archetypal/eppy/geomeppy; *Added* — `ModelRunResults.hourly_timeseries(names)`; *Removed/Breaking* — the spec's "What breaks on purpose" list verbatim, plus the GLOBi one-line migration (`run_result.sql.timeseries_by_name(names, reporting_frequency="Hourly")` → `run_result.hourly_timeseries(names)`), and `ddy_interface_bayes` removal.
- [ ] **Step 4: Full verification** — Run: `EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run pytest -v && uv run pyright && uv run pre-commit run -a && uv run mkdocs build -s` — Expected: all pass, pyright 0 errors.
- [ ] **Step 5: Commit** — `git commit -am "chore!: drop archetypal, release 2.0.0"` (add `CHANGELOG.md`).
