"""Environmental fields on materials and assemblies (UP-9)."""

from pathlib import Path

import pytest

from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.envelope import (
    ConstructionAssemblyComponent,
    GasMaterialComponent,
    GlazingConstructionLayeredComponent,
    GlazingMaterialComponent,
)
from epinterface.sbem.components.materials import ConstructionMaterialComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import load_zone, small_model

MATERIAL_FIELDS = (
    "EmbodiedEnergy",
    "TransportCarbon",
    "TransportDistance",
    "TransportEnergy",
    "SubstitutionRatePattern",
    "SubstitutionTimestep",
)
OPAQUE_FIELDS = ("MoistureDiffusionResistance", "DesignStrength", "ModulusOfElasticity")
ASSEMBLY_FIELDS = (
    "AssemblyCarbon",
    "AssemblyCost",
    "AssemblyEnergy",
    "DisassemblyCarbon",
    "DisassemblyEnergy",
)


@pytest.mark.parametrize(
    ("cls", "fields"),
    [
        (ConstructionMaterialComponent, MATERIAL_FIELDS + OPAQUE_FIELDS),
        (GlazingMaterialComponent, MATERIAL_FIELDS),
        (GasMaterialComponent, MATERIAL_FIELDS),
        (ConstructionAssemblyComponent, ASSEMBLY_FIELDS),
        (GlazingConstructionLayeredComponent, ASSEMBLY_FIELDS),
    ],
)
def test_fields_optional(cls, fields):
    """Every life-cycle field exists and defaults to unknown."""
    for field in fields:
        info = cls.model_fields[field]
        assert not info.is_required()
        assert info.default is None


def test_seed_zone_loads_and_round_trips():
    """Older definitions load; set values survive JSON."""
    zone = load_zone()
    facade = zone.Envelope.Assemblies.FacadeAssembly
    facade.AssemblyCarbon = 12.5
    material = facade.Layers[0].ConstructionMaterial
    material.EmbodiedEnergy = 3.2
    material.SubstitutionRatePattern = [0.5, 1.0]
    material.MoistureDiffusionResistance = 50.0
    back = type(zone).model_validate_json(zone.model_dump_json())
    assert back.Envelope.Assemblies.FacadeAssembly.AssemblyCarbon == 12.5
    m = back.Envelope.Assemblies.FacadeAssembly.Layers[0].ConstructionMaterial
    assert (m.EmbodiedEnergy, m.SubstitutionRatePattern) == (3.2, [0.5, 1.0])
    assert m.MoistureDiffusionResistance == 50.0


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)
def test_not_simulated(tmp_path: Path):
    """Life-cycle fields do not change the EnergyPlus model."""
    plain = small_model(load_zone()).build(
        SimulationPathConfig(output_dir=tmp_path / "a")
    )
    zone = load_zone()
    zone.Envelope.Assemblies.FacadeAssembly.AssemblyEnergy = 100.0
    zone.Envelope.Assemblies.FacadeAssembly.Layers[
        0
    ].ConstructionMaterial.DesignStrength = 3e7
    tagged = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path / "b"))

    def materials(doc):
        return {
            (m.name, m.thickness, m.conductivity, m.density) for m in doc["Material"]
        }

    assert materials(plain) == materials(tagged)
