"""Window settings: operable area and shading (UP-9)."""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from epinterface.document import EPDocument
from epinterface.results import timeseries_frame
from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.envelope import WindowSettingsComponent
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import day, load_zone, small_model, week, year

SOLAR = "Surface Window Transmitted Solar Radiation Rate"

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _with_settings(**fields) -> ZoneComponent:
    z = load_zone()
    z.Envelope.WindowSettings = WindowSettingsComponent(Name="settings", **fields)
    return z


def _natural(zone: ZoneComponent) -> ZoneComponent:
    zone.Operations.HVAC.Ventilation.Provider = "Natural"
    zone.Operations.HVAC.Ventilation.HRV = "NoHRV"
    return zone


def test_default_is_unset():
    """Older definitions load without window settings."""
    assert load_zone().Envelope.WindowSettings is None
    s = WindowSettingsComponent(Name="s")
    assert (s.OperableArea, s.IsShadingSystemOn) == (1.0, False)


def test_temperature_availability_refused():
    """Shading availability is on or off."""
    temp = year("t", week("t", day("t", [20.0] * 24, "Temperature")), "Setpoint")
    with pytest.raises(ValidationError, match="ShadingSystemAvailabilitySchedule"):
        WindowSettingsComponent(Name="s", ShadingSystemAvailabilitySchedule=temp)


@needs_eplus
def test_build_scales_opening_area(tmp_path: Path):
    """Natural ventilation opens only the operable part of the windows."""
    full = small_model(_natural(load_zone())).build(
        SimulationPathConfig(output_dir=tmp_path / "f")
    )
    half = small_model(_natural(_with_settings(OperableArea=0.5))).build(
        SimulationPathConfig(output_dir=tmp_path / "h")
    )
    (a,) = full["ZoneVentilation:WindandStackOpenArea"]
    (b,) = half["ZoneVentilation:WindandStackOpenArea"]
    assert b.opening_area == pytest.approx(0.5 * a.opening_area)
    closed = small_model(_natural(_with_settings(OperableArea=0.0))).build(
        SimulationPathConfig(output_dir=tmp_path / "c")
    )
    assert len(closed["ZoneVentilation:WindandStackOpenArea"]) == 0


@needs_eplus
def test_build_writes_shading_control(tmp_path: Path):
    """A shading system writes a shade and a control over the zone's windows."""
    avail = year("shade_avail", week("sw", day("sd", [1.0] * 24)), "Window")
    zone = _with_settings(
        IsShadingSystemOn=True,
        ShadingSystemType="InteriorShade",
        ShadingSystemSetpoint=150.0,
        ShadingSystemTransmittance=0.2,
        ShadingSystemAvailabilitySchedule=avail,
    )
    doc = small_model(zone).build(SimulationPathConfig(output_dir=tmp_path))
    (shade,) = doc["WindowMaterial:Shade"]
    assert shade.solar_transmittance == 0.2
    assert shade.solar_reflectance == pytest.approx(0.4)
    (control,) = doc["WindowShadingControl"]
    assert control.shading_type == "InteriorShade"
    assert control.setpoint == 150.0
    assert control.schedule_name == "shade_avail"
    assert control.shading_control_is_scheduled == "Yes"
    names = {f.fenestration_surface_name for f in control.fenestration_surfaces}
    assert names == {w.name for w in doc["FenestrationSurface:Detailed"]}


@needs_eplus
def test_simulated_shading_cuts_solar_gains(tmp_path: Path):
    """An exterior shade lowers the solar radiation transmitted by the windows."""

    def request(doc: EPDocument) -> EPDocument:
        doc["Output:Variable"].add(
            key_value="*", variable_name=SOLAR, reporting_frequency="Hourly"
        )
        return doc

    def solar(zone: ZoneComponent, out: Path) -> float:
        result = small_model(zone).run(
            eplus_parent_dir=out, post_geometry_callback=request
        )
        try:
            return float(
                np.nansum(timeseries_frame(result.sql, SOLAR, "Hourly").to_numpy())
            )
        finally:
            result.sql.close()

    plain = solar(load_zone(), tmp_path / "p")
    shaded = solar(
        _with_settings(
            IsShadingSystemOn=True,
            ShadingSystemSetpoint=50.0,
            ShadingSystemTransmittance=0.1,
        ),
        tmp_path / "s",
    )
    assert 0 < shaded < 0.8 * plain
