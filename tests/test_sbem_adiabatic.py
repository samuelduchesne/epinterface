"""Adiabatic flags per assembly (UP-9)."""

from pathlib import Path

import pytest

from epinterface.data import DefaultEPWZipPath
from epinterface.geometry import ShoeboxGeometry
from epinterface.sbem.archetype import AtticAssumptions, BasementAssumptions
from epinterface.sbem.builder import Model, SimulationPathConfig
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import load_zone, small_model

FLAGS = (
    "IsFacadeAdiabatic",
    "IsRoofAdiabatic",
    "IsGroundAdiabatic",
    "IsPartitionAdiabatic",
    "IsSlabAdiabatic",
)

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _flagged(*flags: str) -> ZoneComponent:
    z = load_zone()
    for flag in flags:
        setattr(z.Envelope.Assemblies, flag, True)
    return z


def _two_storey(zone: ZoneComponent) -> Model:
    return Model(
        geometry=ShoeboxGeometry(
            x=0,
            y=0,
            w=20,
            d=20,
            h=3,
            wwr=0.3,
            num_stories=2,
            zoning="core/perim",
            perim_depth=4,
        ),
        Zone=zone,
        Attic=AtticAssumptions(UseFraction=None, Conditioned=False),
        Basement=BasementAssumptions(UseFraction=None, Conditioned=False),
        Weather=DefaultEPWZipPath,
    )


def _boundaries(doc) -> dict[tuple[str, str], set[str]]:
    seen: dict[tuple[str, str], set[str]] = {}
    for srf in doc["BuildingSurface:Detailed"]:
        key = (
            (srf.surface_type or "").lower(),
            (srf.outside_boundary_condition or "").lower(),
        )
        seen.setdefault(key, set()).add(srf.name)
    return seen


def test_defaults_off():
    """Older definitions load with no adiabatic surfaces."""
    a = load_zone().Envelope.Assemblies
    assert not any(getattr(a, f) for f in FLAGS)


@needs_eplus
@pytest.mark.parametrize(
    ("flag", "kind", "before"),
    [
        ("IsFacadeAdiabatic", "wall", "outdoors"),
        ("IsRoofAdiabatic", "roof", "outdoors"),
        ("IsGroundAdiabatic", "floor", "ground"),
        ("IsPartitionAdiabatic", "wall", "surface"),
        ("IsSlabAdiabatic", "floor", "surface"),
    ],
)
def test_build_makes_surfaces_adiabatic(
    flag: str, kind: str, before: str, tmp_path: Path
):
    """Each flag turns its surfaces, and only those, adiabatic."""
    plain = _boundaries(
        _two_storey(load_zone()).build(SimulationPathConfig(output_dir=tmp_path / "p"))
    )
    doc = _two_storey(_flagged(flag)).build(SimulationPathConfig(output_dir=tmp_path))
    flagged = _boundaries(doc)
    assert (kind, before) in plain
    assert (kind, before) not in flagged
    assert plain[(kind, before)] <= flagged[(kind, "adiabatic")]
    for srf in doc["BuildingSurface:Detailed"]:
        if (srf.outside_boundary_condition or "").lower() == "adiabatic":
            assert not srf.outside_boundary_condition_object


@needs_eplus
def test_simulated_adiabatic_envelope_needs_less_heating(tmp_path: Path):
    """An adiabatic facade, roof and ground cut the heating demand."""
    plain = small_model(load_zone()).run(eplus_parent_dir=tmp_path / "p")
    sealed = small_model(
        _flagged("IsFacadeAdiabatic", "IsRoofAdiabatic", "IsGroundAdiabatic")
    ).run(eplus_parent_dir=tmp_path / "s")
    try:
        heat_plain = plain.energy_and_peak.loc["Energy"]["Raw"]["Heating"].sum()
        heat_sealed = sealed.energy_and_peak.loc["Energy"]["Raw"]["Heating"].sum()
    finally:
        plain.sql.close()
        sealed.sql.close()
    assert heat_sealed < 0.5 * heat_plain


@needs_eplus
def test_adiabatic_facade_has_no_windows(tmp_path: Path):
    """EnergyPlus allows no window on an adiabatic wall: they are removed."""
    doc = small_model(_flagged("IsFacadeAdiabatic")).build(
        SimulationPathConfig(output_dir=tmp_path)
    )
    assert len(doc["FenestrationSurface:Detailed"]) == 0


@needs_eplus
def test_simulated_interzone_adiabatic_runs(tmp_path: Path):
    """Adiabatic partitions and slabs between zones simulate."""
    result = _two_storey(_flagged("IsPartitionAdiabatic", "IsSlabAdiabatic")).run(
        eplus_parent_dir=tmp_path
    )
    try:
        assert result.energy_and_peak.loc["Energy"]["Raw"]["Heating"].sum() > 0
    finally:
        result.sql.close()
