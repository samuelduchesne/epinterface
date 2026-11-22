"""Window-to-wall ratios by orientation, honoured by the builder (UP-2)."""

import math
from pathlib import Path

import pytest
from idfkit.geometry import calculate_surface_area, calculate_surface_azimuth
from pydantic import ValidationError

from epinterface.data import DefaultEPWZipPath
from epinterface.document import EPDocument, minimal_document
from epinterface.geometry import ORIENTATIONS, ShoeboxGeometry, orientation_of
from epinterface.sbem.archetype import Archetype, BuildingGeometry, ZoneGroup
from epinterface.sbem.builder import Model
from epinterface.settings import energyplus_settings
from tests.sbem_helpers import load_zone

RATIOS = {
    "N": 0.1,
    "NE": 0.9,
    "E": 0.2,
    "SE": 0.9,
    "S": 0.5,
    "SW": 0.9,
    "W": 0.0,
    "NW": 0.9,
}

needs_version = pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="building needs an EnergyPlus version",
)


def _geometry(**kwargs) -> ShoeboxGeometry:
    return ShoeboxGeometry(**{
        "x": 0,
        "y": 0,
        "w": 12,
        "d": 8,
        "h": 3,
        "wwr": 0.3,
        "num_stories": 2,
        "zoning": "core/perim",
        **kwargs,
    })


def _ratios_by_orientation(doc: EPDocument) -> dict[str, float]:
    """Window area / gross wall area of each orientation's exterior walls."""
    walls = {
        w.name: w
        for w in doc["BuildingSurface:Detailed"]
        if (w.surface_type or "").lower() == "wall"
        and (w.outside_boundary_condition or "").lower() == "outdoors"
    }
    wall_area: dict[str, float] = {}
    window_area: dict[str, float] = {}
    for wall in walls.values():
        o = orientation_of(calculate_surface_azimuth(wall))
        wall_area[o] = wall_area.get(o, 0.0) + calculate_surface_area(wall)
    for window in doc["FenestrationSurface:Detailed"]:
        o = orientation_of(
            calculate_surface_azimuth(walls[window.building_surface_name])
        )
        window_area[o] = window_area.get(o, 0.0) + calculate_surface_area(window)
    return {o: window_area.get(o, 0.0) / a for o, a in wall_area.items()}


def test_wwr_by_orientation_validation():
    """Every orientation, ratios in [0, 1], stored in canonical order."""
    with pytest.raises(ValidationError, match="missing"):
        _geometry(wwr_by_orientation={"N": 0.2})
    with pytest.raises(ValidationError, match=r"\[0, 1\]"):
        _geometry(wwr_by_orientation=dict.fromkeys(ORIENTATIONS, 1.5))
    g = _geometry(wwr_by_orientation=dict(reversed(list(RATIOS.items()))))
    assert g.wwr_by_orientation is not None
    assert list(g.wwr_by_orientation) == list(ORIENTATIONS)
    assert g.window_to_wall_ratio(180) == 0.5
    assert g.window_to_wall_ratio(271) == 0.0
    assert _geometry().window_to_wall_ratio(180) == 0.3


@needs_version
def test_shoebox_windows_follow_orientation():
    """Each facade's window area is its orientation's ratio (0.999 ribbon width)."""
    doc = _geometry(wwr_by_orientation=RATIOS).add(
        minimal_document(energyplus_settings.version_tuple)
    )
    measured = _ratios_by_orientation(doc)
    assert set(measured) == {"N", "E", "S", "W"}
    for o, ratio in measured.items():
        assert ratio == pytest.approx(RATIOS[o] * 0.999, rel=1e-6)


@needs_version
def test_rotated_scene_uses_final_orientation():
    """With a scene rotated by 90 degrees, the ratios follow the final azimuths."""
    shapely = pytest.importorskip("shapely")
    from epinterface.geometry import SceneContext

    # a 12 x 8 rectangle whose long edge runs north-south
    building = shapely.Polygon([(-4, -6), (4, -6), (4, 6), (-4, 6)])
    scene = SceneContext(
        building=building,
        neighbors=[],
        neighbor_heights=[],
        orientation=math.pi / 2,
    )
    doc = _geometry(
        zoning="by_storey", wwr_by_orientation=RATIOS, scene_context=scene
    ).add(minimal_document(energyplus_settings.version_tuple))
    measured = _ratios_by_orientation(doc)
    assert set(measured) == {"N", "E", "S", "W"}
    for o, ratio in measured.items():
        assert ratio == pytest.approx(RATIOS[o] * 0.999, rel=1e-6)


def test_from_archetype_applies_window_ratios():
    """The archetype's ratios by orientation replace the geometry's window ratio."""
    zone = load_zone()
    archetype = Archetype(
        Name="a",
        Groups=[ZoneGroup(Name="g", Zone=zone)],
        Geometry=BuildingGeometry(WindowToWallRatio=RATIOS),
    )
    m = Model.from_archetype(archetype, _geometry(), Weather=DefaultEPWZipPath)
    assert m.geometry.wwr_by_orientation == RATIOS
    plain = Archetype(Name="a", Groups=[ZoneGroup(Name="g", Zone=zone)])
    m = Model.from_archetype(plain, _geometry(), Weather=DefaultEPWZipPath)
    assert m.geometry.wwr_by_orientation is None


@pytest.mark.skipif(
    energyplus_settings.energyplus_version is None,
    reason="simulating needs EnergyPlus",
)
def test_simulated_window_areas_by_orientation(tmp_path: Path):
    """EnergyPlus's window areas by azimuth match the archetype's ratios."""
    import sqlite3

    zone = load_zone()
    archetype = Archetype(
        Name="a",
        Groups=[ZoneGroup(Name="g", Zone=zone)],
        Geometry=BuildingGeometry(WindowToWallRatio=RATIOS),
    )
    m = Model.from_archetype(
        archetype, _geometry(num_stories=1), Weather=DefaultEPWZipPath
    )
    result = m.run(eplus_parent_dir=tmp_path)
    result.sql.close()
    assert result.output_dir is not None
    assert "** Severe  **" not in result.err_text
    (sql_path,) = result.output_dir.glob("*.sql")
    with sqlite3.connect(sql_path) as conn:
        rows = conn.execute(
            "SELECT ClassName, GrossArea, Azimuth, ExtBoundCond FROM Surfaces"
        ).fetchall()
    walls: dict[str, float] = {}
    windows: dict[str, float] = {}
    for cls, area, azimuth, bound in rows:
        o = orientation_of(azimuth)
        if cls == "Window":
            windows[o] = windows.get(o, 0.0) + area
        elif cls == "Wall" and bound == 0:  # 0: outdoors
            walls[o] = walls.get(o, 0.0) + area
    for o, wall in walls.items():
        assert windows.get(o, 0.0) / wall == pytest.approx(RATIOS[o] * 0.999, rel=1e-3)
