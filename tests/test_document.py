"""Tests for idfkit document loading."""

import pytest

from epinterface.data import EnergyPlusArtifactDir
from epinterface.document import load_base_document
from epinterface.settings import energyplus_settings

MINIMAL = EnergyPlusArtifactDir / "Minimal.idf"


def test_load_base_document_same_version():
    """Loading at the file's own version does not migrate."""
    doc = load_base_document(MINIMAL, (22, 2, 0))
    assert doc.version == (22, 2, 0)


def test_load_base_document_migrates_to_newer():
    """Older files are migrated up to the requested version."""
    doc = load_base_document(MINIMAL, energyplus_settings.version_tuple)
    assert doc.version == energyplus_settings.version_tuple


def test_load_base_document_rejects_downgrade():
    """Downgrading is not supported."""
    with pytest.raises(ValueError, match="downgrading"):
        load_base_document(MINIMAL, (9, 0, 0))
