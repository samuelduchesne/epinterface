"""Provider "Both" gives natural and mechanical ventilation (UP-9)."""

from pathlib import Path

import numpy as np
import pytest

from epinterface.document import EPDocument
from epinterface.results import timeseries_frame
from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import load_zone, small_model

NATURAL_FLOW = "Zone Ventilation Standard Density Volume Flow Rate"
MECHANICAL_FLOW = "Zone Mechanical Ventilation Standard Density Volume Flow Rate"

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _with_provider(provider: str) -> ZoneComponent:
    z = load_zone()
    z.Operations.HVAC.Ventilation.Provider = provider  # type: ignore[assignment]
    if provider == "Natural":
        z.Operations.HVAC.Ventilation.HRV = "NoHRV"
    return z


@needs_eplus
@pytest.mark.parametrize(
    ("provider", "natural", "mechanical"),
    [("Mechanical", False, True), ("Natural", True, False), ("Both", True, True)],
)
def test_build_writes_each_provider(
    provider: str, natural: bool, mechanical: bool, tmp_path: Path
):
    """Both writes the wind-and-stack ventilation and the ideal loads' outdoor air."""
    doc = small_model(_with_provider(provider)).build(
        SimulationPathConfig(output_dir=tmp_path)
    )
    assert bool(len(doc["ZoneVentilation:WindandStackOpenArea"])) is natural
    (ideal,) = doc["HVACTemplate:Zone:IdealLoadsAirSystem"]
    assert (ideal.outdoor_air_method == "Sum") is mechanical


def _request(doc: EPDocument) -> EPDocument:
    for name in (NATURAL_FLOW, MECHANICAL_FLOW):
        doc["Output:Variable"].add(
            key_value="*", variable_name=name, reporting_frequency="Hourly"
        )
    return doc


@needs_eplus
def test_simulated_both_ventilates_both_ways(tmp_path: Path):
    """EnergyPlus reports natural and mechanical ventilation flows for Both."""
    result = small_model(_with_provider("Both")).run(
        eplus_parent_dir=tmp_path, post_geometry_callback=_request
    )
    try:
        natural = timeseries_frame(result.sql, NATURAL_FLOW, "Hourly")
        mechanical = timeseries_frame(result.sql, MECHANICAL_FLOW, "Hourly")
        assert np.nansum(natural.to_numpy()) > 0
        assert np.nansum(mechanical.to_numpy()) > 0
    finally:
        result.sql.close()
