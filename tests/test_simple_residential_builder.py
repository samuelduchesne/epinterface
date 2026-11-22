"""Smoke test for the legacy simple residential shoebox builder."""

import pytest
from idfkit.simulation import find_energyplus, simulate

from epinterface.builder import SimpleResidentialModel
from epinterface.data import DefaultEPWZipPath
from epinterface.settings import energyplus_settings


@pytest.mark.skipif(
    energyplus_settings.energyplus_version != "25.2.0",
    reason="simulation checked against EnergyPlus 25.2.0",
)
def test_simple_residential_model_builds_and_simulates(tmp_path):
    """The built document simulates to completion with EnergyPlus."""
    model = SimpleResidentialModel(Weather=DefaultEPWZipPath)  # pyright: ignore [reportCallIssue]
    doc = model.build(tmp_path / "build", weather_cache_dir=tmp_path / "weather")
    epw_path, _ = model.fetch_weather(tmp_path / "weather")

    result = simulate(
        doc,
        weather=epw_path,
        output_dir=tmp_path / "run",
        energyplus=find_energyplus(version=energyplus_settings.version_tuple),
    )

    assert result.success, result.stderr
    err_text = "\n".join(f.read_text() for f in (tmp_path / "run").rglob("*.err"))
    assert "EnergyPlus Completed Successfully" in err_text
    assert result.sql is not None
