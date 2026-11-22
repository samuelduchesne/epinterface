"""Helpers for summarising EnergyPlus zone geometry independent of the IDF library."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
from idfkit import IDFObject, calculate_surface_area
from idfkit.geometry import get_surface_coords

from epinterface.document import EPDocument

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
    # `closing`: a sqlite3 connection's own context manager only commits.
    with closing(sqlite3.connect(sql_path)) as conn:
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


def surface_records(doc: EPDocument) -> list[dict]:
    """Describe every surface without relying on surface names or vertex order.

    Building surfaces, windows and shading surfaces are each described by their
    zone, type, boundary condition, the zone on the other side of a
    `Surface` boundary, construction, area and centroid.

    Args:
        doc (EPDocument): The document to describe.

    Returns:
        list[dict]: One record per surface, sorted.
    """
    surfaces = doc["BuildingSurface:Detailed"]

    def record(kind: str, srf: IDFObject, zone: str, boundary: str, other: str):
        poly = get_surface_coords(srf)
        assert poly is not None
        is_shading = kind == "shading"
        return {
            "kind": kind,
            "zone": zone,
            "surface_type": "" if is_shading else str(srf.surface_type).lower(),
            "boundary": boundary.lower(),
            "boundary_zone": other,
            "construction": "" if is_shading else str(srf.construction_name or ""),
            "area": round(calculate_surface_area(srf), 6) + 0.0,
            "centroid": [round(c, 6) + 0.0 for c in poly.centroid.as_tuple()],
        }

    records = []
    for srf in surfaces:
        partner = surfaces.get(str(srf.outside_boundary_condition_object or ""))
        records.append(
            record(
                "surface",
                srf,
                str(srf.zone_name),
                str(srf.outside_boundary_condition),
                str(partner.zone_name) if partner is not None else "",
            )
        )
    for win in doc["FenestrationSurface:Detailed"]:
        parent = surfaces[str(win.building_surface_name)]
        records.append(record("window", win, str(parent.zone_name), "", ""))
    for shading_type in ("Shading:Site:Detailed", "Shading:Building:Detailed"):
        for srf in doc[shading_type]:
            records.append(record("shading", srf, "", "", ""))
    return sorted(
        records,
        key=lambda r: (r["kind"], r["zone"], r["surface_type"], r["centroid"]),
    )
