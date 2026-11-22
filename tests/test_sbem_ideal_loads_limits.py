"""Ideal-loads limits (UP-9)."""

from pathlib import Path

import numpy as np
import pytest

from epinterface.document import EPDocument
from epinterface.results import timeseries_frame
from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.systems import ConditioningSystemsComponent
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import load_zone, small_model

HEATING = "Zone Ideal Loads Supply Air Sensible Heating Rate"
AREA = 12 * 8  # floor area of small_model's single zone [m2]

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _limited(**fields) -> ZoneComponent:
    z = load_zone()
    data = {**z.Operations.HVAC.ConditioningSystems.model_dump(), **fields}
    z.Operations.HVAC.ConditioningSystems = ConditioningSystemsComponent.model_validate(
        data
    )
    return z


def test_defaults_autosize():
    """Older definitions keep autosized flow and capacity limits."""
    c = load_zone().Operations.HVAC.ConditioningSystems
    assert (c.HeatingLimitType, c.CoolingLimitType) == (
        "LimitFlowRateAndCapacity",
        "LimitFlowRateAndCapacity",
    )
    assert c.MaxHeatingFlowPerFloorArea is None
    assert c.MaxCoolingCapacityPerFloorArea is None


@needs_eplus
def test_build_scales_limits_by_area(tmp_path: Path):
    """Limits per floor area become the zone's limits."""
    zone = _limited(
        HeatingLimitType="LimitCapacity",
        CoolingLimitType="NoLimit",
        MaxHeatingCapacityPerFloorArea=10.0,
        MaxCoolingFlowPerFloorArea=0.01,
    )
    doc = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path))
    (ideal,) = doc["HVACTemplate:Zone:IdealLoadsAirSystem"]
    assert ideal.heating_limit == "LimitCapacity"
    assert ideal.cooling_limit == "NoLimit"
    assert ideal.maximum_sensible_heating_capacity == pytest.approx(10.0 * AREA)
    assert ideal.maximum_cooling_air_flow_rate == pytest.approx(0.01 * AREA)
    assert str(ideal.maximum_heating_air_flow_rate).lower() == "autosize"


@needs_eplus
def test_simulated_heating_capped(tmp_path: Path):
    """The ideal loads never heat above the capacity limit."""

    def request(doc: EPDocument) -> EPDocument:
        doc["Output:Variable"].add(
            key_value="*", variable_name=HEATING, reporting_frequency="Hourly"
        )
        return doc

    def peak(zone: ZoneComponent, out: Path) -> float:
        result = small_model(zone).run(
            eplus_parent_dir=out, post_geometry_callback=request
        )
        try:
            return float(
                np.nanmax(timeseries_frame(result.sql, HEATING, "Hourly").to_numpy())
            )
        finally:
            result.sql.close()

    free = peak(load_zone(), tmp_path / "free")
    cap = 5.0
    capped = peak(
        _limited(HeatingLimitType="LimitCapacity", MaxHeatingCapacityPerFloorArea=cap),
        tmp_path / "capped",
    )
    assert free > cap * AREA
    assert capped <= cap * AREA * 1.001
