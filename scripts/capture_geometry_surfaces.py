"""Capture geomeppy's shoebox surfaces as reference data for the idfkit geometry.

The shoebox geometry was built with archetypal/geomeppy until commit 0b2fafd.
This script loads `epinterface/geometry.py` from that commit, builds every case
in `GEOMETRY_SURFACE_CASES` with it, and writes a name-independent description
of every surface (see `tests.regression.summary.surface_records`) to
`tests/data/regression/geometry_surfaces.json`.

It is kept as provenance for the committed fixture and is not part of the test
suite. archetypal is no longer a dependency of epinterface (2.0.0), so run it
ad hoc with a temporary pin, with the git history available:

    EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run --with archetypal==2.18.10 python scripts/capture_geometry_surfaces.py
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import idfkit
from archetypal.idfclass import IDF

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from epinterface.data import EnergyPlusArtifactDir  # noqa: E402
from epinterface.settings import energyplus_settings  # noqa: E402
from tests.regression.configs import GEOMETRY_SURFACE_CASES  # noqa: E402
from tests.regression.summary import surface_records  # noqa: E402

GEOMEPPY_COMMIT = "0b2fafd"
OUTPUT = ROOT / "tests" / "data" / "regression" / "geometry_surfaces.json"


def _load_geomeppy_geometry(temp_dir: Path):
    """Import `epinterface/geometry.py` as it was at GEOMEPPY_COMMIT."""
    source = subprocess.run(  # noqa: S603
        ["git", "show", f"{GEOMEPPY_COMMIT}:epinterface/geometry.py"],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    path = temp_dir / "geomeppy_geometry.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("geomeppy_geometry", path)
    assert spec is not None and spec.loader is not None  # noqa: S101
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    """Capture the surfaces of every case."""
    records: dict[str, list[dict]] = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        old = _load_geomeppy_geometry(Path(temp_dir))
        for key, geometry in GEOMETRY_SURFACE_CASES.items():
            print(f"capturing {key}")
            scene = geometry.scene_context
            old_geometry = old.ShoeboxGeometry(
                **geometry.model_dump(exclude={"scene_context"}),
                scene_context=old.SceneContext(**dict(scene)) if scene else None,
            )
            target = Path(temp_dir) / "shoebox.idf"
            shutil.copy(EnergyPlusArtifactDir / "Minimal.idf", target)
            idf = IDF(
                target.as_posix(),
                as_version=energyplus_settings.energyplus_version,  # pyright: ignore [reportArgumentType]
                file_version=energyplus_settings.energyplus_version,
                prep_outputs=False,
                output_directory=temp_dir,
            )
            idf = old_geometry.add(idf)
            built = Path(temp_dir) / "built.idf"
            built.write_text(idf.idfstr())
            # archetypal keeps the source file's Version line; the objects are 25.2-shaped
            doc = idfkit.load_idf(str(built), version=energyplus_settings.version_tuple)
            records[key] = surface_records(doc)
    OUTPUT.write_text(json.dumps(records, indent=1) + "\n")


if __name__ == "__main__":
    main()
