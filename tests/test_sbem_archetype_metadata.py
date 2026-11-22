"""Archetype-level metadata (UP-9)."""

import gzip
from pathlib import Path

import pytest
from pydantic import ValidationError

from epinterface.sbem.archetype import Archetype, ZoneGroup
from tests.sbem_helpers import load_zone

DATA = Path(__file__).parent / "data"


def _archetype(**fields) -> Archetype:
    return Archetype(
        Name="office", Groups=[ZoneGroup(Name="all", Zone=load_zone())], **fields
    )


def test_defaults_unknown():
    """An archetype without metadata has none."""
    a = _archetype()
    assert (a.YearFrom, a.YearTo, a.Version, a.Lifespan) == (None, None, None, None)
    assert a.Country == a.ClimateZone == a.Authors == a.AuthorEmails == []
    assert (a.Category, a.Comment, a.DataSource) == (None, None, None)


def test_round_trip(tmp_path: Path):
    """Metadata survives save and load."""
    a = _archetype(
        YearFrom=1946,
        YearTo=1970,
        Country=["CA"],
        ClimateZone=["6A"],
        Authors=["A. Author"],
        AuthorEmails=["a@example.org"],
        Version="v1.0",
        Lifespan=60,
        Category="Office",
        Comment="Post-war office",
        DataSource="Survey",
    )
    assert Archetype.load(a.save(tmp_path / "a.sbem.json")) == a


def test_years_ordered():
    """The construction period is not reversed."""
    with pytest.raises(ValidationError, match="YearFrom"):
        _archetype(YearFrom=2000, YearTo=1990)


def test_v1_0_file_loads_without_metadata(tmp_path: Path):
    """A 1.0 file has no metadata and still loads."""
    path = tmp_path / "v1_0.sbem.json"
    path.write_bytes(
        gzip.decompress((DATA / "archetype_v1_0.sbem.json.gz").read_bytes())
    )
    a = Archetype.load(path)
    assert a.Authors == [] and a.YearFrom is None
