"""Loading of idfkit documents at a target EnergyPlus version."""

from pathlib import Path

import idfkit
from idfkit import IDFDocument
from idfkit.simulation import find_energyplus


def load_base_document(path: Path, version: tuple[int, int, int]) -> IDFDocument:
    """Load an IDF and bring it to `version`.

    Files older than `version` are migrated forward with the EnergyPlus
    transition binaries (`idfkit.MigrationError` propagates on failure).

    Raises:
        ValueError: If the file's version is newer than `version`.
    """
    doc = idfkit.load_idf(str(path))
    if doc.version == version:
        return doc
    if doc.version > version:
        msg = (
            f"{path} is EnergyPlus {doc.version}, newer than the target {version}; "
            "downgrading is not supported."
        )
        raise ValueError(msg)
    energyplus = find_energyplus(version=idfkit.version_string(version))
    report = idfkit.migrate(doc, version, energyplus=energyplus)
    return report.migrated_model if report.migrated_model is not None else doc
