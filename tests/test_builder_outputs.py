"""The sbem builder's output objects and run directory, checked against the archetypal baseline."""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from idfkit import IDFDocument, IDFObject, load_idf

from epinterface.sbem.builder import SimulationPathConfig
from epinterface.settings import energyplus_settings
from tests.regression.configs import REGRESSION_CONFIGS

FIXTURES = Path(__file__).parent / "data" / "regression"
# built.idf holds EnergyPlus 25.2 objects under a stale "22.2" Version line
# (archetypal was told the file was already 25.2 and never transitioned it).
BASELINE_VERSION = (25, 2, 0)


def _normalise_value(value: Any) -> str:
    """Case- and number-format-insensitive text for one field value."""
    text = str(value).strip()
    try:
        return repr(float(text))
    except ValueError:
        return text.lower()


def _canonical(doc: IDFDocument, obj: IDFObject) -> str:
    """An orderable form of an object, ignoring blank and schema-default fields.

    Fields archetypal filled with their schema default and idfkit leaves blank
    therefore compare equal; any other field difference does not.
    """
    fields: dict[str, str] = {}
    for key, value in obj.to_dict().items():
        if isinstance(value, list):
            # extensible groups, e.g. Output:Table:SummaryReports' report names
            for i, group in enumerate(value):
                for inner_key, inner_value in group.items():
                    if inner_value not in (None, ""):
                        fields[f"{inner_key}_{i}"] = _normalise_value(inner_value)
            continue
        if value in (None, ""):
            continue
        default = (
            doc.schema.get_field_default(obj.obj_type, key) if doc.schema else None
        )
        if default is not None and _normalise_value(default) == _normalise_value(value):
            continue
        fields[key] = _normalise_value(value)
    return repr(sorted(fields.items()))


def _output_objects(doc: IDFDocument) -> dict[str, list[str]]:
    return {
        obj_type.lower(): sorted(_canonical(doc, o) for o in objs)
        for obj_type, objs in doc.items()
        if obj_type.upper().startswith("OUTPUT") and len(objs)
    }


@pytest.mark.skipif(
    energyplus_settings.energyplus_version != "25.2.0",
    reason="The baseline built.idf files are EnergyPlus 25.2.0 models",
)
@pytest.mark.parametrize("key", list(REGRESSION_CONFIGS))
def test_output_objects_match_baseline(key, preseeded_readonly_db, tmp_path):
    """The built model requests exactly the outputs archetypal's prep_outputs did."""
    model, _ = REGRESSION_CONFIGS[key](preseeded_readonly_db)
    doc = model.build(SimulationPathConfig(output_dir=tmp_path))
    base = load_idf(str(FIXTURES / key / "built.idf"), version=BASELINE_VERSION)
    assert _output_objects(doc) == _output_objects(base)


def test_run_smoke_any_version(preseeded_readonly_db, tmp_path):
    """A model runs on the configured EnergyPlus and keeps its run directory."""
    model, _ = REGRESSION_CONFIGS["by_storey_plain"](preseeded_readonly_db)
    r = model.run(eplus_parent_dir=tmp_path)
    expected = pd.read_parquet(FIXTURES / "by_storey_plain" / "energy_and_peak.parquet")
    assert list(r.energy_and_peak.index) == list(expected.index)
    assert (tmp_path / "eplus_simulation").is_dir()
    assert r.output_dir is not None
    assert r.doc.version == energyplus_settings.version_tuple
