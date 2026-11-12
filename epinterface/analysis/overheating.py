"""A module for computing and analyzing metrics related to overheating, such as heat index, exceedance hours, etc."""

from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
import pandas as pd
from idfkit.simulation.parsers.sql import SQLResult
from numpy.typing import NDArray
from pydantic import BaseModel, Field

from epinterface.results import timeseries_frame

# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class CountFailureCriterion(BaseModel):
    """Simple check: fail if total hours above/below threshold across the year exceeds max."""

    max_hours: float


class ExceedanceCriterion(BaseModel):
    """Fail if EDH (degree-hours) exceeds max."""

    max_deg_hours: float


class StreakCriterion(BaseModel):
    """Fail if count of streaks longer than min_streak_length exceeds max_count."""

    min_streak_length_hours: float
    max_count: float


class IntegratedStreakCriterion(BaseModel):
    """Fail if sum of integrals (for streaks longer than min) exceeds max_integral."""

    min_streak_length_hours: float
    max_integral: float


class ThresholdWithCriteria(BaseModel):
    """A temperature threshold with optional failure criteria."""

    threshold: float
    exceedance_failure: ExceedanceCriterion | None = None  # EDH degree-hours
    streak_failure: StreakCriterion | None = None  # count of long streaks
    integrated_streak_failure: IntegratedStreakCriterion | None = None
    count_failure: CountFailureCriterion | None = None  # simple hours above threshold


class HeatIndexCriteria(BaseModel):
    """Criteria for heat index categories (fixed NOAA categories)."""

    extreme_danger_hours: float | None = None  # fail if hours in Extreme Danger > this
    danger_or_worse_hours: float | None = (
        None  # fail if hours in Danger+Extreme Danger > this
    )
    caution_or_worse_hours: float | None = (
        None  # fail if hours in Caution+Extreme Caution+Danger+Extreme Danger > this
    )


class ThermalComfortAssumptions(BaseModel):
    """MET, CLO, v for SET (Standard Effective Temperature) calculation in EDH."""

    met: float = 1.1
    clo: float = 0.5
    v: float = 0.1


class OverheatingAnalysisConfig(BaseModel):
    """Configuration for overheating analysis and zone-at-risk assessment."""

    heat_thresholds: tuple[ThresholdWithCriteria, ...] = Field(
        default_factory=lambda: (
            ThresholdWithCriteria(threshold=26.0),
            ThresholdWithCriteria(threshold=30.0),
            ThresholdWithCriteria(threshold=35.0),
        )
    )
    cold_thresholds: tuple[ThresholdWithCriteria, ...] = Field(
        default_factory=lambda: (
            ThresholdWithCriteria(threshold=10.0),
            ThresholdWithCriteria(threshold=5.0),
        )
    )
    heat_index_criteria: HeatIndexCriteria = Field(default_factory=HeatIndexCriteria)
    thermal_comfort: ThermalComfortAssumptions = Field(
        default_factory=ThermalComfortAssumptions
    )


def calculate_hi_categories(
    dbt_mat: NDArray[np.float64],
    rh_mat: NDArray[np.float64],
    zone_names: list[str] | None = None,
    zone_weights: NDArray[np.float64] | None = None,
) -> pd.DataFrame:
    """Computes heat index per hour across all zones and bins into 5 categories (sum = 8760), then takes the most common category for each timestep and the worst category for each timestep.

    Uses Rothfusz regression and NOAA categories:
      - Extreme Danger: ≥130°F
      - Danger: 105 to 129°F
      - Extreme Caution: 90 to 104°F
      - Caution: 80 to 89°F
      - Normal: <80°F

    Args:
        dbt_mat (np.ndarray): The dry bulb temperature matrix (zones x timesteps).
        rh_mat (np.ndarray): The relative humidity matrix (zones x timesteps).
        zone_names (list[str] | None): The names of the zones. If None, the zones will be named "Zone 001", "Zone 002", etc.
        zone_weights (NDArray[np.float64] | None): The weights of the zones. If None, the zones will be weighted equally when summing the heat index.

    Returns:
        cat_counts (pd.DataFrame): A dataframe with the count of timesteps that the building is in each category, using various aggregation methods.

    """
    zone_names_ = (
        [f"Zone {i:03d}" for i in range(dbt_mat.shape[0])]
        if zone_names is None
        else zone_names
    )
    zone_weights_ = (
        zone_weights if zone_weights is not None else np.ones(dbt_mat.shape[0])
    )
    if len(zone_names_) != len(zone_weights_):
        msg = f"Zone names and zone weights must have the same length. Got {len(zone_names_)} zone names and {len(zone_weights_)} zone weights."
        raise ValueError(msg)
    normalized_zone_weights: NDArray[np.float64] = zone_weights_ / zone_weights_.sum()
    n_zones = len(zone_weights_)
    check_timeseries_shape(dbt_mat, expected_zones=n_zones, expected_timesteps=8760)
    check_timeseries_shape(rh_mat, expected_zones=n_zones, expected_timesteps=8760)
    # we use an index map to solve ties and guarantee the "worst" category in the event of a tie is always chosen.
    cat_index_map = {
        "Extreme Danger": 4,
        "Danger": 3,
        "Extreme Caution": 2,
        "Caution": 1,
        "Normal": 0,
    }

    def compute_hi(temp_c, rh):
        # Convert to Fahrenheit
        temp_f = temp_c * 9 / 5 + 32
        hi_f = (
            -42.379
            + 2.04901523 * temp_f
            + 10.14333127 * rh
            - 0.22475541 * temp_f * rh
            - 6.83783e-3 * temp_f**2
            - 5.481717e-2 * rh**2
            + 1.22874e-3 * temp_f**2 * rh
            + 8.5282e-4 * temp_f * rh**2
            - 1.99e-6 * temp_f**2 * rh**2
        )
        return hi_f

    def compute_category(hi_f):
        return np.where(
            hi_f >= 130,
            cat_index_map["Extreme Danger"],
            np.where(
                hi_f >= 105,
                cat_index_map["Danger"],
                np.where(
                    hi_f >= 90,
                    cat_index_map["Extreme Caution"],
                    np.where(
                        hi_f >= 80, cat_index_map["Caution"], cat_index_map["Normal"]
                    ),
                ),
            ),
        )

    heat_index_mat = compute_hi(dbt_mat, rh_mat)
    zone_weighted_heat_index = heat_index_mat * normalized_zone_weights.reshape(-1, 1)
    aggregated_heat_index = zone_weighted_heat_index.sum(axis=0)

    bins_by_hour_and_zone = compute_category(heat_index_mat)
    bins_by_hour_building = compute_category(aggregated_heat_index)

    df = pd.DataFrame(
        bins_by_hour_and_zone,
        index=zone_names_,
        columns=pd.RangeIndex(0, 8760),
    )

    val_counts_by_timestep = [df.loc[zone].value_counts() for zone in zone_names_]
    cat_counts_by_zone = (
        pd
        .concat(val_counts_by_timestep, axis=1, keys=zone_names_, names=["Group"])
        .fillna(0)
        .sort_index()
    )
    cat_counts_by_zone = cat_counts_by_zone.rename(
        index={ix: val for val, ix in cat_index_map.items()}
    )
    cat_counts_by_zone.index.name = "Heat Index Category"

    modes_by_timestep: pd.DataFrame | pd.Series = cast(
        pd.DataFrame | pd.Series, df.mode(axis=0)
    )

    worst_by_timestep = df.max(axis=0)

    # since some timesteps may have multiple modes, we choose the mode with the highest count.
    if isinstance(modes_by_timestep, pd.Series):
        modes = modes_by_timestep
    else:
        modes = modes_by_timestep.max(axis=0)

    val_count_modes = modes.value_counts()
    val_count_modes = val_count_modes.rename(
        index={ix: val for val, ix in cat_index_map.items()}
    )

    val_count_worst = worst_by_timestep.value_counts()
    val_count_worst = val_count_worst.rename(
        index={ix: val for val, ix in cat_index_map.items()}
    )

    val_counts_building = pd.Series(
        bins_by_hour_building, name="Building"
    ).value_counts()
    val_counts_building = val_counts_building.rename(
        index={ix: val for val, ix in cat_index_map.items()}
    )

    for cat in cat_index_map:
        if cat not in val_count_modes.index:
            val_count_modes[cat] = 0
        if cat not in val_count_worst.index:
            val_count_worst[cat] = 0
        if cat not in val_counts_building.index:
            val_counts_building[cat] = 0

    building_counts = pd.concat(
        [val_count_modes, val_count_worst, val_counts_building],
        axis=1,
        keys=["Modal per Timestep", "Worst per Timestep", "Zone Weighted"],
    ).loc[list(cat_index_map.keys())]
    building_counts.index.name = "Heat Index Category"
    building_counts.columns.name = "Group"

    return pd.concat(
        [building_counts.T, cat_counts_by_zone.T],
        axis=0,
        names=["Aggregation Unit"],
        keys=["Building", "Zone"],
    ).rename(columns={c: f"{c} [hr]" for c in cat_index_map})


