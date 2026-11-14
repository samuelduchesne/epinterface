"""Tests for zone-area helpers and the zone-area dependent water use."""

from typing import Any

import pytest
from prisma import Prisma

from epinterface.document import EPDocument
from epinterface.geometry import get_zone_floor_area, get_zone_glazed_area
from epinterface.sbem.prisma.client import deep_fetcher


def _vertices(points: list[tuple[float, float, float]]):
    return [
        {
            "vertex_x_coordinate": x,
            "vertex_y_coordinate": y,
            "vertex_z_coordinate": z,
        }
        for x, y, z in points
    ]


def _add_box_zone(doc: EPDocument, zone_name: str):
    """Add a zone with a 5 x 4 m floor and a 2 m2 window on a 5 x 3 m wall."""
    doc.add("Zone", zone_name)
    doc.add(
        "BuildingSurface:Detailed",
        f"{zone_name}_Floor",
        surface_type="Floor",
        construction_name="",
        zone_name=zone_name,
        outside_boundary_condition="Ground",
        number_of_vertices=4,
        vertices=_vertices([(0, 0, 0), (0, 4, 0), (5, 4, 0), (5, 0, 0)]),
        validate=False,
    )
    doc.add(
        "BuildingSurface:Detailed",
        f"{zone_name}_Wall",
        surface_type="Wall",
        construction_name="",
        zone_name=zone_name,
        outside_boundary_condition="Outdoors",
        number_of_vertices=4,
        vertices=_vertices([(0, 0, 3), (0, 0, 0), (5, 0, 0), (5, 0, 3)]),
        validate=False,
    )
    window_points = [(1, 0, 2), (1, 0, 1), (3, 0, 1), (3, 0, 2)]
    window_vertices: dict[str, Any] = {
        f"vertex_{i}_{axis}_coordinate": point[k]
        for i, point in enumerate(window_points, start=1)
        for k, axis in enumerate("xyz")
    }
    doc.add(
        "FenestrationSurface:Detailed",
        f"{zone_name}_Window",
        surface_type="Window",
        construction_name="",
        building_surface_name=f"{zone_name}_Wall",
        number_of_vertices=4,
        validate=False,
        **window_vertices,
    )


def test_zone_floor_and_glazed_area(doc: EPDocument):
    """Floor and window areas are read from the document's surfaces."""
    _add_box_zone(doc, "Box")
    doc.add("Zone", "Empty")

    assert get_zone_floor_area(doc, "Box") == pytest.approx(20.0)
    assert get_zone_glazed_area(doc, "Box") == pytest.approx(2.0)
    assert get_zone_glazed_area(doc, "Empty") == 0
    with pytest.raises(ValueError, match="TOO_MANY_FLOORS:Empty:0"):
        get_zone_floor_area(doc, "Empty")


def test_add_water_use_to_zone(doc: EPDocument, preseeded_readonly_db: Prisma):
    """Water use is sized from the zone floor area and writes its schedules."""
    _record, zone = deep_fetcher.Zone.get_deep_object(
        "default_zone", preseeded_readonly_db
    )
    ops = zone.Operations
    ops.DHW.IsOn = True
    ops.DHW.WaterSupplyTemperature = 55
    ops.DHW.WaterTemperatureInlet = 10
    zone_name = "Box"
    _add_box_zone(doc, zone_name)
    expected_name = (
        f"{zone_name}_{ops.SpaceUse.WaterUse.safe_name}_{ops.DHW.safe_name}_WATER"
    )
    assert expected_name not in doc["WaterUse:Equipment"]

    doc = ops.add_water_use_to_idf_zone(doc, zone_name)
    doc = ops.add_water_use_to_idf_zone(doc, zone_name)  # repeat is not an error

    water = doc["WaterUse:Equipment"].get(expected_name)
    assert water is not None
    assert len(doc["WaterUse:Equipment"]) == 1
    people = ops.SpaceUse.Occupancy.PeopleDensity * 20.0
    avg_flow = ops.SpaceUse.WaterUse.FlowRatePerPerson * people / (3600 * 24)
    frac = ops.SpaceUse.WaterUse.Schedule.fractional_year_sum(2018)
    assert water.peak_flow_rate == pytest.approx(avg_flow / frac)
    target = doc["Schedule:Year"][f"{expected_name}_TargetWaterTemperatureSch"]
    assert target.schedule_type_limits_name == "Temperature"
    assert water.target_temperature_schedule_name == target.name
    assert (
        water.cold_water_supply_temperature_schedule_name
        == f"{expected_name}_InletWaterTemperatureSch"
    )
    assert water.zone_name == zone_name
