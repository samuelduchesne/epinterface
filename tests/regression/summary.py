"""Helpers for summarising EnergyPlus zone geometry independent of the IDF library."""

import re
import sqlite3
from pathlib import Path

import pandas as pd

_EXCLUDED_ROWS = (
    "Total",
    "Conditioned Total",
    "Unconditioned Total",
    "Not Part of Total",
)

_COLUMN_MAP = {
    "Area": "area",
    "Volume": "volume",
    "Above Ground Gross Wall Area": "gross_wall_area",
    "Underground Gross Wall Area": "underground_wall_area",
    "Window Glass Area": "window_glass_area",
}


def zone_geometry_summary(sql_path: Path) -> pd.DataFrame:
    """Read the zone summary table from an EnergyPlus SQLite output file.

    Args:
        sql_path (Path): Path to the ``eplusout.sql`` file.

    Returns:
        pd.DataFrame: Indexed by zone name with ``area``, ``volume``,
            ``gross_wall_area`` and ``window_glass_area`` columns.
    """
    query = """
        SELECT RowName, ColumnName, Value
        FROM TabularDataWithStrings
        WHERE ReportName = 'InputVerificationandResultsSummary'
          AND TableName = 'Zone Summary'
    """
    with sqlite3.connect(sql_path) as conn:
        raw = pd.read_sql_query(query, conn)
    raw = raw[~raw["RowName"].isin(_EXCLUDED_ROWS)]
    raw = raw[raw["ColumnName"].isin(_COLUMN_MAP)]
    wide = raw.pivot(index="RowName", columns="ColumnName", values="Value")
    wide = wide[list(_COLUMN_MAP)].rename(columns=_COLUMN_MAP)
    wide = wide.astype(float)
    # EnergyPlus reports above-ground and underground wall area separately.
    wide["gross_wall_area"] += wide.pop("underground_wall_area")
    wide = wide[["area", "volume", "gross_wall_area", "window_glass_area"]]
    wide.index.name = "zone"
    wide.columns.name = None
    return wide.sort_index()


def zone_names(doc_text: str) -> list[str]:
    """Extract Zone object names, in file order, from IDF text.

    Args:
        doc_text (str): The IDF file contents.

    Returns:
        list[str]: Zone names in order of appearance.
    """
    without_comments = re.sub(r"!.*", "", doc_text)
    return [
        m.group(1).strip()
        for m in re.finditer(r"(?im)^\s*Zone\s*,\s*([^,;]+?)\s*[,;]", without_comments)
    ]