def check_timeseries_shape(
    ts: np.ndarray, expected_zones: int | None = None, expected_timesteps: int = 8760
) -> None:
    """Checks if the timeseries is a 2D array with shape (zones, timesteps).

    Args:
        ts (np.ndarray): The timeseries to check.
        expected_zones (int | None): The expected number of zones. If None, the number of zones will not be checked.
        expected_timesteps (int): The expected number of timesteps.

    Raises:
        ValueError: If the timeseries is not a 2D array with shape (zones, timesteps).
        ValueError: If the timeseries has a different number of zones than the expected number of zones.
        ValueError: If the timeseries has a different number of timesteps than the expected number of timesteps.

    Returns:
        None
    """
    if ts.ndim != 2:
        msg = f"Timeseries must be a 2D array with shape (zones, timesteps). Got shape {ts.shape}."
        raise ValueError(msg)
    if ts.shape[0] != expected_zones and expected_zones is not None:
        msg = f"Timeseries must have {expected_zones} zones. Got {ts.shape[0]} zones."
        raise ValueError(msg)
    if ts.shape[1] != expected_timesteps:
        msg = f"Timeseries must have {expected_timesteps} timesteps. Got {ts.shape[1]} timesteps."
        raise ValueError(msg)


def calculate_edh(
    dbt_mat: NDArray[np.float64],
    rh_mat: NDArray[np.float64],
    mrt_mat: NDArray[np.float64],
    heat_thresholds: tuple[ThresholdWithCriteria, ...],
    cold_thresholds: tuple[ThresholdWithCriteria, ...],
    thermal_comfort: ThermalComfortAssumptions,
    zone_names: list[str] | None = None,
    zone_weights: NDArray[np.float64] | None = None,
) -> pd.DataFrame:
    """Calculates Exceedance Degree Hours (EDH) per threshold for heating and cooling.

    For each heating threshold T, computes integral of max(0, SET - T) over the year.
    For each cooling threshold T, computes integral of max(0, T - SET) over the year.

    When aggregating at the building scale, we compute:
        - Zone Weighted: The weighted average of the EDHs for all zones.
        - Worst Zone: The EDH for the zone with the worst EDH.

    Parameters:
        dbt_mat: The dry bulb temperature matrix (zones x timesteps).
        rh_mat: The relative humidity matrix (zones x timesteps).
        mrt_mat: The mean radiant temperature matrix (zones x timesteps).
        heat_thresholds: Thresholds for heat exceedance (SET above threshold).
        cold_thresholds: Thresholds for cold exceedance (SET below threshold).
        thermal_comfort: MET, CLO, v for SET calculation.
        zone_names: The names of the zones.
        zone_weights: The weights of the zones.

    Returns:
        pd.DataFrame: MultiIndex (Polarity, Threshold [degC], Aggregation Unit, Group),
            column "EDH [degC-hr]".
    """
    from pythermalcomfort.models import set_tmp

    _zone_weights = (
        zone_weights if zone_weights is not None else np.ones(dbt_mat.shape[0])
    )
    _zone_names = (
        [f"Zone {i:03d}" for i in range(dbt_mat.shape[0])]
        if zone_names is None
        else zone_names
    )

    zone_names_len = len(_zone_names)
    if zone_names_len != len(_zone_weights):
        msg = f"Zone names and zone weights must have the same length. Got {zone_names_len} zone names and {len(_zone_weights)} zone weights."
        raise ValueError(msg)

    check_timeseries_shape(
        dbt_mat, expected_zones=zone_names_len, expected_timesteps=8760
    )
    check_timeseries_shape(
        mrt_mat,
        expected_zones=zone_names_len,
        expected_timesteps=8760,
    )
    check_timeseries_shape(
        rh_mat, expected_zones=zone_names_len, expected_timesteps=8760
    )

    SETs = np.stack(
        [
            set_tmp(
                tdb=dbt_row,
                tr=mrt_row,
                rh=relative_humidity_row,
                met=thermal_comfort.met,
                clo=thermal_comfort.clo,
                v=thermal_comfort.v,
                limit_inputs=False,  # TODO: remove this, or set it and handle NaN cases appropriately.
            )["set"]
            for dbt_row, mrt_row, relative_humidity_row in zip(
                dbt_mat,
                mrt_mat,
                rh_mat,
                strict=False,
            )
        ],
        axis=0,
    )

    heat_thresh_vals = np.array([t.threshold for t in heat_thresholds])
    cool_thresh_vals = np.array([t.threshold for t in cold_thresholds])

    # hot_edh: (n_heat_thresholds, n_zones), cold_edh: (n_cool_thresholds, n_zones)
    hot_edh_by_zone = np.maximum(0, SETs - heat_thresh_vals.reshape(-1, 1, 1)).sum(
        axis=2
    )
    cold_edh_by_zone = np.maximum(0, cool_thresh_vals.reshape(-1, 1, 1) - SETs).sum(
        axis=2
    )

    normalized_zone_weights: NDArray[np.float64] = _zone_weights / _zone_weights.sum()

    # Build zone-level DataFrames
    hot_edh_df = pd.DataFrame(
        hot_edh_by_zone,
        index=pd.Index(heat_thresh_vals, name="Threshold [degC]"),
        columns=pd.Index(_zone_names, name="Zone"),
        dtype=np.float64,
    )
    cold_edh_df = pd.DataFrame(
        cold_edh_by_zone,
        index=pd.Index(cool_thresh_vals, name="Threshold [degC]"),
        columns=pd.Index(_zone_names, name="Zone"),
        dtype=np.float64,
    )

    # Building aggregations
    weighted_hot = hot_edh_df.mul(normalized_zone_weights).sum(axis=1)
    weighted_cold = cold_edh_df.mul(normalized_zone_weights).sum(axis=1)
    worst_hot = hot_edh_df.max(axis=1)
    worst_cold = cold_edh_df.max(axis=1)

    hot_whole_bldg = pd.DataFrame({
        "Zone Weighted": weighted_hot,
        "Worst Zone": worst_hot,
    })
    cold_whole_bldg = pd.DataFrame({
        "Zone Weighted": weighted_cold,
        "Worst Zone": worst_cold,
    })

    # Stack to match basic_oh structure: (Polarity, Threshold, Aggregation Unit, Group)
    hot_zone = hot_edh_df.T
    cold_zone = cold_edh_df.T

    combined = pd.concat(
        [
            pd.concat(
                [hot_whole_bldg.T, hot_zone],
                axis=0,
                keys=["Building", "Zone"],
                names=["Aggregation Unit", "Group"],
            ),
            pd.concat(
                [cold_whole_bldg.T, cold_zone],
                axis=0,
                keys=["Building", "Zone"],
                names=["Aggregation Unit", "Group"],
            ),
        ],
        axis=1,
        keys=["Overheat", "Underheat"],
        names=["Polarity", "Threshold [degC]"],
    ).T

    combined.columns.names = ["Aggregation Unit", "Group"]
    combined = (
        cast(
            pd.Series,
            cast(pd.DataFrame, combined.stack(future_stack=True)).stack(
                future_stack=True
            ),
        )
        .rename("EDH [degC-hr]")
        .dropna()
        .to_frame()
        .reorder_levels(
            ["Polarity", "Threshold [degC]", "Aggregation Unit", "Group"], axis=0
        )
    )
    return combined


