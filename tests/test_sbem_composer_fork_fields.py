"""The composer leaves out the component fields the SBEM database does not store."""

from epinterface.sbem.components.composer import construct_graph
from epinterface.sbem.components.zones import ZoneComponent

FORK_FIELDS = {
    "WindowSettings",
    "MechVentSchedule",
    "ScheduledVentilationSchedule",
    "HeatingAvailabilitySchedule",
    "CoolingAvailabilitySchedule",
}


def test_graph_skips_fork_fields():
    """Fields marked NOT_COMPOSED are not nodes of the composer's graph."""
    g = construct_graph(ZoneComponent)
    assert not FORK_FIELDS & set(g.nodes)
    assert {"Window", "Ventilation", "ConditioningSystems", "Envelope"} <= set(g.nodes)
