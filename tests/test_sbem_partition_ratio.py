"""Internal partitions per floor area (UP-9)."""

from pathlib import Path

import pytest

from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import load_zone, small_model

AREA = 12 * 8  # floor area of small_model's single zone [m2]

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _partitioned(ratio: float) -> ZoneComponent:
    z = load_zone()
    z.Envelope.Assemblies.PartitionAreaPerFloorArea = ratio
    return z


def test_default_has_none():
    """Older definitions load without internal partitions."""
    assert load_zone().Envelope.Assemblies.PartitionAreaPerFloorArea == 0


@needs_eplus
def test_build_writes_partition_mass(tmp_path: Path):
    """The zone gets internal mass of the partition assembly."""
    zone = _partitioned(0.5)
    doc = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path))
    mass = doc["InternalMass"].get("Block shoebox Storey 0_Partitions") or next(
        m for m in doc["InternalMass"] if m.name.endswith("_Partitions")
    )
    assert mass.construction_name == zone.Envelope.Assemblies.PartitionAssembly.Name
    assert mass.surface_area == pytest.approx(0.5 * AREA)
    plain = small_model(load_zone()).build(
        SimulationPathConfig(output_dir=tmp_path / "p")
    )
    assert not [m for m in plain["InternalMass"] if m.name.endswith("_Partitions")]


@needs_eplus
def test_simulated_partitions_change_results(tmp_path: Path):
    """Partitions add thermal mass: the model simulates and its loads change."""
    plain = small_model(load_zone()).run(eplus_parent_dir=tmp_path / "p")
    massive = small_model(_partitioned(2.0)).run(eplus_parent_dir=tmp_path / "m")
    try:
        a = plain.energy_and_peak.loc["Energy"]["Raw"]
        b = massive.energy_and_peak.loc["Energy"]["Raw"]
        assert (a["Heating"].sum(), a["Cooling"].sum()) != pytest.approx((
            b["Heating"].sum(),
            b["Cooling"].sum(),
        ))
    finally:
        plain.sql.close()
        massive.sql.close()
