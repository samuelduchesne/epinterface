"""Tests for the programmatically built base document."""

import json
import time
from pathlib import Path
from typing import Any

import idfkit
import pytest
from idfkit import IDFDocument

from epinterface.document import minimal_document
from epinterface.settings import energyplus_settings

# The objects of the original EnergyPlus 22.2 Minimal.idf (tests/data/Minimal_22_2.idf)
# after IDFVersionUpdater migrated it to 25.2, captured once with the transition binaries.
SNAPSHOT = Path(__file__).parent / "data" / "minimal_25_2_snapshot.json"

SUPPORTED_MAJORS = {22, 23, 24, 25}
SUPPORTED_VERSIONS = [v for v in idfkit.ENERGYPLUS_VERSIONS if v[0] in SUPPORTED_MAJORS]
OTHER_VERSIONS = [v for v in idfkit.ENERGYPLUS_VERSIONS if v not in SUPPORTED_VERSIONS]


def _normalise_value(value: Any) -> str:
    text = str(value).strip()
    try:
        return repr(float(text))
    except ValueError:
        return text.lower()


def _canonical(doc: IDFDocument, obj_type: str, fields: dict[str, Any]) -> str:
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


def _objects(doc: IDFDocument) -> dict[str, list[str]]:
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
    doc = minimal_document(version)
    assert doc.version == version
    result = idfkit.validate_document(doc)
    assert not result.errors, [str(e) for e in result.errors]


@pytest.mark.parametrize("version", SUPPORTED_VERSIONS, ids=idfkit.version_string)
def test_minimal_document_validates_for_supported_versions(version):
    """Every version epinterface supports builds a schema-valid document."""
    _assert_valid(version)


@pytest.mark.parametrize("version", OTHER_VERSIONS, ids=idfkit.version_string)
def test_minimal_document_validates_for_other_idfkit_versions(version):
    """Every other version idfkit knows builds a schema-valid document too."""
    _assert_valid(version)


def test_minimal_document_is_fast():
    """No migration step: the build is far below a second."""
    minimal_document(energyplus_settings.version_tuple)  # warm the schema cache
    start = time.perf_counter()
    minimal_document(energyplus_settings.version_tuple)
    assert time.perf_counter() - start < 1.0
