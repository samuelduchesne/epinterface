"""Capture the regression baseline fixtures (run under archetypal, EnergyPlus 25.2.0).

It is kept as provenance for the committed fixtures and is not part of the test
suite. It needs the pre-migration stack: archetypal is no longer a dependency of
epinterface (2.0.0), and this script calls the pre-2.0 epinterface API, so run
it from a checkout of commit b4f9f6a (the last one that still builds with archetypal) with a temporary pin:

    EPINTERFACE_ENERGYPLUS_VERSION=25.2.0 uv run --with archetypal==2.18.10 python scripts/capture_regression_baseline.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd
from archetypal.idfclass import IDF
from pandas.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from epinterface.data import EnergyPlusArtifactDir  # noqa: E402
from epinterface.sbem.prisma.client import PrismaSettings  # noqa: E402
from epinterface.sbem.prisma.seed_fns import (  # noqa: E402
    create_dhw_systems,
    create_envelope,
    create_hvac_systems,
    create_operations,
    create_schedules,
    create_space_use_children,
    create_zone,
)
from epinterface.settings import energyplus_settings  # noqa: E402
from tests.regression.configs import (  # noqa: E402
    GEOMETRY_GRID,
    HOURLY_NAMES,
    REGRESSION_CONFIGS,
)
from tests.regression.summary import zone_geometry_summary, zone_names  # noqa: E402

FIXTURES = ROOT / "tests" / "data" / "regression"


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write a frame and verify it round-trips losslessly."""
    df.to_parquet(path)
    assert_frame_equal(df, pd.read_parquet(path), check_freq=False)


def _capture_geometry_baseline() -> None:
    zone_names_by_key: dict[str, list[str]] = {}
    shading_counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        for key, geometry in GEOMETRY_GRID.items():
            target = Path(temp_dir) / f"{key.replace('/', '_')}.idf"
            shutil.copy(EnergyPlusArtifactDir / "Minimal.idf", target)
            idf = IDF(
                target.as_posix(),
                as_version=energyplus_settings.energyplus_version,  # pyright: ignore [reportArgumentType]
                file_version=energyplus_settings.energyplus_version,
                prep_outputs=True,
                output_directory=temp_dir,
            )
            idf = geometry.add(idf)
            zone_names_by_key[key] = zone_names(idf.idfstr())
            # archetypal/geomeppy emit neighbours as Shading:Site:Detailed; count both
            # detailed shading types so the number is independent of the type used.
            shading_counts[key] = sum(
                len(idf.idfobjects[t])
                for t in ("SHADING:BUILDING:DETAILED", "SHADING:SITE:DETAILED")
            )
    (FIXTURES / "geometry_baseline.json").write_text(
        json.dumps(
            {"zone_names": zone_names_by_key, "shading_counts": shading_counts},
            indent=1,
        )
    )


def _capture_config(key: str, db) -> None:
    out = FIXTURES / key
    out.mkdir(parents=True, exist_ok=True)
    model, oh = REGRESSION_CONFIGS[key](db)
    with tempfile.TemporaryDirectory() as temp_dir:
        parent = Path(temp_dir)
        r = model.run(eplus_parent_dir=parent, overheating_config=oh)
        run_dir = parent / "eplus_simulation"
        _write_parquet(
            pd.Series(
                r.energy_and_peak.to_numpy(), index=r.energy_and_peak.index
            ).to_frame("value"),
            out / "energy_and_peak.parquet",
        )
        _write_parquet(r.hourly_timeseries(HOURLY_NAMES), out / "hourly.parquet")
        _write_parquet(
            zone_geometry_summary(next(run_dir.rglob("*.sql"))),
            out / "geometry.parquet",
        )
        # The IDF EnergyPlus ran lives in the per-run subdirectory (not the
        # template copy placed directly in ``run_dir``).
        idf_path = next(run_dir.glob("*/*.idf"))
        shutil.copy(idf_path, out / "built.idf")
        if oh is not None:
            assert r.overheating_results is not None  # noqa: S101
            for name in ("edh", "basic_oh", "hi", "consecutive_e_zone"):
                _write_parquet(
                    getattr(r.overheating_results, name), out / f"{name}.parquet"
                )


def main() -> None:
    """Capture all fixtures."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        settings = PrismaSettings.New(
            database_path=Path(temp_dir) / "test.db",
            if_exists="raise",
            auto_register=False,
        )
        with settings.db:
            create_schedules(settings.db)
            last_space_use_name = create_space_use_children(settings.db)
            last_hvac_name = create_hvac_systems(settings.db)
            last_dhw_name = create_dhw_systems(settings.db)
            create_operations(
                settings.db, last_space_use_name, last_hvac_name, last_dhw_name
            )
            create_envelope(settings.db)
            create_zone(settings.db)
            for key in REGRESSION_CONFIGS:
                print(f"capturing {key}")
                _capture_config(key, settings.db)
    _capture_geometry_baseline()


if __name__ == "__main__":
    main()
