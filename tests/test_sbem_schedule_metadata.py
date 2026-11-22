"""Metadata on schedules (UP-9)."""

from epinterface.sbem.components.schedules import YearComponent
from tests.sbem_helpers import day, load_zone, week, year


def test_defaults_unset():
    """Older schedules load without metadata."""
    sched = load_zone().Operations.SpaceUse.Lighting.Schedule
    for s in (sched, sched.January, sched.January.Monday):
        assert (s.Category, s.Comment, s.DataSource) == (None, None, None)


def test_round_trip():
    """Each level of a schedule keeps its metadata."""
    d = day("d", [1.0] * 24)
    d.Category, d.DataSource = "Day", "ASHRAE 90.1"
    w = week("w", d)
    w.Comment = "office week"
    y = year("y", w)
    y.Category, y.Comment, y.DataSource = "Office", "lighting", "ASHRAE 90.1"
    back = YearComponent.model_validate_json(y.model_dump_json())
    assert (back.Category, back.Comment, back.DataSource) == (
        "Office",
        "lighting",
        "ASHRAE 90.1",
    )
    assert back.January.Comment == "office week"
    assert back.January.Monday.DataSource == "ASHRAE 90.1"
