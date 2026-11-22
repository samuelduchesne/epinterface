"""SBEM energy beyond a constant COP (UP-8).

Specific fan power, the ideal loads' supply-air temperature limits and an energy
input ratio linear in outdoor temperature: component validation, the built model
and a simulation checking the post-processed end uses against the raw outputs.
"""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from epinterface.data import DefaultEPWZipPath
from epinterface.geometry import ShoeboxGeometry
from epinterface.results import timeseries_frame
from epinterface.sbem.archetype import Archetype, ZoneGroup
from epinterface.sbem.builder import (
    OUTDOOR_TEMPERATURE_VARIABLE,
    SUPPLY_AIR_VOLUME_VARIABLE,
    Model,
    SimulationPathConfig,
)
from epinterface.sbem.components.systems import (
    ConditioningSystemsComponent,
    ThermalSystemComponent,
)
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings

ZONE_PATH = Path(__file__).parent / "data" / "sbem_zone.json"
SFP = 1500.0  # W/(m3/s)
HEAT_SLOPE = -0.02  # 1/K: a heat pump's EIR rises as it gets colder
HEAT_REFERENCE = 5.0  # degC


@pytest.fixture(scope="module")
def zone() -> ZoneComponent:
    """The seed's default zone definition."""
    return ZoneComponent.model_validate_json(ZONE_PATH.read_text())


def _upgraded(zone: ZoneComponent) -> ZoneComponent:
    upgraded = zone.model_copy(deep=True)
    systems = upgraded.Operations.HVAC.ConditioningSystems
    systems.SpecificFanPower = SFP
    systems.MaximumHeatingSupplyAirTemperature = 40.0
    systems.MinimumCoolingSupplyAirTemperature = 14.0
    assert systems.Heating is not None
    systems.Heating = systems.Heating.model_copy(
        update={
            "SystemCOP": 3.0,
            "DistributionCOP": 0.9,
            "Fuel": "Electricity",
            "EIRTemperatureSlope": HEAT_SLOPE,
            "EIRReferenceTemperature": HEAT_REFERENCE,
        }
    )
    return upgraded


def _model(zone: ZoneComponent) -> Model:
    geometry = ShoeboxGeometry(
        x=0,
        y=0,
        w=12,
        d=8,
        h=3,
        wwr=0.3,
        num_stories=1,
        zoning="by_storey",
        roof_height=None,
    )
    archetype = Archetype(Name="up8", Groups=[ZoneGroup(Name="all", Zone=zone)])
    return Model.from_archetype(archetype, geometry, Weather=DefaultEPWZipPath)


# --- components --------------------------------------------------------------


def test_defaults_are_backward_compatible(zone: ZoneComponent):
    """Older definitions load: no fan, constant COP, the former supply limits."""
    systems = zone.Operations.HVAC.ConditioningSystems
    assert systems.SpecificFanPower is None
    assert systems.MaximumHeatingSupplyAirTemperature == 30.0
    assert systems.MinimumCoolingSupplyAirTemperature == 13.0
    assert systems.Heating is not None
    assert systems.Heating.EIRTemperatureSlope == 0.0
    assert systems.Heating.EIRReferenceTemperature is None
    assert np.allclose(
        systems.Heating.energy_input_ratio(np.array([-10.0, 30.0])),
        1 / systems.Heating.effective_system_cop,
    )


def test_energy_input_ratio_is_linear_and_clipped():
    """EIR = max(0, 1/SystemCOP + slope (T - Tref)) / DistributionCOP."""
    system = ThermalSystemComponent(
        Name="hp",
        ConditioningType="Heating",
        Fuel="Electricity",
        SystemCOP=4.0,
        DistributionCOP=0.8,
        EIRTemperatureSlope=-0.01,
        EIRReferenceTemperature=7.0,
    )
    t = np.array([7.0, -3.0, 100.0])
    expected = np.array([0.25, 0.35, 0.0]) / 0.8
    assert np.allclose(system.energy_input_ratio(t), expected)


def test_slope_needs_reference():
    """A sloped energy input ratio without a reference temperature is refused."""
    with pytest.raises(ValidationError, match="EIRReferenceTemperature"):
        ThermalSystemComponent(
            Name="hp",
            ConditioningType="Heating",
            Fuel="Electricity",
            SystemCOP=4.0,
            DistributionCOP=1.0,
            EIRTemperatureSlope=0.01,
        )