def calculate_basic_overheating_stats(
    dbt_mat: NDArray[np.float64],
    heat_thresholds: tuple[ThresholdWithCriteria, ...],
    cold_thresholds: tuple[ThresholdWithCriteria, ...],
    zone_names: list[str] | None = None,
    zone_weights: NDArray[np.float64] | None = None,
) -> pd.DataFrame:
    """Calculates basic overheating hours by zone and for the whole building.

    When aggregating at the building scale, we compute a few variants:
        - Any Zone: The number of timesteps that the threshold is violated for any zone in the whole building.
        - Zone Weighted: The number of timesteps that the threshold is violated for the weighted average of all zones.
        - Worst Zone: The number of timesteps that the threshold is violated for the zone with the worst number of violations.

    Args:
        dbt_mat: The dry bulb temperature matrix (zones x timesteps).
        heat_thresholds: Thresholds for overheating.
        cold_thresholds: Thresholds for undercooling.
        zone_names: The names of the zones. If None, the zones will be named "Zone 000", "Zone 001", etc.
        zone_weights: The weights of the zones. If None, the zones will be weighted equally.

    Returns:
        hours (pd.DataFrame): A dataframe with the overheating and undercooling hours by threshold for the whole building and by zone and threshold for each zone.

    """
    overheat_thresholds = np.array([t.threshold for t in heat_thresholds])
    undercool_thresholds = np.array([t.threshold for t in cold_thresholds])

    zone_names_ = (
        [f"Zone {i:03d}" for i in range(dbt_mat.shape[0])]
        if zone_names is None
        else zone_names
    )
    zone_weights_ = (
        zone_weights if zone_weights is not None else np.ones(dbt_mat.shape[0])
    )
    if len(zone_names_) != len(zone_weights_):
        msg = f"Zone names and zone weights must have the same length. Got {len(zone_names_)} zone names and {len(zone_weights_)} zone weights."
        raise ValueError(msg)
    normalized_zone_weights: NDArray[np.float64] = zone_weights_ / zone_weights_.sum()
    n_zones = len(zone_weights_)
    check_timeseries_shape(dbt_mat, expected_zones=n_zones, expected_timesteps=8760)

    # threshold comparisons have shape (n_thresholds, n_zones, n_timesteps)
    over_thresh_by_zone = dbt_mat > overheat_thresholds.reshape(-1, 1, 1)
    under_thresh_by_zone = dbt_mat < undercool_thresholds.reshape(-1, 1, 1)
    # max returns true if any of the zones are above the threshold
    # thresh_any has shape (n_thresholds, n_timesteps)
    over_thresh_any: NDArray[np.bool_] = over_thresh_by_zone.max(
        axis=1
    )  # max returns true if threshold is exceeded for any zone
    under_thresh_any: NDArray[np.bool_] = under_thresh_by_zone.max(axis=1)

    # sum returns the number of timesteps that the threshold is exceeded for each zone
    # hours_by_zone has shape (n_thresholds, n_zones)
    over_hours_by_zone = over_thresh_by_zone.sum(axis=-1)
    under_hours_by_zone = under_thresh_by_zone.sum(axis=-1)

    over_hours_by_zone = pd.DataFrame(
        over_hours_by_zone,
        columns=pd.Index(zone_names_, name="Zone"),
        index=pd.Index(overheat_thresholds, name="Threshold [degC]"),
        dtype=np.float64,
    )
    under_hours_by_zone = pd.DataFrame(
        under_hours_by_zone,
        columns=pd.Index(zone_names_, name="Zone"),
        index=pd.Index(undercool_thresholds, name="Threshold [degC]"),
        dtype=np.float64,
    )

    worst_overhours_by_threshold = over_hours_by_zone.max(axis=1)
    worst_underhours_by_threshold = under_hours_by_zone.max(axis=1)

    weighted_overhours_by_threshold = over_hours_by_zone.mul(
        normalized_zone_weights
    ).sum(axis=1)
    weighted_underhours_by_threshold = under_hours_by_zone.mul(
        normalized_zone_weights
    ).sum(axis=1)

    over_hours_by_zone["Any Zone"] = over_thresh_any.sum(axis=1)
    under_hours_by_zone["Any Zone"] = under_thresh_any.sum(axis=1)
    over_hours_by_zone["Zone Weighted"] = weighted_overhours_by_threshold
    under_hours_by_zone["Zone Weighted"] = weighted_underhours_by_threshold
    over_hours_by_zone["Worst Zone"] = worst_overhours_by_threshold
    under_hours_by_zone["Worst Zone"] = worst_underhours_by_threshold
    over_hours_by_zone["Equally Weighted"] = over_hours_by_zone.mean(axis=1)
    under_hours_by_zone["Equally Weighted"] = under_hours_by_zone.mean(axis=1)

    over_whole_bldg = over_hours_by_zone[
        ["Any Zone", "Zone Weighted", "Worst Zone", "Equally Weighted"]
    ]
    under_whole_bldg = under_hours_by_zone[
        ["Any Zone", "Zone Weighted", "Worst Zone", "Equally Weighted"]
    ]
    over_hours_by_zone = over_hours_by_zone.drop(
        columns=["Any Zone", "Zone Weighted", "Worst Zone", "Equally Weighted"]
    )
    under_hours_by_zone = under_hours_by_zone.drop(
        columns=["Any Zone", "Zone Weighted", "Worst Zone", "Equally Weighted"]
    )

    ouh_counts_by_zone_and_threshold = pd.concat(
        [over_hours_by_zone, under_hours_by_zone],
        axis=0,
        keys=["Overheat", "Underheat"],
        names=["Metric", "Threshold [degC]"],
    )

    ouh_counts_by_building_and_threshold = pd.concat(
        [over_whole_bldg, under_whole_bldg],
        axis=0,
        keys=["Overheat", "Underheat"],
        names=["Metric", "Threshold [degC]"],
    )

    combined = pd.concat(
        [ouh_counts_by_building_and_threshold, ouh_counts_by_zone_and_threshold],
        axis=1,
        names=["Aggregation Unit", "Group"],
        keys=["Building", "Zone"],
    ).T
    combined.columns.names = ["Polarity", "Threshold [degC]"]
    combined = (
        cast(
            pd.Series,
            cast(pd.DataFrame, combined.stack(future_stack=True)).stack(
                future_stack=True
            ),
        )
        .rename("Total Hours [hr]")
        .dropna()
        .to_frame()
        .reorder_levels(
            ["Polarity", "Threshold [degC]", "Aggregation Unit", "Group"], axis=0
        )
    )

    return combined


