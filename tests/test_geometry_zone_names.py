"""Shoebox geometry checked against the geomeppy baseline captured in Task 1."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from idfkit import IDFDocument, calculate_surface_area

from tests.regression.configs import (
    GEOMEPPY_MISMATCHED_KEY,
    GEOMETRY_GRID,
    GEOMETRY_SURFACE_CASES,
    REGRESSION_CONFIGS,
)
from tests.regression.summary import surface_records

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


SURFACES = json.loads((FIXTURES / "geometry_surfaces.json").read_text())
_RECORD_KEYS = ("kind", "zone", "surface_type", "boundary", "boundary_zone")


def _same_surface(a: dict, b: dict) -> bool:
    return (
        all(a[k] == b[k] for k in (*_RECORD_KEYS, "construction"))
        and np.isclose(a["area"], b["area"], atol=1e-5)
        and np.allclose(a["centroid"], b["centroid"], atol=1e-5)
    )


def _unmatched(actual: list[dict], expected: list[dict]):
    """Pair records one to one; return those left over on each side."""
    remaining = list(expected)
    only_actual = []
    for record in actual:
        match = next((e for e in remaining if _same_surface(record, e)), None)
        if match is None:
            only_actual.append(record)
        else:
            remaining.remove(match)
    return only_actual, remaining


def _brief(records: list[dict]) -> list[tuple]:
    return sorted(
        (r["kind"], r["zone"], r["boundary"], r["boundary_zone"], r["construction"])
        for r in records
    )


@pytest.mark.parametrize("key", list(GEOMETRY_GRID))
def test_surfaces_match_geomeppy(key, doc):
    """Every surface, window and shading surface matches geomeppy's (names aside)."""
    GEOMETRY_SURFACE_CASES[key].add(doc)
    only_idfkit, only_geomeppy = _unmatched(surface_records(doc), SURFACES[key])
    assert only_idfkit == []
    assert only_geomeppy == []


def test_surfaces_where_geomeppy_mismatched(doc):
    """With 4.321 m storeys geomeppy's intersect_match paired the top storey wrongly.

    On storey 2, the Perimeter_Zone_4 wall at the P3/P4 corner was paired with
    Perimeter_Zone_2 (the P1/P2 corner, on the far side of the building), and
    the Perimeter_Zone_3 partition at the P3/P4 corner was left as an outdoor
    wall carrying a window. idfkit pairs the corner partitions correctly, so
    this case differs on purpose: those three walls and that window.
    """
    GEOMETRY_SURFACE_CASES[GEOMEPPY_MISMATCHED_KEY].add(doc)
    only_idfkit, only_geomeppy = _unmatched(
        surface_records(doc), SURFACES[GEOMEPPY_MISMATCHED_KEY]
    )
    p1, p2, p3, p4 = (f"Block Perimeter_Zone_{i} Storey 2" for i in range(1, 5))
    assert _brief(only_idfkit) == sorted([
        ("surface", p2, "surface", p1, "Project Partition"),
        ("surface", p3, "surface", p4, "Project Partition"),
        ("surface", p4, "surface", p3, "Project Partition"),
    ])
    assert _brief(only_geomeppy) == sorted([
        ("surface", p2, "surface", p4, "Project Partition"),
        ("surface", p4, "surface", p2, "Project Partition"),
        # geomeppy left a stale boundary object on the outdoor wall
        ("surface", p3, "outdoors", "Block Perimeter_Zone_1 Storey 0", "Project Wall"),
        ("window", p3, "", "", "Project External Window"),
    ])


def test_default_constructions_exist_and_match_geomeppy(doc):
    """Every referenced construction is defined, with geomeppy's names and materials."""
    key = "core/perim-True-2.5-1"
    GEOMETRY_GRID[key].add(doc)
    referenced = {
        str(srf.construction_name)
        for srf_type in ("BuildingSurface:Detailed", "FenestrationSurface:Detailed")
        for srf in doc[srf_type]
    }
    defined = {c.name for c in doc["Construction"]}
    assert referenced <= defined
    assert referenced == {r["construction"] for r in SURFACES[key]} - {""}
    material = doc["Material"]["DefaultMaterial"]
    assert (material.roughness, material.thickness, material.conductivity) == (
        "Rough",
        0.1,
        0.1,
    )
    assert (material.density, material.specific_heat) == (1000, 1000)
    glazing = doc["WindowMaterial:SimpleGlazingSystem"]["DefaultGlazing"]
    assert (
        glazing.u_factor,
        glazing.solar_heat_gain_coefficient,
        glazing.visible_transmittance,
    ) == (2.7, 0.763, 0.8)
