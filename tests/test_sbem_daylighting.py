"""Daylighting parameters (UP-9)."""

from pathlib import Path

import pytest

from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import load_zone, small_model

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _dimmed(dimming: str = "Continuous", **fields) -> ZoneComponent:
    z = load_zone()
    lighting = z.Operations.SpaceUse.Lighting
    lighting.DimmingType = dimming  # type: ignore[assignment]
    for key, value in fields.items():
        setattr(lighting, key, value)
    return z


def test_defaults():
    """Older definitions load with UMI's usual daylighting defaults."""
    lighting = load_zone().Operations.SpaceUse.Lighting
    assert lighting.IlluminanceTarget == 500.0
    assert lighting.DaylightWorkplaneHeight == 0.8
    assert lighting.DaylightMeshResolution is None


@needs_eplus
def test_build_writes_daylighting_controls(tmp_path: Path):
    """Dimming writes a reference point at the workplane and a control."""
    zone = _dimmed(
        "Stepped",
        IlluminanceTarget=300.0,
        DaylightWorkplaneHeight=0.75,
        DaylightMeshResolution=1.0,
    )
    doc = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path))
    (control,) = doc["Daylighting:Controls"]
    assert control.lighting_control_type == "Stepped"
    (data,) = control.control_data
    assert data.illuminance_setpoint_at_reference_point == 300.0
    (point,) = doc["Daylighting:ReferencePoint"]
    assert point.z_coordinate_of_reference_point == pytest.approx(0.75)
    assert point.x_coordinate_of_reference_point == pytest.approx(6.0)
    assert point.y_coordinate_of_reference_point == pytest.approx(4.0)
    (grid,) = doc["Output:IlluminanceMap"]
    assert (grid.number_of_x_grid_points, grid.number_of_y_grid_points) == (13, 9)
    plain = small_model(load_zone()).build(
        SimulationPathConfig(output_dir=tmp_path / "p")
    )
    assert len(plain["Daylighting:Controls"]) == 0


@needs_eplus
def test_simulated_dimming_saves_lighting(tmp_path: Path):
    """Continuous dimming lowers the lighting energy."""
    plain = small_model(load_zone()).run(eplus_parent_dir=tmp_path / "p")
    dimmed = small_model(_dimmed(DaylightMeshResolution=2.0)).run(
        eplus_parent_dir=tmp_path / "d"
    )
    try:
        light_plain = plain.energy_and_peak.loc["Energy"]["Raw"]["Lighting"].sum()
        light_dimmed = dimmed.energy_and_peak.loc["Energy"]["Raw"]["Lighting"].sum()
    finally:
        plain.sql.close()
        dimmed.sql.close()
    assert light_dimmed < 0.9 * light_plain
