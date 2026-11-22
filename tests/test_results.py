"""Tests for reading simulation results through idfkit's SQLResult."""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from idfkit.simulation.parsers.sql import SQLResult

from epinterface.results import tabular_frame, timeseries_frame

VAR = "Zone Mean Air Temperature"


@pytest.fixture
def tiny_sql(tmp_path: Path):
    """A tiny EnergyPlus-shaped SQLite file wrapped in a SQLResult."""
    path = tmp_path / "tiny.sql"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE ReportDataDictionary (
            ReportDataDictionaryIndex INTEGER, IndexGroup TEXT, KeyValue TEXT,
            Name TEXT, Units TEXT, ReportingFrequency TEXT);
        CREATE TABLE ReportData (TimeIndex INTEGER, ReportDataDictionaryIndex INTEGER, Value REAL);
        CREATE TABLE Time (
            TimeIndex INTEGER, Month INTEGER, Day INTEGER, Hour INTEGER,
            Minute INTEGER, Interval INTEGER, WarmupFlag INTEGER,
            EnvironmentPeriodIndex INTEGER);
        CREATE TABLE EnvironmentPeriods (EnvironmentPeriodIndex INTEGER, EnvironmentType INTEGER);
        CREATE TABLE TabularDataWithStrings (
            ReportName TEXT, TableName TEXT, ReportForString TEXT,
            ColumnName TEXT, RowName TEXT, Units TEXT, Value TEXT);
        """
    )
    con.executemany(
        "INSERT INTO ReportDataDictionary VALUES (?,?,?,?,?,?)",
        [
            (1, "Zone", "ZONE A", VAR, "C", "Hourly"),
            (2, "Zone", "ZONE B", VAR, "C", "Hourly"),
        ],
    )
    con.executemany("INSERT INTO EnvironmentPeriods VALUES (?,?)", [(1, 1), (2, 3)])
    # (TimeIndex, month, day, hour, minute, interval, warmup, env)
    times = [
        (1, 1, 1, 1, 0, 60, 0, 1),  # design day
        (2, 1, 1, 1, 0, 60, 1, 2),  # warmup
        (3, 1, 1, 1, 0, 60, 0, 2),
        (4, 1, 1, 2, 0, 60, 0, 2),
        (5, 1, 1, 3, 0, 60, 0, 2),
    ]
    con.executemany("INSERT INTO Time VALUES (?,?,?,?,?,?,?,?)", times)
    values = {1: 99.0, 2: 98.0, 3: 20.0, 4: 21.0, 5: 22.0}
    rows = []
    for t, v in values.items():
        rows.append((t, 1, v))
        rows.append((t, 2, v + 10 if t > 2 else v))
    con.executemany("INSERT INTO ReportData VALUES (?,?,?)", rows)
    con.executemany(
        "INSERT INTO TabularDataWithStrings VALUES (?,?,?,?,?,?,?)",
        [
            (
                "AnnualBuildingUtilityPerformanceSummary",
                "End Uses",
                "Entire Facility",
                "Electricity",
                "Heating",
                "GJ",
                "1.5",
            ),
            (
                "AnnualBuildingUtilityPerformanceSummary",
                "End Uses",
                "Entire Facility",
                "Electricity",
                "Cooling",
                "GJ",
                "2.5",
            ),
            (
                "AnnualBuildingUtilityPerformanceSummary",
                "End Uses",
                "Entire Facility",
                "Water",
                "Heating",
                "m3",
                "0.0",
            ),
        ],
    )
    con.commit()
    con.close()
    sql = SQLResult(path)
    yield sql
    sql.close()


def test_timeseries_frame_shape(tiny_sql):
    """Exercise the behaviour named by the test."""
    df = timeseries_frame(tiny_sql, [VAR])
    assert list(df.columns.names) == ["IndexGroup", "KeyValue", "Name"]
    assert sorted(df.columns.get_level_values("KeyValue")) == ["ZONE A", "ZONE B"]
    assert len(df) == 3
    assert df.index[0] == pd.Timestamp("2018-01-01 00:00")


def test_timeseries_frame_excludes_warmup_and_design_days(tiny_sql):
    """Exercise the behaviour named by the test."""
    df = timeseries_frame(tiny_sql, VAR)
    assert df[("Zone", "ZONE A", VAR)].tolist() == [20.0, 21.0, 22.0]
    assert df[("Zone", "ZONE B", VAR)].tolist() == [30.0, 31.0, 32.0]


def test_timeseries_frame_unknown_name_is_empty(tiny_sql):
    """Exercise the behaviour named by the test."""
    assert timeseries_frame(tiny_sql, ["Not A Variable"]).empty


def test_tabular_frame_pivot(tiny_sql):
    """Exercise the behaviour named by the test."""
    df = tabular_frame(tiny_sql, "AnnualBuildingUtilityPerformanceSummary", "End Uses")
    assert list(df.columns.names) == ["ColumnName", "Units"]
    assert df.loc["Heating", ("Electricity", "GJ")] == 1.5
