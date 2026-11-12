"""Regression test against fixtures captured with archetypal (EnergyPlus 25.2.0)."""

from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from epinterface.settings import energyplus_settings
from tests.regression.configs import HOURLY_NAMES, REGRESSION_CONFIGS
from tests.regression.summary import zone_geometry_summary

FIXTURES = Path(__file__).parent / "data" / "regression"

pytestmark = pytest.mark.skipif(
    energyplus_settings.energyplus_version != "25.2.0",
    reason="Regression fixtures are captured with EnergyPlus 25.2.0",
)


@pytest.mark.parametrize("key", list(REGRESSION_CONFIGS))
def test_regression(key, preseeded_readonly_db, tmp_path):
    """Current outputs must match the frozen baseline."""
    model, oh = REGRESSION_CONFIGS[key](preseeded_readonly_db)
    r = model.run(eplus_parent_dir=tmp_path, overheating_config=oh)
    base = FIXTURES / key
    assert_series_equal(
        r.energy_and_peak,
        pd.read_parquet(base / "energy_and_peak.parquet").iloc[:, 0],
        rtol=1e-3,
        atol=1e-6,
        check_names=False,
        check_series_type=False,
    )
    hourly = r.hourly_timeseries(HOURLY_NAMES)
    assert_frame_equal(
        hourly,
        pd.read_parquet(base / "hourly.parquet"),
        rtol=1e-3,
        atol=1e-6,
        check_freq=False,
    )
    sql_path = next((tmp_path / "eplus_simulation").rglob("*.sql"))
    assert_frame_equal(
        zone_geometry_summary(sql_path),
        pd.read_parquet(base / "geometry.parquet"),
        rtol=1e-9,
        atol=0.01,
    )
    if oh is not None:
        assert r.overheating_results is not None
        for name in ("edh", "basic_oh", "hi", "consecutive_e_zone"):
            assert_frame_equal(
                getattr(r.overheating_results, name),
                pd.read_parquet(base / f"{name}.parquet"),
                rtol=1e-3,
                atol=1e-6,
            )
