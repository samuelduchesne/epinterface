"""Natural-ventilation limits and switches (UP-9)."""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from epinterface.document import EPDocument
from epinterface.results import timeseries_frame
from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.systems import VentilationComponent
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import load_zone, small_model

NATURAL_FLOW = "Zone Ventilation Standard Density Volume Flow Rate"

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _natural(**fields) -> ZoneComponent:
    z = load_zone()
    v = z.Operations.HVAC.Ventilation
    data = {**v.model_dump(), "Provider": "Natural", "HRV": "NoHRV", **fields}
    z.Operations.HVAC.Ventilation = VentilationComponent.model_validate(data)
    return z


def test_defaults_reproduce_fixed_limits():
    """Older definitions load with the limits SBEM had fixed."""
    v = load_zone().Operations.HVAC.Ventilation
    assert (v.NatVentMinOutdoorAirTemp, v.NatVentMaxOutdoorAirTemp) == (12.0, 25.0)
    assert v.NatVentMaxRelHumidity is None
    assert v.NatVentZoneTempSetpoint is None
    assert (v.IsWindOn, v.IsBuoyancyOn) == (True, False)


def test_min_below_max():
    """The outdoor temperature band must not be empty."""
    with pytest.raises(ValidationError, match="NatVentMinOutdoorAirTemp"):
        _natural(NatVentMinOutdoorAirTemp=26.0, NatVentMaxOutdoorAirTemp=25.0)


@needs_eplus
def test_build_writes_limits(tmp_path: Path):
    """The wind-and-stack object takes the limits and switches."""
    zone = _natural(
        NatVentMinOutdoorAirTemp=8.0,
        NatVentMaxOutdoorAirTemp=28.0,
        NatVentZoneTempSetpoint=21.0,
        NatVentMaxRelHumidity=80.0,
        IsWindOn=False,
        IsBuoyancyOn=True,
    )
    doc = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path))
    (vent,) = doc["ZoneVentilation:WindandStackOpenArea"]
    assert vent.minimum_outdoor_temperature == 8.0
    assert vent.maximum_outdoor_temperature == 28.0
    assert vent.minimum_indoor_temperature == 21.0
    assert vent.opening_effectiveness == 0.0
    # half the 0.999 x 0.3 ribbon window of a 3 m storey, about 0.45 m
    assert vent.height_difference == pytest.approx(0.5 * 3 * 0.3, rel=0.05)
    (program,) = doc["EnergyManagementSystem:Program"]
    assert "> 80.0" in program.lines[0].program_line
    assert len(doc["EnergyManagementSystem:Actuator"]) == 1


@needs_eplus
def test_build_without_driver_writes_nothing(tmp_path: Path):
    """With neither wind nor buoyancy, nothing drives the air: no object."""
    zone = _natural(IsWindOn=False, IsBuoyancyOn=False)
    doc = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path))
    assert len(doc["ZoneVentilation:WindandStackOpenArea"]) == 0


def _request(doc: EPDocument) -> EPDocument:
    doc["Output:Variable"].add(
        key_value="*", variable_name=NATURAL_FLOW, reporting_frequency="Hourly"
    )
    return doc


def _annual_flow(zone: ZoneComponent, tmp_path: Path) -> float:
    result = small_model(zone).run(
        eplus_parent_dir=tmp_path, post_geometry_callback=_request
    )
    try:
        frame = timeseries_frame(result.sql, NATURAL_FLOW, "Hourly")
        assert not frame.empty
        return float(np.nansum(frame.to_numpy()))
    finally:
        result.sql.close()


@needs_eplus
def test_simulated_limits_change_flow(tmp_path: Path):
    """Humidity and indoor limits shut the windows; buoyancy alone still ventilates."""
    base = _annual_flow(_natural(), tmp_path / "base")
    assert base > 0
    assert _annual_flow(_natural(NatVentMaxRelHumidity=0.0), tmp_path / "rh") == 0
    narrower = _annual_flow(
        _natural(NatVentMinOutdoorAirTemp=18.0, NatVentMaxOutdoorAirTemp=22.0),
        tmp_path / "band",
    )
    assert 0 < narrower < base
    assert _annual_flow(_natural(NatVentZoneTempSetpoint=99.0), tmp_path / "in") == 0
    stack = _annual_flow(_natural(IsWindOn=False, IsBuoyancyOn=True), tmp_path / "s")
    assert stack > 0
