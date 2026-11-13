"""A module for testing the operations component."""

import pytest
from idfkit import IDFDocument
from prisma import Prisma

from epinterface.sbem.prisma.client import deep_fetcher


@pytest.mark.skip(reason="Not yet implmented")
@pytest.mark.parametrize(
    "is_on,supply_temp,inlet_temp,flow_rate_per_person",
    [(False, 10, 55, 0.1), (True, 10, 55, 0.1)],
)
def test_operations_add_hot_water_to_idf(
    doc: IDFDocument,
    preseeded_readonly_db: Prisma,
    is_on: bool,
    supply_temp: float,
    inlet_temp: float,
    flow_rate_per_person: float,
):
    """Testing adding hot water to the document."""
    _zone_record, _zone = deep_fetcher.Zone.get_deep_object(
        "default_zone", preseeded_readonly_db
    )
    # doc = geometry.add(doc)
    # zone.Operations.DHW.IsOn = is_on
    # zone.Operations.DHW.WaterSupplyTemperature = supply_temp
    # zone.Operations.DHW.WaterTemperatureInlet = inlet_temp
    # zone.Operations.SpaceUse.WaterUse.FlowRatePerPerson = flow_rate_per_person

    # for idf_zone in doc["Zone"]:
    #     zone_name = idf_zone.name
    #     expected_water_name = f"{zone_name}_{zone.Operations.SpaceUse.WaterUse.safe_name}_{zone.Operations.DHW.safe_name}_WATER"
    #     assert expected_water_name not in doc["WaterUse:Equipment"]
    #     doc = zone.Operations.add_water_use_to_idf_zone(doc, zone_name)
    #     water_use = doc["WaterUse:Equipment"].get(expected_water_name)
    #     if is_on:
    #         assert water_use
    #     TODO: complit explicitly expected flow rates using prior knowledge of fixture zone areas.
    #         zone_area = 100 if idf_zone.floor_area == 0 else idf_zone.floor_area
    #         assert water_use.peak_flow_rate == flow_rate_per_person * zone_area *
    #     else:
    #         assert not water_use
