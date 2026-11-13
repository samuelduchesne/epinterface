"""Shoebox geometry checked against the geomeppy baseline captured in Task 1."""

import json
from pathlib import Path

import pandas as pd
import pytest
from idfkit import IDFDocument, calculate_surface_area

from tests.regression.configs import GEOMETRY_GRID, REGRESSION_CONFIGS

FIXTURES = Path(__file__).parent / "data" / "regression"
BASELINE = json.loads((FIXTURES / "geometry_baseline.json").read_text())


@pytest.mark.parametrize("key", list(GEOMETRY_GRID))
def test_zone_names_match_baseline(key, doc):
    """Zones carry geomeppy's names, in geomeppy's file order."""
    GEOMETRY_GRID[key].add(doc)
    assert [z.name for z in doc["Zone"]] == BASELINE["zone_names"][key]


def test_neighbor_with_zero_height_adds_no_shading(doc):
    """A neighbour with zero height adds no shading surfaces."""
    geo = GEOMETRY_GRID["by_storey_neighbors"]  # heights [10.0, 0.0]
    geo.add(doc)
    # The baseline counts Shading:Building:Detailed and Shading:Site:Detailed
    # together (geomeppy wrote neighbours as Shading:Site:Detailed).
    n_shading = len(doc["Shading:Building:Detailed"]) + len(
        doc["Shading:Site:Detailed"]
    )
    assert n_shading == BASELINE["shading_counts"]["by_storey_neighbors"]


def _zone_geometry(doc: IDFDocument) -> pd.DataFrame:
    """Per-zone floor area, gross exterior wall area and window glass area."""
    zones = {z.name.upper(): z for z in doc["Zone"]}
    rows = {name: {"area": 0.0, "gross_wall_area": 0.0} for name in zones}
    windows = dict.fromkeys(zones, 0.0)
    for srf in doc["BuildingSurface:Detailed"]:
        row = rows[str(srf.zone_name).upper()]
        surface_type = str(srf.surface_type).lower()
        boundary = str(srf.outside_boundary_condition).lower()
        if surface_type == "floor":
            row["area"] += calculate_surface_area(srf)
        elif surface_type == "wall" and boundary in ("outdoors", "ground"):
            row["gross_wall_area"] += calculate_surface_area(srf)
    for win in doc["FenestrationSurface:Detailed"]:
        parent = doc["BuildingSurface:Detailed"][str(win.building_surface_name)]
        windows[str(parent.zone_name).upper()] += calculate_surface_area(win) * (
            win.multiplier or 1
        )
    df = pd.DataFrame.from_dict(rows, orient="index")
    df["window_glass_area"] = pd.Series(windows)
    multipliers = pd.Series({n: z.multiplier or 1 for n, z in zones.items()})
    return df.mul(multipliers, axis=0).sort_index()


@pytest.mark.parametrize("key", list(REGRESSION_CONFIGS))
def test_regression_geometry_matches_baseline(key, doc, preseeded_readonly_db):
    """Areas computed from the document match EnergyPlus' Zone Summary baseline."""
    model, _ = REGRESSION_CONFIGS[key](preseeded_readonly_db)
    model.geometry.add(doc)
    expected = pd.read_parquet(FIXTURES / key / "geometry.parquet")
    expected = expected[["area", "gross_wall_area", "window_glass_area"]]
    actual = _zone_geometry(doc)
    assert list(actual.index) == list(expected.index)
    pd.testing.assert_frame_equal(
        actual, expected, rtol=1e-9, atol=0.01, check_names=False
    )
