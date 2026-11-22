"""Read simulation results from an idfkit ``SQLResult`` as pandas frames."""

from collections.abc import Sequence
from datetime import timedelta

import pandas as pd
from idfkit.simulation.parsers.sql import SQLResult

_DICTIONARY_COLUMNS = ["ReportDataDictionaryIndex", "IndexGroup", "KeyValue", "Name"]


def timeseries_frame(
    sql: SQLResult,
    names: str | Sequence[str],
    frequency: str = "Hourly",
    environment_type: int = 3,
) -> pd.DataFrame:
    """Get a timeseries frame for the named output variables or meters.

    The frame has a column MultiIndex with levels ``["IndexGroup", "KeyValue", "Name"]``
    and a ``DatetimeIndex`` (year 2018) marking the start of each interval.
    Warmup rows and environments other than ``environment_type`` are excluded.

    Args:
        sql (SQLResult): The open results database.
        names (str | Sequence[str]): Output variable or meter name(s).
        frequency (str): The reporting frequency, e.g. "Hourly" or "Monthly".
        environment_type (int): 1 = design day, 2 = design run period, 3 = weather run period.

    Returns:
        pd.DataFrame: The timeseries, or an empty frame if no names match.
    """
    name_list = [names] if isinstance(names, str) else list(names)
    if not name_list:
        return pd.DataFrame()
    marks = ",".join("?" for _ in name_list)
    header_rows = pd.DataFrame(
        sql.query(
            "SELECT ReportDataDictionaryIndex, IndexGroup, KeyValue, Name, Units "  # noqa: S608
            f"FROM ReportDataDictionary WHERE Name IN ({marks}) "
            "AND ReportingFrequency = ?",
            (*name_list, frequency),
        ),
        columns=[*_DICTIONARY_COLUMNS, "Units"],
    )
    if header_rows.empty:
        return pd.DataFrame()
    header_rows = header_rows.set_index("ReportDataDictionaryIndex")
    indices = [int(i) for i in header_rows.index]
    idx_marks = ",".join("?" for _ in indices)
    data = pd.DataFrame(
        sql.query(
            "SELECT rd.Value, rd.ReportDataDictionaryIndex, t.Month, t.Day, "  # noqa: S608
            "t.Hour, t.Minute, t.Interval "
            "FROM ReportData AS rd "
            "LEFT JOIN Time AS t ON rd.TimeIndex = t.TimeIndex "
            "LEFT JOIN EnvironmentPeriods AS p "
            "ON t.EnvironmentPeriodIndex = p.EnvironmentPeriodIndex "
            f"WHERE rd.ReportDataDictionaryIndex IN ({idx_marks}) "
            "AND IFNULL(t.WarmupFlag, 0) = 0 "
            "AND p.EnvironmentType = ? "
            "ORDER BY rd.ReportDataDictionaryIndex, t.TimeIndex",
            (*indices, environment_type),
        ),
        columns=[
            "Value",
            "ReportDataDictionaryIndex",
            "Month",
            "Day",
            "Hour",
            "Minute",
            "Interval",
        ],
    )
    data = data.join(
        header_rows[["IndexGroup", "KeyValue", "Name"]],
        on="ReportDataDictionaryIndex",
    )
    data = data.pivot(
        index=["Month", "Day", "Hour", "Minute", "Interval"],
        columns=["IndexGroup", "KeyValue", "Name"],
        values="Value",
    )
    date_time_names = data.index.names
    data = data.reset_index()
    parts = pd.DataFrame({
        "year": 2018,
        "month": data["Month"],
        "day": data["Day"],
        "hour": data["Hour"],
        "minute": data["Minute"],
    })
    index = pd.to_datetime(parts)
    index -= data["Interval"].apply(lambda x: timedelta(minutes=x))
    index = pd.DatetimeIndex(index, freq="infer")
    data = data.drop(columns=date_time_names, level="IndexGroup")
    data.index = index
    return data


def _coerce_numeric(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert each column to numeric where possible, leaving others untouched."""
    out = frame.copy()
    for col in out.columns:
        try:
            out[col] = pd.to_numeric(out[col])
        except (ValueError, TypeError):
            continue
    return out


def tabular_frame(
    sql: SQLResult,
    report_name: str,
    table_name: str,
    report_for: str | None = None,
) -> pd.DataFrame:
    """Get a tabular report table as a DataFrame.

    Args:
        sql (SQLResult): The open results database.
        report_name (str): The report name.
        table_name (str): The table name within the report.
        report_for (str | None): The optional "For" string.

    Returns:
        pd.DataFrame: Indexed by ``RowName`` with ``["ColumnName", "Units"]`` columns,
            or the long-form rows if the table cannot be pivoted.
    """
    rows = sql.query(
        "SELECT RowName, ColumnName, Value, Units FROM TabularDataWithStrings "
        "WHERE ReportName = ? AND TableName = ? AND (? IS NULL OR ReportForString = ?)",
        (report_name, table_name, report_for, report_for),
    )
    data = pd.DataFrame(rows, columns=["RowName", "ColumnName", "Value", "Units"])
    try:
        pivoted = data.pivot(
            index="RowName", columns=["ColumnName", "Units"], values="Value"
        )
    except ValueError:
        pivoted = data
    return _coerce_numeric(pivoted)
