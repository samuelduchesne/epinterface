"""Tests for idfkit value schedules."""

from itertools import chain
from pathlib import Path

import idfkit
import numpy as np
import pytest

from epinterface.interface import add_constant_schedule, add_default_schedules
from epinterface.schedules import add_values_schedule

REGRESSION = Path(__file__).parent / "data" / "regression"


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


def _weekday_varying(rng, last_day_distinct=True):
    week = rng.random((7, 24))
    week[5:] = 0.0
    days = np.tile(week, (53, 1))[:365]
    if last_day_distinct:
        days[-1] = rng.random(24)
    return days.reshape(-1)


def test_add_values_schedule_drops_day_365_like_archetypal(doc):
    """Weekday variation survives; the 365th day is not in any week."""
    vals = _weekday_varying(np.random.default_rng(0))
    result = add_values_schedule(doc, "var", vals, type_limits="Fraction")
    evaluated = _values(doc, "var")
    assert np.allclose(evaluated[: 364 * 24], vals[: 364 * 24])
    # Dec 31 (a Monday in 2018) reuses the last week's Monday profile.
    assert np.allclose(evaluated[364 * 24 :], vals[357 * 24 : 358 * 24])
    # Identical weeks collapse into one block stretched to Dec 31.
    assert len(result.schedule_weeks) == 1
    assert result.schedule_weeks[0]["end_month"] == 12
    assert result.schedule_weeks[0]["end_day"] == 31


def test_add_values_schedule_default_puts_jan_1_in_monday_field(doc):
    """Default (archetypal) mapping: the series' first day fills the Monday field."""
    vals = np.zeros((365, 24))
    vals[0] = 1.0
    add_values_schedule(doc, "mon", vals.reshape(-1), "Fraction")
    week = doc["Schedule:Week:Daily"]["w_mon_01"]
    assert week.monday_schedule_day_name == "d_mon_01"
    assert week.sunday_schedule_day_name == "d_mon_00"


def test_add_values_schedule_sunday_start_weekday_mapping(doc):
    """With Jan 1 = Sunday, a profile set on the first Monday lands on Monday."""
    vals = np.zeros((365, 24))
    vals[1::7] = 1.0  # series day 1 = Monday Jan 2 2017, and every Monday after
    add_values_schedule(
        doc, "sun", vals.reshape(-1), "Fraction", first_weekday="sunday"
    )
    week = doc["Schedule:Week:Daily"]["w_sun_00"]
    assert week.monday_schedule_day_name == "d_sun_01"
    assert week.sunday_schedule_day_name == "d_sun_00"
    evaluated = np.array(
        idfkit.schedules.values(doc["Schedule:Year"]["sun"], year=2017, document=doc)
    ).reshape(365, 24)
    assert (evaluated[1] == 1.0).all()  # Monday Jan 2 2017
    assert (evaluated[0] == 0.0).all()  # Sunday Jan 1
    assert (evaluated[2] == 0.0).all()  # Tuesday Jan 3
    assert np.allclose(evaluated[:364], vals[:364])


def _normalize(values):
    """Strings, with numerics as floats and trailing blanks dropped."""
    out = []
    for v in values:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(str(v))
    while out and out[-1] == "":
        out.pop()
    return out


def _field_values(obj):
    """Name and field values of an idfkit object."""
    return _normalize(obj.fieldvalues)


def _year_field_values(obj):
    """Name, limits and flattened (week, start, end) blocks of a Schedule:Year."""
    blocks = [
        [
            b["schedule_week_name"],
            b["start_month"],
            b["start_day"],
            b["end_month"],
            b["end_day"],
        ]
        for b in obj.schedule_weeks
    ]
    return _normalize([
        obj.name,
        obj.schedule_type_limits_name,
        *chain.from_iterable(blocks),
    ])


def _archetypal_field_values(epbunch):
    """Name and field values of an archetypal (eppy) object."""
    return _normalize(epbunch.fieldvalues[1:])


@pytest.fixture
def idf(tmp_path):
    """An archetypal IDF of the minimal model, for the comparison below (remove in Task 10)."""
    from archetypal.idfclass import IDF

    from epinterface.data import EnergyPlusArtifactDir
    from epinterface.settings import energyplus_settings

    target = tmp_path / "Minimal.idf"
    target.write_text((EnergyPlusArtifactDir / "Minimal.idf").read_text())
    return IDF(
        target.as_posix(),
        as_version=energyplus_settings.energyplus_version,  # pyright: ignore [reportArgumentType]
        file_version=energyplus_settings.energyplus_version,
        prep_outputs=True,
        output_directory=tmp_path.as_posix(),
    )


