"""The building's structure (UP-9)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from epinterface.sbem.archetype import Archetype, ZoneGroup
from epinterface.sbem.components.structure import (
    MassRatioComponent,
    StructureComponent,
)
from tests.sbem_helpers import load_zone


def _concrete():
    return load_zone().Envelope.Assemblies.FacadeAssembly.Layers[0].ConstructionMaterial


def test_archetype_default_has_no_structure():
    """Archetypes without a structure load as before."""
    a = Archetype(Name="a", Groups=[ZoneGroup(Name="g", Zone=load_zone())])
    assert a.Structure is None


def test_defaults_follow_umi():
    """A bare structure has UMI's default advanced model."""
    s = StructureComponent(Name="s")
    assert s.MassRatios == [] and s.UseAdvancedModel is False
    model = s.AdvancedModel
    assert model.ColumnWallSpacing.PrimarySpan == 8.0
    assert model.ConstructionSystems.Floors.ConstructionSystemType == "OneWayFlatSlab"
    assert model.FoundationSoilSettings.FoundationSoilPreset == "Clay"
    assert model.LoadingSettings.LiveLoadingValue == 2.4


def test_round_trip(tmp_path: Path):
    """A structure survives the archetype's save and load."""
    s = StructureComponent(
        Name="frame",
        AssemblyCarbon=30.0,
        MassRatios=[
            MassRatioComponent(Material=_concrete(), NormalRatio=400, HighLoadRatio=600)
        ],
        UseAdvancedModel=True,
    )
    s.AdvancedModel.ConstructionSystems.Columns.Material = _concrete()
    s.AdvancedModel.ConstructionSystems.Columns.ConstructionSystemType = "SquareTube"
    a = Archetype(Name="a", Groups=[ZoneGroup(Name="g", Zone=load_zone())], Structure=s)
    back = Archetype.load(a.save(tmp_path / "a.sbem.json"))
    assert back == a
    assert back.Structure is not None
    assert (
        back.Structure.AdvancedModel.ConstructionSystems.Columns.Material == _concrete()
    )


def test_unknown_system_type_refused():
    """Construction system types are UMI's."""
    with pytest.raises(ValidationError):
        StructureComponent.model_validate({
            "Name": "s",
            "AdvancedModel": {
                "ConstructionSystems": {"Beams": {"ConstructionSystemType": "Arch"}}
            },
        })
