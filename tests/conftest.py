"""Fixtures for the tests."""

import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from idfkit import IDFDocument

from epinterface.document import minimal_document
from epinterface.geometry import ShoeboxGeometry
from epinterface.sbem.prisma.client import PrismaSettings
from epinterface.sbem.prisma.seed_fns import (
    create_dhw_systems,
    create_envelope,
    create_hvac_systems,
    create_operations,
    create_schedules,
    create_space_use_children,
    create_zone,
)
from epinterface.settings import energyplus_settings
from epinterface.simulation import SQLResultFile


@pytest.fixture(scope="package")
def preseeded_readonly_db():
    """Create a database with schedules and space use children to be used in other tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        database_path = Path(temp_dir) / "test.db"
        settings = PrismaSettings.New(
            database_path=database_path, if_exists="raise", auto_register=False
        )
        with settings.db:
            create_schedules(settings.db)
            last_space_use_name = create_space_use_children(settings.db)
            last_hvac_name = create_hvac_systems(settings.db)
            last_dhw_name = create_dhw_systems(settings.db)
            _last_ops_name = create_operations(
                settings.db, last_space_use_name, last_hvac_name, last_dhw_name
            )

            create_envelope(settings.db)
            create_zone(settings.db)

            yield settings.db


@pytest.fixture(scope="function")
def doc() -> IDFDocument:
    """A fresh minimal idfkit document at the configured version."""
    return minimal_document(energyplus_settings.version_tuple)


@pytest.fixture(scope="function")
def shoebox_geometry_by_storey_no_basement_or_attic_or_neighbors():
    """A shoebox that does NOT have a core/perim split."""
    geometry = ShoeboxGeometry(
        x=-5,
        y=-5,
        w=10,
        d=10,
        h=3,
        wwr=0.2,
        num_stories=2,
        basement=False,
        zoning="by_storey",
        roof_height=None,
    )
    return geometry


@pytest.fixture(scope="function")
def shoebox_geometry_core_perim_no_basement_or_attic_or_neighbors():
    """A shoebox that has a core/perim split."""
    geometry = ShoeboxGeometry(
        x=-5,
        y=-5,
        w=10,
        d=10,
        h=3,
        wwr=0.2,
        num_stories=2,
        basement=False,
        zoning="core/perim",
        roof_height=None,
    )

    return geometry


@dataclass
class SQLCleanupSpy:
    """Results files found inside temporary directories as they are deleted."""

    checked: list[Path] = field(default_factory=list)
    still_open: list[Path] = field(default_factory=list)


def _is_open(sql: SQLResultFile) -> bool:
    try:
        sql.query("SELECT 1")
    except sqlite3.ProgrammingError:
        return False
    return True


@pytest.fixture
def sql_cleanup_spy(monkeypatch: pytest.MonkeyPatch) -> SQLCleanupSpy:
    """Record whether simulation results are still open when their temp dir is deleted.

    An open results file blocks the deletion on Windows; this catches it on any OS.
    """
    spy = SQLCleanupSpy()
    created: list[SQLResultFile] = []
    original_init = SQLResultFile.__init__

    def recording_init(self: SQLResultFile, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        created.append(self)

    class CheckedTemporaryDirectory(tempfile.TemporaryDirectory):
        def __exit__(self, *exc) -> None:
            root = Path(self.name).resolve()
            for sql in created:
                if sql.path.resolve().is_relative_to(root):
                    spy.checked.append(sql.path)
                    if _is_open(sql):
                        spy.still_open.append(sql.path)
            super().__exit__(*exc)

    monkeypatch.setattr(SQLResultFile, "__init__", recording_init)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", CheckedTemporaryDirectory)
    return spy
