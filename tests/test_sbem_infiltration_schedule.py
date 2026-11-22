"""An infiltration schedule (UP-2)."""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from epinterface.document import EPDocument
from epinterface.results import timeseries_frame
from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.envelope import InfiltrationComponent
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import day, load_zone, small_model, week, year

INFILTRATION_FLOW = "Zone Infiltration Standard Density Volume Flow Rate"
# no infiltration in the morning, full infiltration in the afternoon
HALF_DAY = [0.0] * 12 + [1.0] * 12


@pytest.fixture(scope="module")
def zone() -> ZoneComponent:
    """The seed's default zone definition."""
    return load_zone()


def _scheduled(zone: ZoneComponent) -> ZoneComponent:
    z = zone.model_copy(deep=True)
    half = day("half_day", HALF_DAY)
    z.Envelope.Infiltration.Schedule = year(
        "infiltration_half_day", week("half_week", half), "Infiltration"
    )
    return z


def test_default_is_unscheduled(zone: ZoneComponent):
    """Older definitions load without a schedule."""
    assert zone.Envelope.Infiltration.Schedule is None


def test_temperature_schedule_refused(zone: ZoneComponent):
    """An infiltration schedule is a multiplier."""
    temp = year("t", week("t", day("t", [20.0] * 24, "Temperature")), "Setpoint")
    data = zone.Envelope.Infiltration.model_dump()
    with pytest.raises(ValidationError, match="infiltration schedule"):
        InfiltrationComponent.model_validate({**data, "Schedule": temp.model_dump()})


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)
def test_build_uses_schedule(zone: ZoneComponent, tmp_path: Path):
    """The infiltration object follows the archetype's schedule."""
    doc = small_model(_scheduled(zone)).build(SimulationPathConfig(output_dir=tmp_path))
    (infiltration,) = doc["ZoneInfiltration:DesignFlowRate"]
    assert infiltration.schedule_name == "infiltration_half_day"
    assert "infiltration_half_day" in doc["Schedule:Year"]

    plain = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path / "p"))
    (infiltration,) = plain["ZoneInfiltration:DesignFlowRate"]
    assert infiltration.schedule_name.endswith("_INFILTRATION_Schedule")


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="simulating needs EnergyPlus",
)
def test_simulated_infiltration_follows_schedule(zone: ZoneComponent, tmp_path: Path):
    """EnergyPlus's infiltration flow is zero in the morning and on in the afternoon."""

    def request_flow(doc: EPDocument) -> EPDocument:
        doc["Output:Variable"].add(
            key_value="*", variable_name=INFILTRATION_FLOW, reporting_frequency="Hourly"
        )
        return doc

    model = small_model(_scheduled(zone))
    result = model.run(eplus_parent_dir=tmp_path, post_geometry_callback=request_flow)
    try:
        frame = timeseries_frame(result.sql, INFILTRATION_FLOW, "Hourly")
        flow = frame.iloc[:, 0]
        hours = np.asarray(flow.index.hour)
        assert np.all(flow.to_numpy()[hours < 12] == 0)
        afternoon = flow.to_numpy()[hours >= 12]
        volume = model.geometry.w * model.geometry.d * model.geometry.h
        ach = zone.Envelope.Infiltration.AirChangesPerHour
        # standard density, so within a few percent of ACH x volume
        assert afternoon.mean() == pytest.approx(ach * volume / 3600, rel=0.1)
    finally:
        result.sql.close()
