"""The base idfkit document every model is built on."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeAlias

import idfkit
from idfkit import IDFObject
from idfkit.document import AnyIDFDocument
from idfkit.versioned import (
    IDFDocumentV22_2,
    IDFDocumentV23_1,
    IDFDocumentV23_2,
    IDFDocumentV24_1,
    IDFDocumentV24_2,
    IDFDocumentV25_1,
    IDFDocumentV25_2,
    as_version,
)

# The EnergyPlus releases epinterface builds models for, oldest first. It keeps
# per-version meter and table definitions for these majors only (see
# `epinterface.settings.SUPPORTED_ENERGYPLUS_MAJORS`). 22.1 is left out: it
# names several fields epinterface writes differently (the zone and flow fields
# of `ZoneInfiltration:DesignFlowRate`, the zone of
# `ZoneVentilation:WindandStackOpenArea`), and epinterface writes 22.2's names.
SUPPORTED_DOCUMENT_TYPES = (
    IDFDocumentV22_2,
    IDFDocumentV23_1,
    IDFDocumentV23_2,
    IDFDocumentV24_1,
    IDFDocumentV24_2,
    IDFDocumentV25_1,
    IDFDocumentV25_2,
)

# `TypeAlias`, not a `type` statement, while Python 3.10 and 3.11 are supported.
EPDocument: TypeAlias = (  # noqa: UP040
    IDFDocumentV22_2
    | IDFDocumentV23_1
    | IDFDocumentV23_2
    | IDFDocumentV24_1
    | IDFDocumentV24_2
    | IDFDocumentV25_1
    | IDFDocumentV25_2
)
"""A document of any EnergyPlus release epinterface supports.

