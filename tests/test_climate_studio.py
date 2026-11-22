"""The climate studio library and shoebox builder, on idfkit documents."""

import json
from pathlib import Path

import pytest
from idfkit.schedules import values as schedule_values

from epinterface.climate_studio.builder import Model, SimulationPathConfig
from epinterface.climate_studio.interface import (
    ClimateStudioLibraryV2,
    LibrarySchedule,
    extract_sch,
)
from epinterface.data import DefaultEPWZipPath
from epinterface.document import EPDocument
from epinterface.geometry import ShoeboxGeometry
from epinterface.settings import energyplus_settings
from tests.conftest import SQLCleanupSpy

LIB_PATH = Path(__file__).parent / "data" / "test_lib.json"


@pytest.fixture
def lib_data() -> dict:
    """The raw test library."""
    return json.loads(LIB_PATH.read_text())


@pytest.fixture
def lib(lib_data: dict) -> ClimateStudioLibraryV2:
    """The test library, with a window construction it defines."""
    lib = ClimateStudioLibraryV2.model_validate(lib_data)
    for env in lib.Envelopes.values():
        assert env.WindowDefinition is not None
        env.WindowDefinition.Construction = "Template_post_2003"
    return lib


def _model(lib: ClimateStudioLibraryV2) -> Model:
    return Model(
        Weather=DefaultEPWZipPath,
        lib=lib,
        space_use_name="MA_SF_pre_1975",
        envelope_name="MA_SF_pre_1975",
        geometry=ShoeboxGeometry(
            x=0,
            y=0,
            w=10,
            d=10,
            h=3,
            wwr=0.2,
            num_stories=2,
            basement=False,
            zoning="by_storey",
            roof_height=None,
        ),
    )


def test_library_schedules_hold_their_values(lib_data: dict):
    """Library schedules keep the type limits and 8760 values they were loaded with."""
    lib = ClimateStudioLibraryV2.model_validate(lib_data)
    occ = lib.Schedules["MA_OCC_SCH"]
    assert isinstance(occ, LibrarySchedule)
    assert occ.Values == lib_data["Schedules"]["MA_OCC_SCH"]["Values"]
    assert occ.Type.Name == "Fraction"


def test_library_serializes_to_the_same_json(lib_data: dict):
    """Dumping a library gives back the schedule data it was loaded from."""
    lib = ClimateStudioLibraryV2.model_validate(lib_data)
    dumped = lib.model_dump(mode="json")
    assert dumped["Schedules"] == lib_data["Schedules"]
    assert ClimateStudioLibraryV2.model_validate(dumped) == lib


def test_library_schedule_writes_year_schedule(doc: EPDocument, lib_data: dict):
    """A library schedule becomes a Schedule:Year with its type limits and values."""
    lib = ClimateStudioLibraryV2.model_validate(lib_data)
    occ = lib.Schedules["MA_OCC_SCH"]
    year = occ.add_to_idf(doc)
    assert year.name == "MA_OCC_SCH"
    assert year.schedule_type_limits_name == "Fraction"
    assert "Fraction" in doc["ScheduleTypeLimits"]
    written = schedule_values(year, year=2018, document=doc)
    # day 365 is not part of any week (see add_values_schedule)
    assert list(written[:8736]) == pytest.approx(occ.Values[:8736])


def test_extract_sch_resolves_type_names():
    """CSV schedule types resolve to the type limits archetypal used for them."""
    import pandas as pd

    header = [["Temperature"], ["RepeatingDay"], ["c"], ["d"], ["e"]]
    frame = pd.DataFrame(
        header + [[str(20 + h)] for h in range(24)], columns=["Setpoint"]
    )
    sch = extract_sch(frame, "Setpoint")
    assert sch.Type.model_dump() == {
        "Name": "Temperature",
        "LowerLimit": -100.0,
        "UpperLimit": 100.0,
        "NumericType": "Continuous",
        "UnitType": "Dimensionless",
    }
    assert len(sch.Values) == 8760
    assert sch.Values[:25] == [*(20.0 + h for h in range(24)), 20.0]


def test_build_returns_idfkit_document(lib: ClimateStudioLibraryV2, tmp_path):
    """The builder writes zones, loads, HVAC and the library schedules they use."""
    model = _model(lib)
    doc = model.build(SimulationPathConfig(output_dir=tmp_path))
    assert len(doc["Zone"]) == 2
    year_names = {s.name for s in doc["Schedule:Year"]}
    assert {"MA_OCC_SCH", "MA_EQUIP_SCHEDULE", "MA_LIGHTS_SCHEDULE"} <= year_names
    assert "AllOn" in year_names
    assert len(doc["People"]) == 1
    assert len(doc["WaterUse:Equipment"]) == 2
    assert len(doc["HVACTemplate:Zone:IdealLoadsAirSystem"]) == 2
    walls = [
        s
        for s in doc["BuildingSurface:Detailed"]
        if (s.surface_type or "").lower() == "wall"
        and (s.outside_boundary_condition or "").lower() == "outdoors"
    ]
    assert {w.construction_name for w in walls} == {"TEMPLATE_MA_SF_WOOD"}
    assert "TEMPLATE_MA_SF_WOOD" in doc["Construction"]
    # sizing periods, winter first as on the sbem path
    assert [p.name for p in doc["SizingPeriod:WeatherFileConditionType"]] == [
        "Winter Extreme",
        "Summer Extreme",
    ]
    # building does not mutate the library's schedules
    assert "AllOn" not in lib.Schedules


@pytest.mark.skipif(
    energyplus_settings.energyplus_version != "25.2.0",
    reason="simulation checked against EnergyPlus 25.2.0",
)
def test_run_simulates_and_postprocesses(
    lib: ClimateStudioLibraryV2, sql_cleanup_spy: SQLCleanupSpy
):
    """The model simulates with EnergyPlus and reports end uses per m2.

    The results file is closed before the temporary run directory is deleted.
    """
    doc, results, err_text = _model(lib).run(move_energy=True)
    assert sql_cleanup_spy.checked
    assert sql_cleanup_spy.still_open == []
    assert "EnergyPlus Completed Successfully" in err_text
    assert results.name == "kWh/m2"
    assert results["Electricity"] > 0
    # heating and hot water moved onto natural gas
    assert results["NaturalGas"] > 0
    assert "District Heating" not in results.index
