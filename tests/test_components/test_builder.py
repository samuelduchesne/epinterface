"""Test the builder."""

import pytest
from idfkit import IDFObject, SimulationError
from idfkit.geometry import Vector3D, calculate_surface_area, get_surface_coords
from prisma import Prisma

from epinterface.data import DefaultEPWZipPath, EnergyPlusArtifactDir
from epinterface.ddy_injector_bayes import DDYSizingSpec
from epinterface.document import EPDocument, load_document
from epinterface.geometry import ShoeboxGeometry
from epinterface.sbem.builder import (
    AtticAssumptions,
    BasementAssumptions,
    Model,
    SimulationPathConfig,
)
from epinterface.sbem.flat_model import FlatModel
from epinterface.sbem.prisma.client import deep_fetcher
from epinterface.settings import energyplus_settings
from tests.conftest import SQLCleanupSpy


def _lower(value: str | None) -> str:
    assert value is not None
    return value.lower()


def _vertices(surface: IDFObject) -> list[Vector3D]:
    coords = get_surface_coords(surface)
    assert coords is not None
    return list(coords.vertices)


def _model(db: Prisma, **geometry) -> Model:
    _, zone = deep_fetcher.Zone.get_deep_object("default_zone", db)
    return Model(
        Weather=DefaultEPWZipPath,
        Zone=zone,
        Basement=BasementAssumptions(Conditioned=False, UseFraction=None),
        Attic=AtticAssumptions(Conditioned=False, UseFraction=None),
        geometry=ShoeboxGeometry(**{
            "x": 0,
            "y": 0,
            "w": 10,
            "d": 10,
            "h": 3,
            "wwr": 0.2,
            "num_stories": 2,
            "basement": False,
            "zoning": "by_storey",
            "roof_height": None,
            **geometry,
        }),
    )


def test_builder(preseeded_readonly_db: Prisma, sql_cleanup_spy: SQLCleanupSpy):
    """A model runs in a temp dir and returns its document, warnings and results.

    The results stay queryable after the temporary run directory is deleted,
    and no results file is left open in it at deletion (Windows refuses that).
    """
    r = _model(preseeded_readonly_db).run()
    assert sql_cleanup_spy.checked
    assert sql_cleanup_spy.still_open == []
    hourly = r.hourly_timeseries(["Zone Mean Air Temperature"])
    assert hourly.shape[0] == 8760
    assert hourly.shape[1] > 0
    assert r.doc.version == energyplus_settings.version_tuple
    assert "EnergyPlus Completed Successfully" in r.err_text


def test_simulation_failure_raises(preseeded_readonly_db: Prisma, tmp_path):
    """EnergyPlus failing (here: no Building object) raises SimulationError."""

    def break_model(doc: EPDocument) -> EPDocument:
        for building in list(doc["Building"]):
            doc.removeidfobject(building)
        return doc

    with pytest.raises(SimulationError):
        _model(preseeded_readonly_db).simulate(
            SimulationPathConfig(output_dir=tmp_path),
            post_geometry_callback=break_model,
        )


def test_exposed_basement_walls_are_split(preseeded_readonly_db: Prisma, tmp_path):
    """Basement walls split at the exposed height into a ground and an outdoor part."""
    model = _model(preseeded_readonly_db, basement=True, exposed_basement_frac=0.25)
    doc = model.build(SimulationPathConfig(output_dir=tmp_path))
    walls = [
        s for s in doc["BuildingSurface:Detailed"] if _lower(s.surface_type) == "wall"
    ]
    bottoms = [s for s in walls if s.name.endswith("_bottom")]
    tops = [s for s in walls if s.name.endswith("_top")]
    assert len(bottoms) == len(tops) == 4
    # the original ground walls are replaced by their bottom parts
    assert [
        s for s in walls if _lower(s.outside_boundary_condition) == "ground"
    ] == bottoms
    assert {_lower(s.outside_boundary_condition) for s in tops} == {"outdoors"}
    for bottom in bottoms:
        top = doc["BuildingSurface:Detailed"][
            bottom.name.removesuffix("_bottom") + "_top"
        ]
        bottom_zs = [v.z for v in _vertices(bottom)]
        top_zs = [v.z for v in _vertices(top)]
        assert max(bottom_zs) == pytest.approx(min(top_zs))
        assert max(top_zs) - min(bottom_zs) == pytest.approx(3)
        assert max(top_zs) - min(top_zs) == pytest.approx(0.75)
        assert calculate_surface_area(top) == pytest.approx(10 * 0.75)
        assert bottom.construction_name == top.construction_name


