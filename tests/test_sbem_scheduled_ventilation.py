"""Scheduled ventilation (UP-9)."""

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
from tests.sbem_helpers import day, load_zone, small_model, week, year

FLOW = "Zone Ventilation Standard Density Volume Flow Rate"
NIGHT = [1.0] * 6 + [0.0] * 12 + [1.0] * 6

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _night_schedule():
    return year("night_flush", week("night_week", day("night", NIGHT)), "Window")


def _scheduled(**fields) -> ZoneComponent:
    z = load_zone()
    data = {
        **z.Operations.HVAC.Ventilation.model_dump(),
        "IsScheduledVentilationOn": True,
        "ScheduledVentilationAch": 2.0,
        **fields,
    }
    z.Operations.HVAC.Ventilation = VentilationComponent.model_validate(data)
    return z


def test_default_is_off():
    """Older definitions load without scheduled ventilation."""
    v = load_zone().Operations.HVAC.Ventilation
    assert v.IsScheduledVentilationOn is False
    assert v.ScheduledVentilationAch == 0
    assert v.ScheduledVentilationSchedule is None
    assert v.ScheduledVentilationSetpoint is None


def test_temperature_schedule_refused():
    """The schedule multiplies a flow."""
    temp = year("t", week("t", day("t", [20.0] * 24, "Temperature")), "Setpoint")
    with pytest.raises(ValidationError, match="ScheduledVentilationSchedule"):
        _scheduled(ScheduledVentilationSchedule=temp.model_dump())


@needs_eplus
def test_build_writes_design_flow_rate(tmp_path: Path):
    """The builder writes a natural ZoneVentilation:DesignFlowRate."""
    zone = _scheduled(
        ScheduledVentilationSchedule=_night_schedule().model_dump(),
        ScheduledVentilationSetpoint=18.0,
    )
    doc = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path))
    (vent,) = doc["ZoneVentilation:DesignFlowRate"]
    assert vent.air_changes_per_hour == 2.0
    assert vent.schedule_name == "night_flush"
    assert vent.minimum_indoor_temperature == 18.0
    off = small_model(load_zone()).build(
        SimulationPathConfig(output_dir=tmp_path / "o")
    )
    assert len(off["ZoneVentilation:DesignFlowRate"]) == 0


def _flow(zone: ZoneComponent, tmp_path: Path):
    def request(doc: EPDocument) -> EPDocument:
        doc["Output:Variable"].add(
            key_value="*", variable_name=FLOW, reporting_frequency="Hourly"
        )
        return doc

    result = small_model(zone).run(
        eplus_parent_dir=tmp_path, post_geometry_callback=request
    )
    try:
        return timeseries_frame(result.sql, FLOW, "Hourly").iloc[:, 0]
    finally:
        result.sql.close()


@needs_eplus
def test_simulated_flow_follows_schedule(tmp_path: Path):
    """The flow is ACH x volume at night and zero by day; a high setpoint stops it."""
    model = small_model(load_zone())
    volume = model.geometry.w * model.geometry.d * model.geometry.h
    flow = _flow(
        _scheduled(ScheduledVentilationSchedule=_night_schedule().model_dump()),
        tmp_path / "a",
    )
    hours = np.asarray(flow.index.hour)
    night = (hours < 6) | (hours >= 18)
    assert np.all(flow.to_numpy()[~night] == 0)
    assert flow.to_numpy()[night].mean() == pytest.approx(2.0 * volume / 3600, rel=0.1)
    stopped = _flow(_scheduled(ScheduledVentilationSetpoint=99.0), tmp_path / "b")
    assert np.all(stopped.to_numpy() == 0)
