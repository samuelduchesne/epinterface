"""Tests for the programmatically built base document."""

import json
import time
from pathlib import Path
from typing import Any

import idfkit
import pytest

from epinterface.document import (
    SUPPORTED_DOCUMENT_TYPES,
    EPDocument,
    _add_objects,
    _fill_minimal,
    add_or_replace,
    as_supported,
    minimal_document,
    watts_per_area,
)
from epinterface.settings import SUPPORTED_ENERGYPLUS_MAJORS, energyplus_settings

# The objects of the original EnergyPlus 22.2 Minimal.idf (tests/data/Minimal_22_2.idf)
# after IDFVersionUpdater migrated it to 25.2, captured once with the transition binaries.
SNAPSHOT = Path(__file__).parent / "data" / "minimal_25_2_snapshot.json"

SUPPORTED_MAJORS = {22, 23, 24, 25}
# 22.1 names several written fields differently; see SUPPORTED_DOCUMENT_TYPES.
SUPPORTED_VERSIONS = [
    v
    for v in idfkit.ENERGYPLUS_VERSIONS
    if v[0] in SUPPORTED_MAJORS and v != (22, 1, 0)
]
OTHER_VERSIONS = [v for v in idfkit.ENERGYPLUS_VERSIONS if v not in SUPPORTED_VERSIONS]


def _normalise_value(value: Any) -> str:
    text = str(value).strip()
    try:
        return repr(float(text))
    except ValueError:
        return text.lower()


def _canonical(doc: EPDocument, obj_type: str, fields: dict[str, Any]) -> str:
    """Ignore blank and schema-default fields, number formatting and case."""
    out: dict[str, str] = {}
    for key, value in fields.items():
        if isinstance(value, list):
            for i, group in enumerate(value):
                for inner_key, inner_value in group.items():
                    if inner_value not in (None, ""):
                        out[f"{inner_key}_{i}"] = _normalise_value(inner_value)
            continue
        if value in (None, ""):
            continue
        default = doc.schema.get_field_default(obj_type, key) if doc.schema else None
        if default is not None and _normalise_value(default) == _normalise_value(value):
            continue
        out[key] = _normalise_value(value)
    return repr(sorted(out.items()))


def _objects(doc: EPDocument) -> dict[str, list[str]]:
    return {
        t: sorted(_canonical(doc, t, o.to_dict()) for o in objs)
        for t, objs in doc.items()
        if t != "Version" and len(objs)
    }


def test_minimal_document_matches_migrated_minimal_idf():
    """Same objects and values as the migrated packaged Minimal.idf."""
    doc = minimal_document((25, 2, 0))
    expected_raw = json.loads(SNAPSHOT.read_text())
    expected = {
        t: sorted(_canonical(doc, t, fields) for fields in objs)
        for t, objs in expected_raw.items()
    }
    assert _objects(doc) == expected


def test_minimal_document_has_no_extra_baseline_objects():
    """`new_document`'s SimulationControl baseline is not part of the base model."""
    doc = minimal_document((25, 2, 0))
    assert len(doc["SimulationControl"]) == 0
    assert len(doc["Building"]) == 1
    assert len(doc["GlobalGeometryRules"]) == 1


def test_minimal_document_returns_independent_documents():
    """Each call is a fresh document."""
    a = minimal_document((25, 2, 0))
    a["Building"]["None"].north_axis = 90.0
    assert minimal_document((25, 2, 0))["Building"]["None"].north_axis == 0.0


def _assert_valid(version: tuple[int, int, int]) -> None:
    doc = idfkit.new_document(version)
    _fill_minimal(doc)
    assert doc.version == version
    result = idfkit.validate_document(doc)
    assert not result.errors, [str(e) for e in result.errors]


@pytest.mark.parametrize("version", SUPPORTED_VERSIONS, ids=idfkit.version_string)
def test_minimal_document_validates_for_supported_versions(version):
    """Every version epinterface supports builds a schema-valid document."""
    _assert_valid(version)


@pytest.mark.parametrize("version", OTHER_VERSIONS, ids=idfkit.version_string)
def test_minimal_objects_validate_for_other_idfkit_versions(version):
    """The minimal objects are schema-valid for every other version idfkit knows too."""
    _assert_valid(version)


@pytest.mark.parametrize("version", OTHER_VERSIONS, ids=idfkit.version_string)
def test_minimal_document_refuses_unsupported_versions(version):
    """A version epinterface does not support fails before any object is added."""
    with pytest.raises(TypeError, match=idfkit.version_string(version)):
        minimal_document(version)


@pytest.mark.parametrize("version", SUPPORTED_VERSIONS, ids=idfkit.version_string)
def test_minimal_document_is_typed_for_its_version(version):
    """`as_supported` accepts every supported version's document."""
    doc = minimal_document(version)
    assert as_supported(doc) is doc
    assert doc.version == version


