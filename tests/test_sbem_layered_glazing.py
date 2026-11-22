"""Layered glazing constructions (UP-9)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from epinterface.sbem.builder import SimulationPathConfig
from epinterface.sbem.components.envelope import (
    GasLayerComponent,
    GasMaterialComponent,
    GlazingConstructionLayeredComponent,
    GlazingConstructionSimpleComponent,
    GlazingLayerComponent,
    GlazingMaterialComponent,
    ZoneEnvelopeComponent,
)
from epinterface.sbem.components.zones import ZoneComponent
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import load_zone, small_model

needs_eplus = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)

# EnergyPlus's dataset values of 3 mm clear glass
CLEAR = GlazingMaterialComponent(
    Name="Clear",
    Conductivity=0.9,
    SolarTransmittance=0.837,
    SolarReflectanceFront=0.075,
    SolarReflectanceBack=0.075,
    VisibleTransmittance=0.898,
    VisibleReflectanceFront=0.081,
    VisibleReflectanceBack=0.081,
    IRTransmittance=0.0,
    IREmissivityFront=0.84,
    IREmissivityBack=0.84,
)
ARGON = GasMaterialComponent(Name="ArgonFill", GasType="Argon")


def pane() -> GlazingLayerComponent:
    """A 3 mm clear pane."""
    return GlazingLayerComponent(Thickness=0.003, GlazingMaterial=CLEAR)


def cavity() -> GasLayerComponent:
    """A 13 mm argon cavity."""
    return GasLayerComponent(Thickness=0.013, GasMaterial=ARGON)


def double() -> GlazingConstructionLayeredComponent:
    """A double clear window with argon."""
    return GlazingConstructionLayeredComponent(
        Name="DoubleClearArgon", Layers=[pane(), cavity(), pane()]
    )


def _with_window(window) -> ZoneComponent:
    z = load_zone()
    z.Envelope.Window = window
    return z


def test_simple_still_loads():
    """An envelope with simple glazing reads as simple glazing."""
    assert isinstance(load_zone().Envelope.Window, GlazingConstructionSimpleComponent)


def test_layered_round_trips_through_json():
    """A layered window survives the envelope's JSON."""
    env = load_zone().Envelope.model_copy(update={"Window": double()})
    back = ZoneEnvelopeComponent.model_validate_json(env.model_dump_json())
    assert isinstance(back.Window, GlazingConstructionLayeredComponent)
    assert back.Window == double()
    assert back.Window.pane_count == 2


@pytest.mark.parametrize(
    "layers",
    [
        [],
        [cavity()],
        [pane(), cavity()],
        [pane(), pane()],
        [pane(), cavity()] * 4 + [pane()],
    ],
)
def test_invalid_layer_sequences(layers):
    """Panes and gases alternate, panes outermost, at most four panes."""
    with pytest.raises(ValidationError):
        GlazingConstructionLayeredComponent(Name="bad", Layers=layers)


@needs_eplus
def test_build_writes_layers(tmp_path: Path):
    """The windows get a construction of glazing and gas materials."""
    doc = small_model(_with_window(double())).build(
        SimulationPathConfig(output_dir=tmp_path)
    )
    construction = doc["Construction"]["DoubleClearArgon"]
    assert construction.outside_layer == "Clear_0.003m"
    assert construction.layer_2 == "ArgonFill_0.013m"
    assert construction.layer_3 == "Clear_0.003m"
    glass = doc["WindowMaterial:Glazing"]["Clear_0.003m"]
    assert glass.solar_transmittance_at_normal_incidence == 0.837
    assert doc["WindowMaterial:Gas"]["ArgonFill_0.013m"].gas_type == "Argon"
    for window in doc["FenestrationSurface:Detailed"]:
        assert window.construction_name == "DoubleClearArgon"


@needs_eplus
def test_simulated_double_glazing_saves_heating(tmp_path: Path):
    """A double pane needs less heating than a single one."""
    single = GlazingConstructionLayeredComponent(Name="SingleClear", Layers=[pane()])
    one = small_model(_with_window(single)).run(eplus_parent_dir=tmp_path / "1")
    two = small_model(_with_window(double())).run(eplus_parent_dir=tmp_path / "2")
    try:
        heat_one = one.energy_and_peak.loc["Energy"]["Raw"]["Heating"].sum()
        heat_two = two.energy_and_peak.loc["Energy"]["Raw"]["Heating"].sum()
    finally:
        one.sql.close()
        two.sql.close()
    assert heat_two < heat_one