def test_add_values_schedule_matches_archetypal(doc, idf):
    """Day/Week/Year objects match archetypal's to_year_week_day field-for-field."""
    # remove in Task 10 with archetypal
    from archetypal.schedule import Schedule

    rng = np.random.default_rng(3)
    for name, vals in {
        "wk": _weekday_varying(rng),
        "seasonal": np.where(
            (np.arange(8760) // 24) % 100 < 50, _weekday_varying(rng), 0.25
        ),
    }.items():
        sched = Schedule.from_values(name, vals, Type="Fraction")
        year, _weeks, _days = sched.to_year_week_day()
        year.to_epbunch(idf)
        mine = add_values_schedule(doc, name, vals, "Fraction")

        for kind in ("Day:Hourly", "Week:Daily"):
            theirs = idf.idfobjects[f"SCHEDULE:{kind}".upper()]
            theirs = [o for o in theirs if o.Name.split("_")[1:-1] == [name]]
            ours = [
                o for o in doc[f"Schedule:{kind}"] if o.name.split("_")[1:-1] == [name]
            ]
            assert theirs, kind
            assert len(ours) == len(theirs), kind
            for t, o in zip(
                sorted(theirs, key=lambda x: x.Name),
                sorted(ours, key=lambda x: x.name),
                strict=True,
            ):
                assert _field_values(o) == _archetypal_field_values(t)
        theirs_year = idf.idfobjects["SCHEDULE:YEAR"][-1]
        assert _year_field_values(mine) == _archetypal_field_values(theirs_year)


def test_add_values_schedule_constant_matches_baseline_structure(doc):
    """A constant series yields the one day / week / block seen in built.idf."""
    baseline = idfkit.load_idf(
        str(REGRESSION / "by_storey_plain" / "built.idf"),
        strict_parsing=False,
        strict=False,
    )
    add_values_schedule(doc, "Always_On", np.ones(8760), "Fraction")
    for kind, name in (
        ("Schedule:Day:Hourly", "d_Always_On_00"),
        ("Schedule:Week:Daily", "w_Always_On_00"),
    ):
        assert _field_values(doc[kind][name]) == _field_values(baseline[kind][name])
    assert _year_field_values(doc["Schedule:Year"]["Always_On"]) == _year_field_values(
        baseline["Schedule:Year"]["Always_On"]
    )
    assert len(doc["Schedule:Day:Hourly"]) == 1
    assert len(doc["Schedule:Week:Daily"]) == 1


def test_add_values_schedule_rejects_wrong_length(doc):
    """Only 8760 values are accepted."""
    with pytest.raises(ValueError, match="8760"):
        add_values_schedule(doc, "x", [1.0] * 24, "Fraction")


def _schedule_names(doc):
    """Names of every schedule object, in collection order."""
    return {
        t: [o.name for o in doc[t]]
        for t in ("Schedule:Year", "Schedule:Week:Daily", "Schedule:Day:Hourly")
    }


def test_identical_repeat_leaves_schedule_untouched(doc):
    """Writing the same schedule again reuses it, without reordering."""
    first = add_constant_schedule(doc, "A", 1)
    add_constant_schedule(doc, "B", 0)
    before = _schedule_names(doc)

    again = add_constant_schedule(doc, "A", 1)

    assert again.name == first.name
    assert _schedule_names(doc) == before


def test_different_repeat_replaces_schedule(doc):
    """A different schedule under the same name replaces the old one."""
    add_constant_schedule(doc, "A", 1)
    add_constant_schedule(doc, "A", 0.5)

    assert [o.name for o in doc["Schedule:Year"]] == ["A"]
    assert len(doc["Schedule:Day:Hourly"]) == 1
    day = doc["Schedule:Day:Hourly"]["d_A_00"]
    assert day.hour_1 == 0.5
    assert day.hour_24 == 0.5


def test_orphan_generated_objects_do_not_raise(doc):
    """A leftover day object with no year of that name is replaced, not an error."""
    doc.add("Schedule:Day:Hourly", "d_A_00", {"schedule_type_limits_name": "Fraction"})

    add_constant_schedule(doc, "A", 1)

    assert doc["Schedule:Day:Hourly"]["d_A_00"].hour_1 == 1
    assert len(doc["Schedule:Day:Hourly"]) == 1


def test_default_schedules_twice(doc):
    """Adding the default schedules repeatedly is a no-op."""
    add_default_schedules(doc)
    before = _schedule_names(doc)
    add_default_schedules(doc)
    assert _schedule_names(doc) == before
