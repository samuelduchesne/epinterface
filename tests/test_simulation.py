"""The shared simulation helpers, without running EnergyPlus."""

import sqlite3
from pathlib import Path

import pytest

from epinterface.simulation import SQLResultFile, detach_sql, read_warnings


def _results_file(path: Path) -> Path:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
    conn.close()
    return path


def test_detach_sql_reads_a_private_copy(tmp_path: Path):
    """The original is closed; the copy lives elsewhere and is deleted on close."""
    original = SQLResultFile(_results_file(tmp_path / "eplus.sql"))

    detached = detach_sql(original)

    with pytest.raises(sqlite3.ProgrammingError):
        original.query("SELECT 1")
    assert not detached.path.is_relative_to(tmp_path)
    assert detached.query("SELECT x FROM t") == [(42,)]
    (tmp_path / "eplus.sql").unlink()  # the run directory can go away
    assert detached.query("SELECT x FROM t") == [(42,)]
    detached.close()
    assert not detached.path.exists()


def test_read_warnings_concatenates_err_files(tmp_path: Path):
    """Every .err file under the directory is read, in path order."""
    (tmp_path / "a.err").write_text("first")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.err").write_text("second")
    assert read_warnings(tmp_path) == "first\nsecond"
