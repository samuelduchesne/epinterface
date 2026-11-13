"""The base idfkit document every model is built on."""

from typing import Any

import idfkit
from idfkit import IDFDocument

_DESIGN_DAY_COMMON: dict[str, Any] = {
    "daily_dry_bulb_temperature_range": 0.0,
    "dry_bulb_temperature_range_modifier_type": "DefaultMultipliers",
    "humidity_condition_type": "Wetbulb",
    "barometric_pressure": 101281.0,
    "rain_indicator": "No",
    "snow_indicator": "No",
    "daylight_saving_time_indicator": "No",
}

# Field values of the objects the former packaged `Minimal.idf` held, keyed by
# the field names idfkit uses in the newest schema. # `new_document` also pre-adds SimulationControl, which `Minimal.idf` never had:
# it is removed, as the run configuration is the simulation's concern.
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
    doc: IDFDocument,
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


def minimal_document(version: tuple[int, int, int]) -> IDFDocument:
    """A new base document at EnergyPlus `version`: the minimal objects to run.

    The document is built programmatically from the version's own schema, so any
    version idfkit supports can be requested directly (no migration step).
    Every call returns a fresh document that the caller may edit freely.
    """
    doc = idfkit.new_document(version)
    for baseline_type in ("SimulationControl", "Building", "GlobalGeometryRules"):
        for obj in list(doc[baseline_type]):
            doc.removeidfobject(obj)
    _add_objects(doc)
    return doc
