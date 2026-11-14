"""Running EnergyPlus on idfkit documents, shared by the sbem and climate_studio builders.

Holds the output objects both builders request, the simulation call with its
error handling, the `.err` reader and the lifetime handling of the SQLite
results (`detach_sql`).
"""

import os
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, get_args

from idfkit import SimulationError
from idfkit.simulation import find_energyplus, simulate
from idfkit.simulation.parsers.sql import SQLResult

from epinterface.document import EPDocument

# TODO: add the meters for HVAC systems
AvailableHourlyVariables = Literal[
    "Zone Mean Air Temperature",
    "Zone Air Relative Humidity",
    "Site Outdoor Air Drybulb Temperature",
    "Zone Mean Radiant Temperature",
]

AVAILABLE_HOURLY_VARIABLES = get_args(AvailableHourlyVariables)


# The outputs archetypal's `prep_outputs` added on top of the requested ones
# (`add_umi_template_outputs`, `add_profile_gas_elect_outputs`). They are kept
# so that a model requests the same outputs as before the idfkit migration.
_UMI_TEMPLATE_VARIABLES = (
    "Air System Outdoor Air Minimum Flow Fraction",
    "Air System Total Cooling Energy",
    "Air System Total Heating Energy",
    "Heat Exchanger Latent Effectiveness",
    "Heat Exchanger Sensible Effectiveness",
    "Heat Exchanger Total Heating Rate",
    "Water Heater Heating Energy",
    "Zone Ideal Loads Zone Total Cooling Energy",
    "Zone Ideal Loads Zone Total Heating Energy",
    "Zone Thermostat Cooling Setpoint Temperature",
    "Zone Thermostat Heating Setpoint Temperature",
)
_UMI_TEMPLATE_AND_PROFILE_METERS = (
    "Baseboard:EnergyTransfer",
    "Cooling:DistrictCooling",
    "Cooling:Electricity",
    "Cooling:EnergyTransfer",
    "Cooling:Gas",
    "CoolingCoils:EnergyTransfer",
    "Fans:Electricity",
    "HeatRejection:Electricity",
    "HeatRejection:EnergyTransfer",
    "Heating:DistrictHeating",
    "Heating:Electricity",
    "Heating:EnergyTransfer",
    "Heating:Gas",
    "HeatingCoils:EnergyTransfer",
    "Pumps:Electricity",
    "Refrigeration:Electricity",
    "Refrigeration:EnergyTransfer",
    "WaterSystems:EnergyTransfer",
    "Electricity:Facility",
    "Gas:Facility",
    "WaterSystems:Electricity",
)


def _filter_like_archetypal(
    items: Sequence[tuple[str, str]], wanted: Sequence[str]
) -> list[tuple[str, str]]:
    """Drop unwanted outputs the way the archetypal-based builder did.

    It removed unwanted objects from the list it was iterating over, so the
    object right after each removed one was never checked and always kept.
    Reproducing that keeps the requested outputs (and the run's output
    files) identical to the archetypal baseline.
    """
    kept: list[tuple[str, str]] = []
    skip_next = False
    for item in items:
        if skip_next or item[0] in wanted:
            kept.append(item)
            skip_next = False
        else:
            skip_next = True
    return kept


def add_output_objects(doc: EPDocument, desired_meters: Sequence[str]) -> None:
    """Request the simulation outputs archetypal's `prep_outputs` requested.

    The SQLite output (with tabular data), the HTML/CSV summary reports and the
    schedule and variable dictionaries, then the desired meters (monthly and
    hourly) and `AVAILABLE_HOURLY_VARIABLES` (hourly), filtered as before.

    Args:
        doc (EPDocument): The document to add the outputs to (modified in place).
        desired_meters (Sequence[str]): The meters the results postprocessing reads.
    """
    for obj_type, fields in (
        ("OutputControl:Table:Style", {"column_separator": "CommaAndHTML"}),
        ("Output:Table:SummaryReports", {"reports": [{"report_name": "AllSummary"}]}),
        ("Output:SQLite", {"option_type": "SimpleAndTabular"}),
    ):
        for existing in list(doc[obj_type]):
            doc.removeidfobject(existing)
        doc.add(obj_type, "", fields)
    doc.add("Output:Schedules", "", {"key_field": "Hourly"})
    doc.add("Output:VariableDictionary", "", {"key_field": "IDF"})

    variables = sorted({
        (variable, "Hourly")
        for variable in (*AVAILABLE_HOURLY_VARIABLES, *_UMI_TEMPLATE_VARIABLES)
    })
    meters = sorted(
        {
            (meter, frequency)
            for meter in desired_meters
            for frequency in ("Monthly", "Hourly")
        }
        | {(meter, "Monthly") for meter in _UMI_TEMPLATE_AND_PROFILE_METERS}
    )
    for variable, frequency in _filter_like_archetypal(
        variables, AVAILABLE_HOURLY_VARIABLES
    ):
        doc.add(
            "Output:Variable",
            "",
            {
                "key_value": "*",
                "variable_name": variable,
                "reporting_frequency": frequency,
            },
        )
    for meter, frequency in _filter_like_archetypal(meters, desired_meters):
        doc.add(
            "Output:Meter", "", {"key_name": meter, "reporting_frequency": frequency}
        )


