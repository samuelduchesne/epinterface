"""Archetype save and load with a schema version (UP-2)."""

import gzip
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from epinterface.sbem.archetype import (
    ARCHETYPE_SCHEMA_VERSION,
    SUPPORTED_ARCHETYPE_SCHEMA_VERSIONS,
    Archetype,
    ArchetypeSchemaVersionError,
    ZoneGroup,
)
from tests.sbem_helpers import day, load_zone, week, year

# Written by the fork at 9ff8add (schema 1.0), before UP-8 and UP-2's extra fields.
V1_0_FILE = Path(__file__).parent / "data" / "archetype_v1_0.sbem.json.gz"


def _v1_0_text() -> str:
    return gzip.decompress(V1_0_FILE.read_bytes()).decode("utf-8")


def _new_fields_archetype() -> Archetype:
    """An archetype using every field schema 1.1 adds."""
    zone = load_zone()
    systems = zone.Operations.HVAC.ConditioningSystems
    systems.SpecificFanPower = 1200.0
    systems.MaximumHeatingSupplyAirTemperature = 45.0
    systems.MinimumCoolingSupplyAirTemperature = 12.0
    assert systems.Heating is not None
    systems.Heating = systems.Heating.model_copy(
        update={"EIRTemperatureSlope": -0.01, "EIRReferenceTemperature": 7.0}
    )
    ventilation = zone.Operations.HVAC.Ventilation
    ventilation.SensibleHeatRecoveryEffectiveness = 0.8
    ventilation.LatentHeatRecoveryEffectiveness = 0.6
    on, off = day("on", [1.0] * 24), day("off", [0.0] * 24)
    zone.Envelope.Infiltration.Schedule = year(
        "inf", week("inf_week", on, Holiday=off, SummerDesignDay=off), "Infiltration"
    )
    return Archetype(Name="v1_1", Groups=[ZoneGroup(Name="all", Zone=zone)])


def test_current_version_and_supported_versions():
    """This epinterface writes 1.1 and reads 1.0 and 1.1."""
    assert ARCHETYPE_SCHEMA_VERSION == "1.1"
    assert SUPPORTED_ARCHETYPE_SCHEMA_VERSIONS == ("1.0", "1.1")


def test_v1_0_file_loads_with_defaults(tmp_path: Path):
    """A file written before the new fields loads, with backward-compatible defaults."""
    path = tmp_path / "old.sbem.json"
    path.write_text(_v1_0_text(), encoding="utf-8")
    assert Archetype.schema_version_of(path) == "1.0"
    a = Archetype.load(path)
    assert a.SchemaVersion == ARCHETYPE_SCHEMA_VERSION
    zone = a.Groups[0].Zone
    systems = zone.Operations.HVAC.ConditioningSystems
    assert systems.SpecificFanPower is None
    assert systems.MaximumHeatingSupplyAirTemperature == 30.0
    assert systems.MinimumCoolingSupplyAirTemperature == 13.0
    assert zone.Envelope.Infiltration.Schedule is None
    assert zone.Operations.SpaceUse.Lighting.Schedule.January.Holiday is None
    # re-saving records the current version
    again = a.save(tmp_path / "again.sbem.json")
    assert Archetype.schema_version_of(again) == ARCHETYPE_SCHEMA_VERSION
    assert Archetype.load(again) == a


def test_new_fields_round_trip(tmp_path: Path):
    """Every new field survives save and load, byte for byte."""
    a = _new_fields_archetype()
    path = a.save(tmp_path / "new.sbem.json")
    b = Archetype.load(path)
    assert b == a
    assert b.save(tmp_path / "again.sbem.json").read_bytes() == path.read_bytes()
    assert f'"SchemaVersion": "{ARCHETYPE_SCHEMA_VERSION}"' in path.read_text()


def test_file_without_version_is_read_as_1_0(tmp_path: Path):
    """A file that records no version is read as 1.0."""
    data = json.loads(_v1_0_text())
    del data["SchemaVersion"]
    path = tmp_path / "unversioned.sbem.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert Archetype.schema_version_of(path) == "1.0"
    assert Archetype.load(path).SchemaVersion == ARCHETYPE_SCHEMA_VERSION


def test_newer_version_refused_before_its_fields(tmp_path: Path):
    """A newer file is refused for its version, not for fields this one lacks."""
    data = json.loads(_new_fields_archetype().to_json())
    data["SchemaVersion"] = "2.0"
    data["Groups"][0]["SomethingNew"] = 1
    path = tmp_path / "newer.sbem.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ArchetypeSchemaVersionError, match="'2.0' is not supported"):
        Archetype.load(path)


def test_unsupported_version_in_python_data():
    """Validating data of an unsupported version fails with the version named."""
    data = _new_fields_archetype().model_dump()
    data["SchemaVersion"] = "0.9"
    with pytest.raises(ValidationError, match="'0.9' is not supported"):
        Archetype.model_validate(data)