def _consecutive_run_lengths_vectorized(
    M_diff: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Compute lengths and integrals of consecutive runs where M_diff > 0, along the last axis.

    M_diff has shape (..., n_timesteps). For each (..., :) slice, identifies runs where
    M_diff > 0 and returns:
      - lengths: (n_slices, max_runs) count of timesteps per run, NaN-padded.
      - integrals: (n_slices, max_runs) sum of M_diff over each run (degree-hours), NaN-padded.

    Uses run_id + bincount (and bincount with weights for integrals) so no Python loops
    over rows or timesteps.
    """
    M = M_diff > 0
    orig_shape = M.shape
    n_timesteps = orig_shape[-1]
    n_slices = int(np.prod(orig_shape[:-1]))
    M_2d = M.reshape(n_slices, n_timesteps)
    M_diff_2d = M_diff.reshape(n_slices, n_timesteps)

    # Run starts: True where a new run of True begins
    run_start = np.empty_like(M_2d)
    run_start[:, 0] = M_2d[:, 0]
    run_start[:, 1:] = M_2d[:, 1:] & ~M_2d[:, :-1]

    # Run id: 0 where False, 1,2,3,... for each run of True
    run_id = np.where(M_2d, np.cumsum(run_start, axis=1), 0)

    max_run_id = int(run_id.max())
    if max_run_id == 0:
        nan_out = np.full((n_slices, 1), np.nan, dtype=np.float64)
        return nan_out, nan_out.copy()

    # Linear index for (row, run_id); run_id is 1..max_run_id
    flat_row = np.repeat(np.arange(n_slices, dtype=np.intp), n_timesteps)
    flat_run = run_id.ravel()
    mask = flat_run > 0
    flat_row = flat_row[mask]
    flat_run = flat_run[mask]
    flat_diff = M_diff_2d.ravel()[mask]

    idx = flat_row * max_run_id + (flat_run - 1)
    counts_flat = np.bincount(idx, minlength=n_slices * max_run_id)
    counts = counts_flat.reshape(n_slices, max_run_id).astype(np.float64)
    counts[counts == 0] = np.nan

    integrals_flat = np.bincount(
        idx, weights=flat_diff, minlength=n_slices * max_run_id
    )
    integrals = integrals_flat.reshape(n_slices, max_run_id).astype(np.float64)
    integrals[np.isnan(counts)] = np.nan
    return counts, integrals


def calculate_consecutive_hours_above_threshold(
    dbt_mat: NDArray[np.float64],
    heat_thresholds: tuple[ThresholdWithCriteria, ...],
    cold_thresholds: tuple[ThresholdWithCriteria, ...],
    zone_names: list[str] | None = None,
) -> pd.DataFrame:
    """Calculates consecutive hours above (overheating) or below (underheating) thresholds per zone.

    For each overheating threshold and each zone, computes the lengths of every run of
    consecutive hours above that threshold. For each underheating threshold and each zone,
    computes the lengths of every run of consecutive hours below that threshold. Uses
    vectorized operations across thresholds and zones; only the time dimension is
    processed with run-length logic.

    Args:
        dbt_mat (NDArray[np.float64]): The dry bulb temperature matrix (zones x timesteps).
        heat_thresholds: Thresholds for consecutive hours *above*.
        cold_thresholds: Thresholds for consecutive hours *below*.
        zone_names: The names of the zones. If None, zones are named "Zone 001", "Zone 002", etc.

    Returns:
        pd.DataFrame: MultiIndex (Metric, Threshold [degC], Zone). Columns "Streak 001", ... (run lengths, NaN-padded) and "Integral 001", ... (sum of excess/deficit per run, degree-hours, NaN-padded).
    """
    n_zones, _ = dbt_mat.shape
    zone_names_ = (
        [f"Zone {i:03d}" for i in range(n_zones)] if zone_names is None else zone_names
    )

    over_arr = np.array([t.threshold for t in heat_thresholds], dtype=np.float64)
    under_arr = np.array([t.threshold for t in cold_thresholds], dtype=np.float64)

    check_timeseries_shape(dbt_mat, expected_zones=n_zones, expected_timesteps=8760)

    # Excess/deficit for integrals: (n_thresholds, n_zones, n_timesteps)
    over_diff = dbt_mat - over_arr.reshape(-1, 1, 1)
    under_diff = under_arr.reshape(-1, 1, 1) - dbt_mat

    # Compute run lengths and integrals for all (threshold, zone) slices in one go per metric
    if over_arr.size > 0:
        over_lengths, over_integrals = _consecutive_run_lengths_vectorized(over_diff)
    else:
        over_lengths = over_integrals = np.empty((0, 0), dtype=np.float64)
    if under_arr.size > 0:
        under_lengths, under_integrals = _consecutive_run_lengths_vectorized(under_diff)
    else:
        under_lengths = under_integrals = np.empty((0, 0), dtype=np.float64)

    def build_df(
        lengths: NDArray[np.float64],
        integrals: NDArray[np.float64],
        thresholds: NDArray[np.float64],
        metric: str,
    ) -> pd.DataFrame:
        if lengths.size == 0:
            return pd.DataFrame()
        n_runs = lengths.shape[1]
        index = pd.MultiIndex.from_product(
            [
                [metric],
                list(thresholds),
                zone_names_,
            ],
            names=["Polarity", "Threshold [degC]", "Zone"],
        )
        streak_cols = [f"{i:05d}" for i in range(n_runs)]
        integral_cols = [f"{i:05d}" for i in range(n_runs)]
        length_df = pd.DataFrame(
            lengths,
            index=index,
            columns=streak_cols,
            dtype=np.float64,
        )
        integral_df = pd.DataFrame(
            integrals,
            index=index,
            columns=integral_cols,
            dtype=np.float64,
        )
        return pd.concat(
            [length_df, integral_df],
            axis=1,
            keys=["Streak [hr]", "Integral [deg-hr]"],
            names=["Metric", "Streak Index"],
        )

    over_df = build_df(over_lengths, over_integrals, over_arr, "Overheat")
    under_df = build_df(under_lengths, under_integrals, under_arr, "Underheat")

    if over_df.size == 0 and under_df.size == 0:
        return pd.DataFrame(
            index=pd.MultiIndex.from_tuples(
                [], names=["Metric", "Threshold [degC]", "Zone"]
            ),
        )

    if over_df.size == 0:
        return under_df
    if under_df.size == 0:
        return over_df
    return cast(
        pd.DataFrame,
        (
            pd
            .concat([over_df, under_df], axis=0)
            .stack(level="Streak Index", future_stack=True)
            .dropna()
        ),
    )


def _consecutive_run_lengths_looped(
    M_diff: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Compute lengths of consecutive True runs along the last axis, for all leading dimensions.

    M has shape (..., n_timesteps). For each (..., :) slice, returns run lengths in a padded
    2D array of shape (n_slices, max_runs), with NaN padding.
    """
    # TODO: use this method in a test to validate the vectorized version.
    M = M_diff > 0
    orig_shape = M.shape
    n_timesteps = orig_shape[-1]
    n_slices = int(np.prod(orig_shape[:-1]))

    M_2d = M.reshape(n_slices, n_timesteps)
    M_diff_2d = M_diff.reshape(n_slices, n_timesteps)

    slice_streaks = []
    slice_streak_integrals = []
    for slice_ix in range(n_slices):
        slice_data = M_2d[slice_ix, :]
        is_streaking = False
        streak_len = 0
        streak_integral = 0
        streaks = []
        streak_integrals = []
        for i in range(n_timesteps):
            flag = slice_data[i]
            diff = M_diff_2d[slice_ix, i]
            if flag and not is_streaking:
                is_streaking = True
                streak_len = 1
                streak_integral = diff
            elif flag and is_streaking:
                streak_len += 1
                streak_integral += diff
            elif not flag and is_streaking:
                streaks.append(streak_len)
                streak_integrals.append(streak_integral)
                is_streaking = False
                streak_len = 0
                streak_integral = 0
            else:
                streak_len = 0
                streak_integral = 0
        if is_streaking:
            streaks.append(streak_len)
            streak_integrals.append(streak_integral)
        slice_streaks.append(streaks)
        slice_streak_integrals.append(streak_integrals)
    most_streaks = max(len(streaks) for streaks in slice_streaks)
    most_streak_integrals = max(
        len(streak_integrals) for streak_integrals in slice_streak_integrals
    )
    padded_streaks = np.full((n_slices, most_streaks), np.nan, dtype=np.float64)
    padded_streak_integrals = np.full(
        (n_slices, most_streak_integrals), np.nan, dtype=np.float64
    )
    for slice_ix in range(n_slices):
        padded_streaks[slice_ix, : len(slice_streaks[slice_ix])] = slice_streaks[
            slice_ix
        ]
        padded_streak_integrals[slice_ix, : len(slice_streak_integrals[slice_ix])] = (
            slice_streak_integrals[slice_ix]
        )
    reshaped_streaks = padded_streaks.reshape((
        *orig_shape[:-1],
        most_streaks,
    ))
    reshaped_streak_integrals = padded_streak_integrals.reshape((
        *orig_shape[:-1],
        most_streak_integrals,
    ))
    return reshaped_streaks, reshaped_streak_integrals


def _check_heat_index_caution_or_worse(
    hi: pd.DataFrame,
    zone_names: list[str],
    crit: float,
    level: Literal["Caution", "Extreme Caution", "Danger", "Extreme Danger"],
) -> pd.Series:
    """Check each zone to see if the number of hours in the given heat index level or worse exceeds the criterion.

    Args:
        hi (pd.DataFrame): The heat index dataframe.
        zone_names (list[str]): The names of the zones.
        crit (float): The criterion for the given heat index level or worse.
        level (Literal["Caution", "Extreme Caution", "Danger", "Extreme Danger"]): The heat index level to check.

    Returns:
        Series(index=zone_names, dtype=bool): True where zone fails (at risk).
    """
    hi_zone = hi.loc["Zone"].reindex(zone_names)
    base_levels = [
        "Extreme Danger [hr]",
        "Danger [hr]",
        "Extreme Caution [hr]",
        "Caution [hr]",
    ]
    levels_to_use = base_levels[: base_levels.index(f"{level} [hr]") + 1]
    cols = [c for c in levels_to_use if c in hi_zone.columns]
    vals = (
        cast(pd.DataFrame, hi_zone[cols].fillna(0)).sum(axis=1)
        if cols
        else pd.Series(0.0, index=zone_names)
    )
    return vals.reindex(zone_names, fill_value=0).gt(crit)


def _check_count_failure(
    basic_zone: pd.DataFrame,
    polarity: str,
    thresh_val: float,
    zone_names: list[str],
    max_hours: float,
) -> pd.Series:
    """Check each zone to see if the number of hours above/below threshold exceeds the criterion.

    Args:
        basic_zone (pd.DataFrame): The basic overheating dataframe.
        polarity (str): The polarity of the threshold ("Overheat" or "Underheat").
        thresh_val (float): The threshold value.
        zone_names (list[str]): The names of the zones.
        max_hours (float): The maximum number of hours allowed.

    Returns:
        Series(index=zone_names, dtype=bool): True where zone fails (at risk).
    """
    try:
        s = cast(pd.Series, basic_zone.loc[(polarity, thresh_val), "Total Hours [hr]"])
    except KeyError:
        return pd.Series(False, index=zone_names)
    return s.reindex(zone_names, fill_value=0).gt(max_hours)


def _check_exceedance_failure(
    edh_zone: pd.DataFrame,
    polarity: str,
    thresh_val: float,
    zone_names: list[str],
    max_deg_hours: float,
) -> pd.Series:
    """Check each zone to see if the EDH exceeds the criterion.

    Args:
        edh_zone (pd.DataFrame): The EDH dataframe.
        polarity (str): The polarity of the threshold ("Overheat" or "Underheat").
        thresh_val (float): The threshold value.
        zone_names (list[str]): The names of the zones.
        max_deg_hours (float): The maximum number of degree-hours allowed.

    Returns:
        Series(index=zone_names, dtype=bool): True where zone fails (at risk).
    """
    try:
        s = cast(pd.Series, edh_zone.loc[(polarity, thresh_val), "EDH [degC-hr]"])
    except KeyError:
        return pd.Series(False, index=zone_names)
    return s.reindex(zone_names, fill_value=0).gt(max_deg_hours)


def _check_streak_failure(
    consecutive: pd.DataFrame,
    polarity: str,
    thresh_val: float,
    zone_names: list[str],
    min_streak_length_hours: float,
    max_count: float,
) -> pd.Series:
    """Returns Series(index=zone_names, dtype=bool): True where zone fails (at risk)."""
    streak_col = next(
        (c for c in consecutive.columns if "Streak" in str(c)),
        consecutive.columns[0] if len(consecutive.columns) > 0 else None,
    )
    if streak_col is None:
        return pd.Series(False, index=zone_names)
    try:
        subset = consecutive.xs(
            (polarity, thresh_val),
            level=("Polarity", "Threshold [degC]"),
        )
    except KeyError:
        return pd.Series(False, index=zone_names)
    count_long = subset.groupby(level="Zone")[streak_col].apply(
        lambda g: (g > min_streak_length_hours).sum()
    )
    return count_long.reindex(zone_names, fill_value=0).gt(max_count)


def _check_integrated_streak_failure(
    consecutive: pd.DataFrame,
    polarity: str,
    thresh_val: float,
    zone_names: list[str],
    min_streak_length_hours: float,
    max_integral: float,
) -> pd.Series:
    """Returns Series(index=zone_names, dtype=bool): True where zone fails (at risk)."""
    streak_col = next(
        (c for c in consecutive.columns if "Streak" in str(c)),
        consecutive.columns[0] if len(consecutive.columns) > 0 else None,
    )
    int_col = next(
        (c for c in consecutive.columns if "Integral" in str(c)),
        consecutive.columns[-1] if len(consecutive.columns) > 1 else None,
    )
    if streak_col is None or int_col is None:
        return pd.Series(False, index=zone_names)
    try:
        subset = consecutive.xs(
            (polarity, thresh_val),
            level=("Polarity", "Threshold [degC]"),
        )
    except KeyError:
        return pd.Series(False, index=zone_names)

    def _sum_integral_long_streaks(g: pd.DataFrame) -> float:
        mask = g[streak_col] > min_streak_length_hours
        # TODO: this is the sum of *ALL* the long streaks, not just the longest one.
        # Consider separating out that check.
        return float(g.loc[mask, int_col].sum())

    total_int = subset.groupby(level="Zone").apply(_sum_integral_long_streaks)
    return total_int.reindex(zone_names, fill_value=0).gt(max_integral)


def compute_zone_at_risk(
    results: "OverheatingAnalysisResults",
    config: OverheatingAnalysisConfig,
    zone_weights: NDArray[np.float64],
    zone_names: list[str],
) -> pd.DataFrame:
    """Compute a boolean for each zone indicating whether it is at risk.

    A zone is at risk if it fails any configured criterion (heat index, EDH,
    hours above/below threshold, or consecutive streak criteria).

    Args:
        results: The overheating analysis results.
        config: The configuration with criteria for each threshold.
        zone_weights: Weights for each zone.
        zone_names: Names of the zones.

    Returns:
        DataFrame with index=zone names, columns=weight, at_risk (bool).
    """
    hi = results.hi
    basic_zone: pd.DataFrame = cast(
        pd.DataFrame, results.basic_oh.xs("Zone", level="Aggregation Unit")
    )
    edh_zone: pd.DataFrame = cast(
        pd.DataFrame, results.edh.xs("Zone", level="Aggregation Unit")
    )
    consecutive = results.consecutive_e_zone

    normalized_weights = zone_weights / zone_weights.sum()
    fail_series_list: list[pd.Series] = []

    # Heat index criteria
    if config.heat_index_criteria.extreme_danger_hours is not None:
        fail_series_list.append(
            _check_heat_index_caution_or_worse(
                hi,
                zone_names,
                config.heat_index_criteria.extreme_danger_hours,
                level="Extreme Danger",
            )
        )
    if config.heat_index_criteria.danger_or_worse_hours is not None:
        fail_series_list.append(
            _check_heat_index_caution_or_worse(
                hi,
                zone_names,
                config.heat_index_criteria.danger_or_worse_hours,
                level="Danger",
            )
        )
    if config.heat_index_criteria.caution_or_worse_hours is not None:
        fail_series_list.append(
            _check_heat_index_caution_or_worse(
                hi,
                zone_names,
                config.heat_index_criteria.caution_or_worse_hours,
                level="Caution",
            )
        )

    # Threshold criteria
    for polarity, thresholds in [
        ("Overheat", config.heat_thresholds),
        ("Underheat", config.cold_thresholds),
    ]:
        for tc in thresholds:
            thresh_val = float(tc.threshold)
            if tc.count_failure is not None:
                fail_series_list.append(
                    _check_count_failure(
                        basic_zone,
                        polarity,
                        thresh_val,
                        zone_names,
                        tc.count_failure.max_hours,
                    )
                )
            if tc.exceedance_failure is not None:
                fail_series_list.append(
                    _check_exceedance_failure(
                        edh_zone,
                        polarity,
                        thresh_val,
                        zone_names,
                        tc.exceedance_failure.max_deg_hours,
                    )
                )
            if tc.streak_failure is not None:
                fail_series_list.append(
                    _check_streak_failure(
                        consecutive,
                        polarity,
                        thresh_val,
                        zone_names,
                        tc.streak_failure.min_streak_length_hours,
                        tc.streak_failure.max_count,
                    )
                )
            if tc.integrated_streak_failure is not None:
                fail_series_list.append(
                    _check_integrated_streak_failure(
                        consecutive,
                        polarity,
                        thresh_val,
                        zone_names,
                        tc.integrated_streak_failure.min_streak_length_hours,
                        tc.integrated_streak_failure.max_integral,
                    )
                )

    at_risk = (
        pd.concat(fail_series_list, axis=1).any(axis=1)
        if fail_series_list
        else pd.Series(False, index=zone_names)
    )

    out = pd.DataFrame(
        {"weight": normalized_weights, "at_risk": at_risk},
        index=zone_names,
    )
    out.index.name = "Zone"
    return out


def overheating_results_postprocess(
    sql: SQLResult,
    zone_weights: NDArray[np.float64],
    zone_names: list[str],
    config: OverheatingAnalysisConfig | None = None,
) -> "OverheatingAnalysisResults":
    """Postprocess the sql file to get the temperature results.

    Args:
        sql: The sql file to postprocess.
        zone_weights: The weights of the zones.
        zone_names: The names of the zones.
        config: Overheating analysis configuration. Uses defaults if None.

    Returns:
        OverheatingAnalysisResults with hi, edh, basic_oh, consecutive_e_zone, zone_at_risk.
    """
    _config = config if config is not None else OverheatingAnalysisConfig()
    # TODO: compare the single request flamegraph to splitting it out as multiple requests
    hourly = timeseries_frame(
        sql,
        [
            "Zone Mean Air Temperature",
            "Zone Air Relative Humidity",
            "Zone Mean Radiant Temperature",
        ],
        "Hourly",
    )
    hourly.index.names = ["Timestep"]
    hourly.columns.names = ["_", "Zone", "Meter"]

    hourly: pd.DataFrame = cast(
        pd.DataFrame,
        hourly
        .droplevel("_", axis=1)
        .stack(level="Zone", future_stack=True)
        .unstack(level="Timestep"),
    )

    rh = hourly.xs("Zone Air Relative Humidity", level="Meter", axis=1)
    dbt = hourly.xs("Zone Mean Air Temperature", level="Meter", axis=1)
    radiant = hourly.xs("Zone Mean Radiant Temperature", level="Meter", axis=1)

    zone_names_: list[str] = dbt.index.tolist()
    zone_names__: list[str] = radiant.index.tolist()
    zone_names___: list[str] = rh.index.tolist()
    if (
        {z.lower() for z in zone_names} != {z.lower() for z in zone_names_}
        or {z.lower() for z in zone_names} != {z.lower() for z in zone_names__}
        or {z.lower() for z in zone_names} != {z.lower() for z in zone_names___}
    ):
        msg = f"Zone names do not match! Expected: {zone_names}, Found: {zone_names_}, {zone_names__}, {zone_names___}."
        raise ValueError(msg)
    if zone_names_ != zone_names__ or zone_names_ != zone_names___:
        msg = f"Dataframe zone names are not in the same order as each other! Expected: {zone_names_}, but got {zone_names__}, {zone_names___}."
        raise ValueError(msg)

    # reorder the zone weights to match the zone names.
    zone_weights_to_use = np.array([
        zone_weights[[z.lower() for z in zone_names].index(zone.lower())]
        for zone in zone_names_
    ])
    zone_names_to_use = zone_names_

    dbt_mat = dbt.to_numpy()
    rh_mat = rh.to_numpy()
    radiant_mat = radiant.to_numpy()

    hi = calculate_hi_categories(
        dbt_mat=dbt_mat,
        rh_mat=rh_mat,
        zone_names=zone_names_to_use,
        zone_weights=zone_weights_to_use,
    )

    edh = calculate_edh(
        dbt_mat=dbt_mat,
        rh_mat=rh_mat,
        mrt_mat=radiant_mat,
        heat_thresholds=_config.heat_thresholds,
        cold_thresholds=_config.cold_thresholds,
        thermal_comfort=_config.thermal_comfort,
        zone_names=zone_names_to_use,
        zone_weights=zone_weights_to_use,
    )

    consecutive_e_zone = calculate_consecutive_hours_above_threshold(
        dbt_mat=dbt_mat,
        heat_thresholds=_config.heat_thresholds,
        cold_thresholds=_config.cold_thresholds,
        zone_names=zone_names_to_use,
    )

    basic_oh = calculate_basic_overheating_stats(
        dbt_mat=dbt_mat,
        zone_names=zone_names_to_use,
        zone_weights=zone_weights_to_use,
        heat_thresholds=_config.heat_thresholds,
        cold_thresholds=_config.cold_thresholds,
    )

    zone_at_risk = compute_zone_at_risk(
        results=OverheatingAnalysisResults(
            hi=hi,
            edh=edh,
            basic_oh=basic_oh,
            consecutive_e_zone=consecutive_e_zone,
            zone_at_risk=pd.DataFrame(),  # placeholder, not used by compute_zone_at_risk
        ),
        config=_config,
        zone_weights=zone_weights_to_use,
        zone_names=zone_names_to_use,
    )

    return OverheatingAnalysisResults(
        hi=hi,
        edh=edh,
        basic_oh=basic_oh,
        consecutive_e_zone=consecutive_e_zone,
        zone_at_risk=zone_at_risk,
    )


@dataclass
class OverheatingAnalysisResults:
    """The results of a overheating analysis."""

    hi: pd.DataFrame
    edh: pd.DataFrame
    basic_oh: pd.DataFrame
    consecutive_e_zone: pd.DataFrame
    zone_at_risk: pd.DataFrame


if __name__ == "__main__":
    # Timesteps should be along the columns
    # Zones should be along the rows
    _n_timesteps = 8760
    _n_zones = 10
    _zone_names = [f"Zone {i:03d}" for i in range(_n_zones)]
    _zone_weights = np.ones(_n_zones)
    _temperature_matrix = np.random.rand(_n_zones, _n_timesteps) * 30 + 10
    _relative_humidity_matrix = np.random.rand(_n_zones, _n_timesteps) * 50 + 50
    _mean_radiant_temperature_matrix = (
        _temperature_matrix + np.random.randn(_n_zones, _n_timesteps) * 1
    )

    _thermal_comfort = ThermalComfortAssumptions(
        met=1.1,
        clo=0.5,
        v=0.1,
    )
    _heat_thresholds = (
        ThresholdWithCriteria(threshold=26.0),
        ThresholdWithCriteria(threshold=30.0),
        ThresholdWithCriteria(threshold=35.0),
    )
    _cold_thresholds = (
        ThresholdWithCriteria(threshold=10.0),
        ThresholdWithCriteria(threshold=5.0),
    )
    r = calculate_hi_categories(
        _temperature_matrix,
        _relative_humidity_matrix,
        zone_names=_zone_names,
        zone_weights=_zone_weights,
    )

    edh = calculate_edh(
        _temperature_matrix,
        _relative_humidity_matrix,
        _mean_radiant_temperature_matrix,
        zone_names=_zone_names,
        zone_weights=_zone_weights,
        heat_thresholds=_heat_thresholds,
        cold_thresholds=_cold_thresholds,
        thermal_comfort=_thermal_comfort,
    )

    basic_oh_stats = calculate_basic_overheating_stats(
        _temperature_matrix,
        zone_names=_zone_names,
        zone_weights=_zone_weights,
        heat_thresholds=_heat_thresholds,
        cold_thresholds=_cold_thresholds,
    )

    consecutive_hours = calculate_consecutive_hours_above_threshold(
        _temperature_matrix,
        zone_names=_zone_names,
        heat_thresholds=_heat_thresholds,
        cold_thresholds=_cold_thresholds,
    )

    config = OverheatingAnalysisConfig()
    results = OverheatingAnalysisResults(
        hi=r,
        edh=edh,
        basic_oh=basic_oh_stats,
        consecutive_e_zone=consecutive_hours,
        zone_at_risk=pd.DataFrame(),  # placeholder, will be overwritten
    )
    zone_at_risk = compute_zone_at_risk(
        results=results,
        config=config,
        zone_weights=_zone_weights,
        zone_names=_zone_names,
    )
    results = OverheatingAnalysisResults(
        hi=r,
        edh=edh,
        basic_oh=basic_oh_stats,
        consecutive_e_zone=consecutive_hours,
        zone_at_risk=zone_at_risk,
    )

    print("---- Heat Index ----")
    print("\n")
    print(r)
    print("--- EDH ----")
    print("\n")
    print(edh)
    print("--- Basic Overheating Stats ----")
    print("\n")
    print(basic_oh_stats)
    print("--- Consecutive Hours ----")
    print("\n")
    print(consecutive_hours)
    print("--- Zone at Risk ----")
    print("\n")
    print(zone_at_risk)