class SQLResultFile(SQLResult):
    """A `SQLResult` that knows the file it reads.

    With `delete_on_close`, the file is deleted when the result is closed (or
    garbage collected): used for the private copies made by `detach_sql`.
    """

    def __init__(self, path: Path | str, *, delete_on_close: bool = False) -> None:
        """Open the SQLite results file at `path` read-only."""
        super().__init__(path)
        self.path = Path(path)
        self.delete_on_close = delete_on_close

    def close(self) -> None:
        """Close the connection; delete the file if `delete_on_close`."""
        super().close()
        if self.delete_on_close:
            self.path.unlink(missing_ok=True)


def run_energyplus(doc: EPDocument, epw_path: Path, output_dir: Path) -> SQLResultFile:
    """Simulate `doc` with the EnergyPlus of its release and open its SQLite results.

    The returned result holds an open connection to the `.sql` file in
    `output_dir`; close it (or `detach_sql` it) before deleting the directory,
    which Windows refuses while the file is open.

    Args:
        doc (EPDocument): The model to simulate.
        epw_path (Path): The weather file.
        output_dir (Path): The EnergyPlus run directory.

    Returns:
        sql (SQLResultFile): The open results database.

    Raises:
        SimulationError: If EnergyPlus fails.
        FileNotFoundError: If the simulation produced no SQLite file.
    """
    # The EnergyPlus of the document's own release, which is the configured one
    # for the documents epinterface builds.
    result = simulate(
        doc,
        weather=epw_path,
        output_dir=output_dir,
        energyplus=find_energyplus(version=doc.version),
    )
    if not result.success:
        msg = f"EnergyPlus failed in {result.run_dir}:\n{read_warnings(result.run_dir)}"
        raise SimulationError(msg, exit_code=result.exit_code, stderr=result.stderr)
    sql_path = result.sql_path
    if sql_path is None:
        msg = "Simulation produced no SQLite results file."
        raise FileNotFoundError(msg)
    return SQLResultFile(sql_path)


def read_warnings(output_dir: Path) -> str:
    """Get the EnergyPlus warning text written to a simulation directory.

    Args:
        output_dir (Path): The simulation's output directory.

    Returns:
        str: The concatenated text of every `*.err` file under `output_dir`.
    """
    err_files = sorted(output_dir.rglob("*.err"))
    return "\n".join(f.read_text() for f in err_files)


def detach_sql(sql: SQLResultFile) -> SQLResultFile:
    """Close `sql` and reopen a private copy of its file.

    Use it before the run directory is deleted (e.g. a `TemporaryDirectory`):
    no handle is left open on the directory (Windows refuses to delete an
    open file) while the results stay queryable.

    The copy is a `tempfile.mkstemp` file in the system temporary directory,
    deleted when the returned result is closed or garbage collected.

    Args:
        sql (SQLResultFile): The open results of a run; closed here.

    Returns:
        sql (SQLResultFile): The results, read from the copy.
    """
    if sql.delete_on_close:
        # Already a private copy: closing it would delete the file to copy.
        return sql
    sql.close()
    fd, copy_path = tempfile.mkstemp(prefix="epinterface-", suffix=".sql")
    os.close(fd)
    try:
        shutil.copyfile(sql.path, copy_path)
    except BaseException:
        Path(copy_path).unlink(missing_ok=True)
        raise
    return SQLResultFile(copy_path, delete_on_close=True)