def test_inject_ddy_in_requested_order(doc: EPDocument):
    """The location and the requested sizing periods replace the document's own."""
    ddy = load_document(
        EnergyPlusArtifactDir / "USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.ddy",
        energyplus_settings.version_tuple,
    )
    DDYSizingSpec(
        match=False, conditions_types=["Winter Extreme", "Summer Extreme"]
    ).inject_ddy(doc, ddy)
    assert [o.name for o in doc["Site:Location"]] == [
        o.name for o in ddy["Site:Location"]
    ]
    periods = list(doc["SizingPeriod:WeatherFileConditionType"])
    assert [p.name for p in periods] == ["Winter Extreme", "Summer Extreme"]
    assert periods[0].period_selection == "WinterExtreme"
    assert len(doc["SizingPeriod:DesignDay"]) == 0


def test_flat_model_rotates_around_floor_plan_centre(doc: EPDocument):
    """The FlatModel callback rotates the building in place, like geomeppy did."""
    flat = FlatModel(**{**_FLAT_MODEL_KWARGS, "Rotation": 90})
    model, callback = flat.to_model()
    doc = model.geometry.add(doc)

    def footprint(d: EPDocument) -> tuple[float, float, float, float]:
        points = [
            v
            for s in d["BuildingSurface:Detailed"]
            if _lower(s.surface_type) == "floor"
            for v in _vertices(s)
        ]
        return (
            min(p.x for p in points),
            max(p.x for p in points),
            min(p.y for p in points),
            max(p.y for p in points),
        )

    x0, x1, y0, y1 = footprint(doc)
    doc = callback(doc)
    rx0, rx1, ry0, ry1 = footprint(doc)
    assert (rx0 + rx1) / 2 == pytest.approx((x0 + x1) / 2)
    assert (ry0 + ry1) / 2 == pytest.approx((y0 + y1) / 2)
    # a quarter turn swaps the footprint's width and depth
    assert rx1 - rx0 == pytest.approx(y1 - y0)
    assert ry1 - ry0 == pytest.approx(x1 - x0)


_FLAT_MODEL_KWARGS = {
    "F2FHeight": 3.25,
    "Width": 40,
    "Depth": 20,
    "Rotation": 0,
    "WWR": 0.3,
    "NFloors": 2,
    "FacadeRValue": 3.0,
    "RoofRValue": 3.0,
    "SlabRValue": 3.0,
    "WindowUValue": 3.0,
    "WindowSHGF": 0.7,
    "WindowTVis": 0.5,
    "InfiltrationACH": 0.5,
    "VentFlowRatePerArea": 0.001,
    "VentFlowRatePerPerson": 0.0085,
    "VentProvider": "Mechanical",
    "VentHRV": "NoHRV",
    "VentEconomizer": "NoEconomizer",
    "VentDCV": "NoDCV",
    "DHWFlowRatePerPerson": 0.010,
    "DHWFuel": "Electricity",
    "DHWSystemCOP": 1.0,
    "DHWDistributionCOP": 1.0,
    "EquipmentPowerDensity": 25,
    "LightingPowerDensity": 10,
    "OccupantDensity": 0.01,
    "EquipmentBase": 0.4,
    "EquipmentAMInterp": 0.5,
    "EquipmentLunchInterp": 0.8,
    "EquipmentPMInterp": 0.5,
    "EquipmentWeekendPeakInterp": 0.25,
    "EquipmentSummerPeakInterp": 0.5,
    "LightingBase": 0.3,
    "LightingAMInterp": 0.75,
    "LightingLunchInterp": 0.75,
    "LightingPMInterp": 0.9,
    "LightingWeekendPeakInterp": 0.75,
    "LightingSummerPeakInterp": 0.9,
    "OccupancyBase": 0.05,
    "OccupancyAMInterp": 0.25,
    "OccupancyLunchInterp": 0.9,
    "OccupancyPMInterp": 0.5,
    "OccupancyWeekendPeakInterp": 0.15,
    "OccupancySummerPeakInterp": 0.85,
    "HeatingSetpointBase": 21,
    "SetpointDeadband": 2,
    "HeatingSetpointSetback": 2,
    "CoolingSetpointSetback": 2,
    "NightSetback": 0.5,
    "WeekendSetback": 0.5,
    "SummerSetback": 0.5,
    "HeatingFuel": "Electricity",
    "CoolingFuel": "Electricity",
    "HeatingSystemCOP": 1.0,
    "CoolingSystemCOP": 1.0,
    "HeatingDistributionCOP": 1.0,
    "CoolingDistributionCOP": 1.0,
    "EPWURI": DefaultEPWZipPath,
}


def test_model_run_results_idf_is_a_deprecated_alias_of_doc():
    """`ModelRunResults.idf` still returns the document, with a warning."""
    import warnings

    from epinterface.document import minimal_document
    from epinterface.sbem.builder import ModelRunResults

    doc = minimal_document(energyplus_settings.version_tuple)
    results = ModelRunResults(
        doc=doc,
        sql=None,  # pyright: ignore[reportArgumentType]
        energy_and_peak=None,  # pyright: ignore[reportArgumentType]
        err_text="",
        output_dir=None,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert results.idf is doc
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
