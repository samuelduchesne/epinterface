"""Tests for idfkit value schedules."""

import idfkit
import numpy as np
import pytest

from epinterface.schedules import add_values_schedule


def _values(doc, name):
    return idfkit.schedules.values(doc["Schedule:Year"][name], year=2018, document=doc)


def test_add_values_schedule_round_trips(doc):
    """A daily-repeating profile reproduces exactly and needs one day object."""
    vals = np.tile(np.r_[np.zeros(8), np.ones(10), np.zeros(6)], 365)
    result = add_values_schedule(doc, "occ", vals, type_limits="Fraction")
    assert result.name == "occ"
    assert np.allclose(_values(doc, "occ"), vals)
    assert len(doc["Schedule:Day:Hourly"]) == 1
    assert len(doc["Schedule:Week:Daily"]) == 1
    assert doc["Schedule:Day:Hourly"]["d_occ_00"] is not None
    assert doc["Schedule:Week:Daily"]["w_occ_00"] is not None


def test_add_values_schedule_weekly_and_last_day_variation(doc):
    """Weekday variation and a distinct final day survive the round trip."""
    rng = np.random.default_rng(0)
    week = rng.random((7, 24))
    days = np.tile(week, (53, 1))[:365]
    days[-1] = rng.random(24)
    vals = days.reshape(-1)
    add_values_schedule(doc, "var", vals, type_limits="Fraction")
    assert np.allclose(_values(doc, "var"), vals)


def test_add_values_schedule_rejects_wrong_length(doc):
    """Only 8760 values are accepted."""
    with pytest.raises(ValueError, match="8760"):
        add_values_schedule(doc, "x", [1.0] * 24, "Fraction")
