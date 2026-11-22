"""A schedule for mechanical outdoor air (UP-9)."""

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

FLOW = "Zone Mechanical Ventilation Standard Density Volume Flow Rate"
OFFICE_HOURS = [0.0] * 8 + [1.0] * 10 + [0.0] * 6

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _schedule(kind="Fraction"):
    values = OFFICE_HOURS if kind == "Fraction" else [20.0] * 24
    return year(
        "office_oa", week("office_oa_w", day("office_oa_d", values, kind)), "Occupancy"
    )


def _with_schedule(**fields) -> ZoneComponent:
    z = load_zone()
    data = {**z.Operations.HVAC.Ventilation.model_dump(), **fields}
    z.Operations.HVAC.Ventilation = VentilationComponent.model_validate(data)
    return z


def test_default_is_unscheduled():
    """Older definitions load without a mechanical ventilation schedule."""
    assert load_zone().Operations.HVAC.Ventilation.MechVentSchedule is None


def test_fraction_required():
    """The schedule is a fraction of the design outdoor air."""
    with pytest.raises(ValidationError, match="MechVentSchedule"):
        _with_schedule(MechVentSchedule=_schedule("Temperature").model_dump())


@needs_eplus
def test_build_uses_detailed_specification(tmp_path: Path):
    """The ideal loads take a DesignSpecification:OutdoorAir with the schedule."""
    doc = small_model(_with_schedule(MechVentSchedule=_schedule().model_dump())).build(
        SimulationPathConfig(output_dir=tmp_path)
    )
    (ideal,) = doc["HVACTemplate:Zone:IdealLoadsAirSystem"]
    assert ideal.outdoor_air_method == "DetailedSpecification"
    (spec,) = doc["DesignSpecification:OutdoorAir"]
    assert ideal.design_specification_outdoor_air_object_name == spec.name
    assert spec.outdoor_air_schedule_name == "office_oa"
    assert spec.outdoor_air_flow_per_person == 0.006


@needs_eplus
def test_simulated_outdoor_air_follows_schedule(tmp_path: Path):
    """The ideal loads bring no outdoor air outside the scheduled hours."""

    def request(doc: EPDocument) -> EPDocument:
        doc["Output:Variable"].add(
            key_value="*", variable_name=FLOW, reporting_frequency="Hourly"
        )
        return doc

    zone = _with_schedule(MechVentSchedule=_schedule().model_dump())
    result = small_model(zone).run(
        eplus_parent_dir=tmp_path, post_geometry_callback=request
    )
    try:
        flow = timeseries_frame(result.sql, FLOW, "Hourly").iloc[:, 0]
    finally:
        result.sql.close()
    hours = np.asarray(flow.index.hour)
    on = (hours >= 8) & (hours < 18)
    assert np.all(flow.to_numpy()[~on] == pytest.approx(0, abs=1e-9))
    assert flow.to_numpy()[on].mean() > 0