Through it, a type checker offers only the object types and fields that every
supported release has, and accepts only values every one of them accepts.
"""


def as_supported(doc: AnyIDFDocument) -> EPDocument:
    """Type `doc` as a document of a supported EnergyPlus release.

    Returns `doc` itself, after checking its version at run time.

    Raises:
        TypeError: If `doc` is of a release epinterface does not support.
    """
    return as_version(doc, SUPPORTED_DOCUMENT_TYPES)


def load_document(path: Path | str, version: tuple[int, int, int]) -> EPDocument:
    """Load an IDF or DDY file as a document of a supported EnergyPlus release.

    Args:
        path (Path | str): The file to load.
        version (tuple[int, int, int]): The EnergyPlus version to read it as.

    Raises:
        TypeError: If `version` is not a release epinterface supports.
    """
    return as_supported(idfkit.load_idf(str(path), version=version))


_DESIGN_DAY_COMMON: dict[str, Any] = {
    "daily_dry_bulb_temperature_range": 0.0,
    "dry_bulb_temperature_range_modifier_type": "DefaultMultipliers",
    "humidity_condition_type": "Wetbulb",
    "barometric_pressure": 101281.0,
    "rain_indicator": "No",
    "snow_indicator": "No",
    "daylight_saving_time_indicator": "No",
}

# The objects of the former packaged `Minimal.idf`, with its values and the
# field names of the newest idfkit schema. Fields an older schema lacks are
# skipped only through the explicit `_FIELD_ADDED_IN` allowlist; any other
# unknown field fails in `doc.add`.
# `new_document` also pre-adds a SimulationControl, which is removed because the
# migrated `Minimal.idf` never had one (parity with the former base model).
_MINIMAL_OBJECTS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    (
        "Building",
        "None",
        {
            "north_axis": 0.0,
            "terrain": "Suburbs",
            "loads_convergence_tolerance_value": 0.04,
            "temperature_convergence_tolerance_value": 0.4,
            "solar_distribution": "FullInteriorAndExterior",
            "maximum_number_of_warmup_days": 25,
            "minimum_number_of_warmup_days": 6,
        },
    ),
    (
        "GlobalGeometryRules",
        "",
        {
            "starting_vertex_position": "UpperLeftCorner",
            "vertex_entry_direction": "CounterClockWise",
            "coordinate_system": "World",
        },
    ),
    (
        "Site:Location",
        "DENVER_STAPLETON_CO_USA_WMO_724690",
        {
            "latitude": 39.77,
            "longitude": -104.87,
            "time_zone": -7.0,
            "elevation": 1611.0,
        },
    ),
    (
        "SizingPeriod:DesignDay",
        "Boston-Logan.Intl.AP Ann Htg 99.6% Condns DB",
        _DESIGN_DAY_COMMON
        | {
            "month": 1,
            "day_of_month": 21,
            "day_type": "WinterDesignDay",
            "maximum_dry_bulb_temperature": -13.5,
            "wetbulb_or_dewpoint_at_maximum_dry_bulb": -13.5,
            "wind_speed": 7.2,
            "wind_direction": 300.0,
            "solar_model_indicator": "ASHRAEClearSky",
            "sky_clearness": 0.0,
        },
    ),
    (
        "SizingPeriod:DesignDay",
        "Boston-Logan.Intl.AP Ann Clg .4% Condns DB=>MWB",
        _DESIGN_DAY_COMMON
        | {
            "month": 7,
            "day_of_month": 21,
            "day_type": "SummerDesignDay",
            "maximum_dry_bulb_temperature": 32.7,
            "daily_dry_bulb_temperature_range": 10.7,
            "wetbulb_or_dewpoint_at_maximum_dry_bulb": 22.8,
            "daily_wet_bulb_temperature_range": 4.4,
            "wind_speed": 6.1,
            "wind_direction": 240.0,
            "solar_model_indicator": "ASHRAETau2017",
            "ashrae_clear_sky_optical_depth_for_beam_irradiance_taub_": 0.472,
            "ashrae_clear_sky_optical_depth_for_diffuse_irradiance_taud_": 2.185,
        },
    ),
    (
        "Sizing:Parameters",
        "",
        {"heating_sizing_factor": 1.15, "cooling_sizing_factor": 1.15},
    ),
    (
        "HeatBalanceAlgorithm",
        "",
        {
            "algorithm": "ConductionTransferFunction",
            "surface_temperature_upper_limit": 200.0,
            "minimum_surface_convection_heat_transfer_coefficient_value": 0.1,
            "maximum_surface_convection_heat_transfer_coefficient_value": 1000.0,
        },
    ),
    ("SurfaceConvectionAlgorithm:Inside", "", {"algorithm": "TARP"}),
    ("SurfaceConvectionAlgorithm:Outside", "", {"algorithm": "DOE-2"}),
    (
        "Site:GroundTemperature:BuildingSurface",
        "",
        {
            f"{month}_ground_temperature": temperature
            for month, temperature in zip(
                (
                    "january",
                    "february",
                    "march",
                    "april",
                    "may",
                    "june",
                    "july",
                    "august",
                    "september",
                    "october",
                    "november",
                    "december",
                ),
                (
                    18.3,
                    18.2,
                    18.3,
                    18.4,
                    20.1,
                    22.0,
                    22.3,
                    22.5,
                    22.5,
                    20.7,
                    18.9,
                    18.5,
                ),
                strict=True,
            )
        },
    ),
    ("Output:VariableDictionary", "", {"key_field": "Regular"}),
    ("OutputControl:Table:Style", "", {"column_separator": "HTML"}),
    (
        "Output:Table:SummaryReports",
        "",
        {"reports": [{"report_name": "AllSummary"}]},
    ),
    (
        "Output:SQLite",
        "",
        {
            "option_type": "SimpleAndTabular",
            "unit_conversion_for_tabular_data": "UseOutputControlTableStyle",
        },
    ),
)


# Fields a version's schema lacks, as (object type, field) -> first version that has it.
# Anything else not in the schema is a typo and must fail loudly in `doc.add`.
_FIELD_ADDED_IN: dict[tuple[str, str], tuple[int, int, int]] = {
    ("Output:SQLite", "unit_conversion_for_tabular_data"): (9, 5, 0),
}


def _add_objects(
    doc: AnyIDFDocument,
    objects: tuple[tuple[str, str, dict[str, Any]], ...] = _MINIMAL_OBJECTS,
) -> None:
    """Add `objects` to `doc`, skipping only the fields in `_FIELD_ADDED_IN`."""
    for obj_type, name, fields in objects:
        supported = {
            k: v
            for k, v in fields.items()
            if doc.version >= _FIELD_ADDED_IN.get((obj_type, k), (0, 0, 0))
        }
        if supported.get("solar_model_indicator") == "ASHRAETau2017" and doc.version < (
            9,
            0,
            0,
        ):
            supported["solar_model_indicator"] = "ASHRAETau"  # 2017 model is newer
        doc.add(obj_type, name, supported)


def _fill_minimal(doc: AnyIDFDocument) -> None:
    """Replace `new_document`'s baseline objects in `doc` with the minimal objects.

    Works for a document of any release idfkit knows, not only the supported ones.
    """
    for baseline_type in ("SimulationControl", "Building", "GlobalGeometryRules"):
        for obj in list(doc.get_collection(baseline_type)):
            doc.removeidfobject(obj)
    _add_objects(doc)


def minimal_document(version: tuple[int, int, int]) -> EPDocument:
    """A new base document at EnergyPlus `version`: the minimal objects to run.

    The document is built programmatically from the version's own schema, so any
    supported version can be requested directly (no migration step).
    Every call returns a fresh document that the caller may edit freely.

    Raises:
        TypeError: If `version` is not a release epinterface supports.
    """
    doc = as_supported(idfkit.new_document(version))
    _fill_minimal(doc)
    return doc


def watts_per_area(doc: EPDocument, value: float) -> dict[str, float]:
    """The Watts/Area design level of `Lights` or `ElectricEquipment` for `doc`.

    EnergyPlus 24.1 renamed the field `watts_per_zone_floor_area` to
    `watts_per_floor_area`. Pass the result as keyword fields:
    `add_or_replace(doc, "Lights", name, **watts_per_area(doc, 8.0), ...)`.

    Args:
        doc (EPDocument): The document the object is written to.
        value (float): The design level [W/m2].

    Returns:
        dict[str, float]: The value under the field name of `doc`'s release.
    """
    if doc.version < (24, 1, 0):
        return {"watts_per_zone_floor_area": value}
    return {"watts_per_floor_area": value}


def add_or_replace(
    doc: EPDocument, obj_type: str, name: str = "", /, **fields: Any
) -> IDFObject:
    """Add one object, reusing or replacing an existing one as archetypal did.

    archetypal's writer (`newidfobject`) kept a model free of duplicates, and
    epinterface relies on that when several components write the same shared
    object (a material used by several constructions, a type limit or a
    schedule used by several loads):

    - A type EnergyPlus allows only once (e.g. `Timestep`) replaces the object
      already in the document, so the result holds a single, current definition.
    - An object whose type and name already exist is returned as is when its
      fields are identical, and replaced otherwise.

    Fields set to None are left blank. Field names are idfkit's (the schema's
    snake_case names); an unknown field raises in `doc.add`.

    Args:
        doc (EPDocument): The document to write to.
        obj_type (str): The EnergyPlus object type, e.g. "Material".
        name (str): The object's name; empty for unnamed types.
        **fields (Any): The object's fields by idfkit name.

    Returns:
        IDFObject: The object now in the document.
    """
    fields = {k: v for k, v in fields.items() if v is not None}
    obj_schema = doc.schema.get_object_schema(obj_type) if doc.schema else None
    if obj_schema and obj_schema.get("maxProperties") == 1:
        for existing in list(doc[obj_type]):
            doc.removeidfobject(existing)
    elif name and (existing := doc[obj_type].get(name)) is not None:
        stored = {
            k: v
            for k, v in existing.to_dict().items()
            if k != "name" and v not in (None, "")
        }
        if stored == {k: v for k, v in fields.items() if v not in (None, "")}:
            return existing
        doc.removeidfobject(existing)
    return doc.add(obj_type, name, fields)


def add_construction(
    doc: EPDocument, name: str, layer_names: Sequence[str]
) -> IDFObject:
    """Write a `Construction` of the named layers, outside first.

    The layer materials must be written first. An identical construction is
    reused and a different one of the same name replaced (see `add_or_replace`).

    Args:
        doc (EPDocument): The document to write to.
        name (str): The construction's name.
        layer_names (Sequence[str]): The material names, from outside to inside.

    Returns:
        IDFObject: The `Construction` object.
    """
    layers = {
        ("outside_layer" if i == 0 else f"layer_{i + 1}"): layer
        for i, layer in enumerate(layer_names)
    }
    return add_or_replace(doc, "Construction", name, **layers)
