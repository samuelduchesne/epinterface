"""Numeric heat-recovery effectiveness, sensible and latent (UP-2)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from epinterface.constants import assumed_constants
from epinterface.data import DefaultEPWZipPath
from epinterface.geometry import ShoeboxGeometry
from epinterface.sbem.builder import Model, SimulationPathConfig
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.test_sbem_energy import ZONE_PATH


@pytest.fixture(scope="module")
def zone() -> ZoneComponent:
    """The seed's default zone definition (mechanical ventilation, sensible HRV)."""
    return ZoneComponent.model_validate_json(ZONE_PATH.read_text())


def _with_hrv(zone: ZoneComponent, sensible: float | None, latent: float | None):
    z = zone.model_copy(deep=True)
    z.Operations.HVAC.Ventilation.SensibleHeatRecoveryEffectiveness = sensible
    z.Operations.HVAC.Ventilation.LatentHeatRecoveryEffectiveness = latent
    return z


def _model(zone: ZoneComponent) -> Model:
    from epinterface.sbem.archetype import AtticAssumptions, BasementAssumptions

    return Model(
        geometry=ShoeboxGeometry(
            x=0, y=0, w=12, d=8, h=3, wwr=0.3, num_stories=1, zoning="by_storey"
        ),
        Zone=zone,
        Attic=AtticAssumptions(UseFraction=None, Conditioned=False),
        Basement=BasementAssumptions(UseFraction=None, Conditioned=False),
        Weather=DefaultEPWZipPath,
    )


def test_defaults_fall_back_to_assumed_constants(zone: ZoneComponent):
    """Unset effectiveness keeps the former assumed constants."""
    v = zone.Operations.HVAC.Ventilation
    assert v.SensibleHeatRecoveryEffectiveness is None
    assert v.LatentHeatRecoveryEffectiveness is None
    assert (
        v.sensible_heat_recovery_effectiveness
        == assumed_constants.Sensible_Heat_Recovery_Effectiveness
    )
    assert (
        v.latent_heat_recovery_effectiveness
        == assumed_constants.Latent_Heat_Recovery_Effectiveness
    )


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_effectiveness_range(zone: ZoneComponent, value: float):
    """Effectiveness is a fraction."""
    data = zone.Operations.HVAC.Ventilation.model_dump()
    with pytest.raises(ValidationError):
        type(zone.Operations.HVAC.Ventilation).model_validate({
            **data,
            "SensibleHeatRecoveryEffectiveness": value,
        })


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)
def test_build_writes_effectiveness(zone: ZoneComponent, tmp_path: Path):
    """The ideal loads template takes the archetype's effectiveness."""
    doc = _model(_with_hrv(zone, 0.82, 0.55)).build(
        SimulationPathConfig(output_dir=tmp_path)
    )
    (template,) = doc["HVACTemplate:Zone:IdealLoadsAirSystem"]
    assert template.heat_recovery_type == "Sensible"
    assert template.sensible_heat_recovery_effectiveness == 0.82
    assert template.latent_heat_recovery_effectiveness == 0.55


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="simulating needs EnergyPlus",
)
def test_simulated_heating_falls_with_effectiveness(
    zone: ZoneComponent, tmp_path: Path
):
    """More effective heat recovery delivers less heating."""
    heating = {}
    for value in (0.0, 0.9):
        result = _model(_with_hrv(zone, value, None)).run(
            eplus_parent_dir=tmp_path / str(value)
        )
        result.sql.close()
        assert "** Severe  **" not in result.err_text
        energy = result.energy_and_peak.loc["Energy"].loc["Raw"]
        heating[value] = energy.loc["Heating"].sum()
    assert heating[0.9] < 0.9 * heating[0.0]