def test_supported_document_types_match_supported_majors():
    """The typed releases are the releases of the supported majors, but 22.1."""
    assert {t.__name__ for t in SUPPORTED_DOCUMENT_TYPES} == {
        f"IDFDocumentV{v[0]}_{v[1]}" for v in SUPPORTED_VERSIONS
    }
    assert set(SUPPORTED_ENERGYPLUS_MAJORS) == SUPPORTED_MAJORS


def test_minimal_document_is_fast():
    """No migration step: the build is far below a second."""
    minimal_document(energyplus_settings.version_tuple)  # warm the schema cache
    start = time.perf_counter()
    minimal_document(energyplus_settings.version_tuple)
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize("version", [(22, 1, 0), (25, 2, 0)], ids=idfkit.version_string)
def test_unknown_field_fails_loudly(version):
    """A mistyped field name is an error, not silently dropped."""
    doc = idfkit.new_document(version)
    with pytest.raises(Exception, match="typo_field"):
        _add_objects(doc, (("Sizing:Parameters", "", {"typo_field": 1.15}),))


_WOOD = {
    "roughness": "MediumSmooth",
    "thickness": 0.1,
    "conductivity": 0.12,
    "density": 540.0,
    "specific_heat": 1210.0,
}


def test_add_or_replace_reuses_identical_object(doc: EPDocument):
    """An object with the same type, name and fields is returned, not duplicated."""
    first = add_or_replace(doc, "Material", "Wood", **_WOOD)
    second = add_or_replace(doc, "Material", "Wood", **_WOOD)
    assert second is first
    assert len(doc["Material"]) == 1


def test_add_or_replace_replaces_different_object(doc: EPDocument):
    """An object with the same type and name but other fields replaces the old one."""
    add_or_replace(doc, "Material", "Wood", **_WOOD)
    add_or_replace(doc, "Material", "Wood", **(_WOOD | {"thickness": 0.2}))
    assert len(doc["Material"]) == 1
    assert doc["Material"]["Wood"].thickness == 0.2


def test_add_or_replace_leaves_none_fields_blank(doc: EPDocument):
    """None means unset: the field stays blank and does not break reuse."""
    first = add_or_replace(doc, "Material", "Wood", **_WOOD, solar_absorptance=None)
    assert first.solar_absorptance in (None, "")
    assert add_or_replace(doc, "Material", "Wood", **_WOOD) is first


def test_add_or_replace_replaces_singleton(doc: EPDocument):
    """A type allowed once (Timestep) holds only the latest definition."""
    add_or_replace(doc, "Timestep", number_of_timesteps_per_hour=4)
    add_or_replace(doc, "Timestep", number_of_timesteps_per_hour=6)
    assert [t.number_of_timesteps_per_hour for t in doc["Timestep"]] == [6]


def test_add_or_replace_unknown_field_raises(doc: EPDocument):
    """A field the schema does not know is an error, not silently dropped."""
    with pytest.raises(Exception, match="typo_field"):
        add_or_replace(doc, "Material", "Wood", **_WOOD, typo_field=1)


@pytest.mark.parametrize("version", SUPPORTED_VERSIONS, ids=idfkit.version_string)
@pytest.mark.parametrize("obj_type", ["Lights", "ElectricEquipment"])
def test_watts_per_area_is_a_field_of_every_supported_version(version, obj_type):
    """The design level lands in the field the version's schema has."""
    doc = minimal_document(version)
    obj = add_or_replace(
        doc,
        obj_type,
        "Load",
        zone_or_zonelist_or_space_or_spacelist_name="Zone",
        schedule_name="Always On",
        design_level_calculation_method="Watts/Area",
        **watts_per_area(doc, 8.5),
    )
    expected = (
        "watts_per_zone_floor_area" if version < (24, 1, 0) else "watts_per_floor_area"
    )
    assert obj[expected] == 8.5


def test_add_or_replace_keeps_the_original_when_the_replacement_is_refused(
    doc: EPDocument,
):
    """A replacement that fails validation leaves the existing object in place."""
    add_or_replace(doc, "Material", "Wood", **_WOOD)
    with pytest.raises(Exception, match="thickness"):
        add_or_replace(doc, "Material", "Wood", **(_WOOD | {"thickness": -0.1}))
    assert doc["Material"]["Wood"].thickness == _WOOD["thickness"]
    assert len(doc["Material"]) == 1


def test_minimal_documents_do_not_share_field_values():
    """Editing one document's list-valued field leaves later documents untouched."""
    version = energyplus_settings.version_tuple
    first = minimal_document(version)
    reports = first["Output:Table:SummaryReports"][0].reports
    count = len(reports)
    reports.append({"report_name": "ZoneComponentLoadSummary"})
    second = minimal_document(version)
    assert len(second["Output:Table:SummaryReports"][0].reports) == count
