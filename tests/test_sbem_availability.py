"""Heating and cooling availability schedules (UP-9)."""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from epinterface.document import EPDocument
from epinterface.results import timeseries_frame
from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.systems import ConditioningSystemsComponent
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import MONTHS, day, load_zone, small_model, week

HEATING = "Zone Ideal Loads Supply Air Sensible Heating Rate"

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _winter_off_in_january():
    """Heating off in January, on otherwise."""
    from epinterface.sbem.components.schedules import YearComponent

    on = week("avail_on", day("avail_on_d", [1.0] * 24))
    off = week("avail_off", day("avail_off_d", [0.0] * 24))
    return YearComponent(
        Name="heating_avail",
        Type="Setpoint",
        **{m: (off if m == "January" else on) for m in MONTHS},
    )


def _available(**fields) -> ZoneComponent:
    z = load_zone()
    data = {**z.Operations.HVAC.ConditioningSystems.model_dump(), **fields}
    z.Operations.HVAC.ConditioningSystems = ConditioningSystemsComponent.model_validate(
        data
    )
    return z


def test_defaults_always_available():
    """Older definitions load without availability schedules."""
    c = load_zone().Operations.HVAC.ConditioningSystems
    assert c.HeatingAvailabilitySchedule is None
    assert c.CoolingAvailabilitySchedule is None


def test_fraction_required():
    """An availability schedule is on or off."""
    from tests.sbem_helpers import year

    temp = year("t", week("t", day("t", [20.0] * 24, "Temperature")), "Setpoint")
    with pytest.raises(ValidationError, match="CoolingAvailabilitySchedule"):
        _available(CoolingAvailabilitySchedule=temp.model_dump())


@needs_eplus
def test_build_writes_schedule(tmp_path: Path):
    """The ideal loads' heating availability is the schedule."""
    zone = _available(HeatingAvailabilitySchedule=_winter_off_in_january().model_dump())
    doc = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path))
    (ideal,) = doc["HVACTemplate:Zone:IdealLoadsAirSystem"]
    assert ideal.heating_availability_schedule_name == "heating_avail"
    assert ideal.cooling_availability_schedule_name in (None, "")


@needs_eplus
def test_simulated_no_heating_when_unavailable(tmp_path: Path):
    """No heating in January when the schedule says so; heating in February."""

    def request(doc: EPDocument) -> EPDocument:
        doc["Output:Variable"].add(
            key_value="*", variable_name=HEATING, reporting_frequency="Hourly"
        )
        return doc

    zone = _available(HeatingAvailabilitySchedule=_winter_off_in_january().model_dump())
    result = small_model(zone).run(
        eplus_parent_dir=tmp_path, post_geometry_callback=request
    )
    try:
        heat = timeseries_frame(result.sql, HEATING, "Hourly").iloc[:, 0]
    finally:
        result.sql.close()
    months = np.asarray(heat.index.month)
    assert np.all(heat.to_numpy()[months == 1] == 0)
    assert heat.to_numpy()[months == 2].sum() > 0