def test_supply_temperatures_ordered():
    """The heating supply limit must be above the cooling one."""
    with pytest.raises(ValidationError, match="MaximumHeatingSupplyAirTemperature"):
        ConditioningSystemsComponent(
            Name="c",
            Heating=None,
            Cooling=None,
            MaximumHeatingSupplyAirTemperature=12.0,
            MinimumCoolingSupplyAirTemperature=13.0,
        )


def test_negative_fan_power_refused():
    """A specific fan power is not negative."""
    with pytest.raises(ValidationError):
        ConditioningSystemsComponent(
            Name="c", Heating=None, Cooling=None, SpecificFanPower=-1
        )


# --- built model ---------------------------------------------------------------


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version (EPINTERFACE_ENERGYPLUS_VERSION)",
)
def test_build_writes_supply_limits_and_volume_output(
    zone: ZoneComponent, tmp_path: Path
):
    """The ideal loads take the supply limits; the supply volume is requested."""
    doc = _model(_upgraded(zone)).build(SimulationPathConfig(output_dir=tmp_path))
    (template,) = doc["HVACTemplate:Zone:IdealLoadsAirSystem"]
    assert template.maximum_heating_supply_air_temperature == 40.0
    assert template.minimum_cooling_supply_air_temperature == 14.0
    variables = {v.variable_name for v in doc["Output:Variable"]}
    assert SUPPLY_AIR_VOLUME_VARIABLE in variables

    plain = _model(zone).build(SimulationPathConfig(output_dir=tmp_path / "plain"))
    (template,) = plain["HVACTemplate:Zone:IdealLoadsAirSystem"]
    assert template.maximum_heating_supply_air_temperature == 30.0
    assert template.minimum_cooling_supply_air_temperature == 13.0
    variables = {v.variable_name for v in plain["Output:Variable"]}
    assert SUPPLY_AIR_VOLUME_VARIABLE not in variables


# --- simulation ------------------------------------------------------------------


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="simulating needs EnergyPlus",
)
def test_simulated_fan_and_heating_use(zone: ZoneComponent, tmp_path: Path):
    """Fans = SFP x supply volume; heating use = delivered x hourly EIR."""
    model = _model(_upgraded(zone))
    result = model.run(eplus_parent_dir=tmp_path)
    try:
        assert "** Severe  **" not in result.err_text
        energy = result.energy_and_peak.loc["Energy"]
        area = model.total_conditioned_area

        volume = timeseries_frame(result.sql, SUPPLY_AIR_VOLUME_VARIABLE, "Hourly")
        assert volume.shape[1] == 1
        assert volume.to_numpy().sum() > 0
        expected_fans = volume.to_numpy().sum() * SFP / 1000 / area
        fans = energy.loc["End Uses"].loc["Fans"].sum()
        assert fans == pytest.approx(expected_fans, rel=1e-9)

        raw = result.hourly_timeseries(["Heating:DistrictHeatingWater"])
        delivered = raw.iloc[:, 0].to_numpy() / 3.6e6 / area  # J -> kWh/m2
        t_out = (
            timeseries_frame(result.sql, OUTDOOR_TEMPERATURE_VARIABLE, "Hourly")
            .iloc[:, 0]
            .to_numpy()
        )
        eir = np.maximum(1 / 3.0 + HEAT_SLOPE * (t_out - HEAT_REFERENCE), 0) / 0.9
        heating = energy.loc["End Uses"].loc["Heating"].sum()
        assert heating == pytest.approx((delivered * eir).sum(), rel=1e-3)
        # colder hours weigh more than a constant COP at the reference would say
        assert heating > delivered.sum() / (3.0 * 0.9)

        utilities = energy.loc["Utilities"]
        end_uses = energy.loc["End Uses"]
        assert utilities.sum() == pytest.approx(end_uses.sum(), rel=1e-9)
        # heating, cooling and fans are all electric here
        electric = (
            end_uses.loc[["Lighting", "Equipment", "Heating", "Cooling", "Fans"]].sum()
        )
        assert utilities.loc["Electricity"].sum() == pytest.approx(electric, rel=1e-9)
        assert result.energy_and_peak.loc["Peak"].loc["Utilities"].loc[
            "Electricity"
        ].max() > 0
    finally:
        result.sql.close()
