"""Model configurations frozen for the idfkit migration regression baseline.

All configurations use the preseeded test database, the ``default_zone`` zone,
the default EPW and a 10 x 10 x 3 m shoebox with a 0.2 window-to-wall ratio
unless stated otherwise. No model validator rejected any row of the plan, so
no assumptions were changed.
"""

from collections.abc import Callable
from itertools import product

from prisma import Prisma
from shapely import box

from epinterface.analysis.overheating import (
    OverheatingAnalysisConfig,
    ThresholdWithCriteria,
)
from epinterface.data import DefaultEPWZipPath
from epinterface.geometry import SceneContext, ShoeboxGeometry
from epinterface.sbem.builder import AtticAssumptions, BasementAssumptions, Model
from epinterface.sbem.prisma.client import deep_fetcher

HOURLY_NAMES = ["Zone Mean Air Temperature", "Zone Air Relative Humidity"]

_SHOEBOX = {"x": 0, "y": 0, "w": 10, "d": 10, "h": 3, "wwr": 0.2}


def _grid_scene_context() -> SceneContext:
    return SceneContext(
        building=box(0, 0, 10, 10),
        neighbors=[box(15, 0, 25, 10), box(0, 15, 10, 25)],
        neighbor_heights=[10.0, 0.0],
        orientation=0,
    )


def _build_geometry_grid() -> dict[str, ShoeboxGeometry]:
    grid: dict[str, ShoeboxGeometry] = {}
    for zoning, basement, roof_height, num_stories in product(
        ("by_storey", "core/perim"), (False, True), (None, 2.5), (1, 3)
    ):
        grid[f"{zoning}-{basement}-{roof_height}-{num_stories}"] = ShoeboxGeometry(
            **_SHOEBOX,
            num_stories=num_stories,
            zoning=zoning,
            basement=basement,
            roof_height=roof_height,
        )
    grid["by_storey_neighbors"] = ShoeboxGeometry(
        **_SHOEBOX,
        num_stories=2,
        zoning="by_storey",
        basement=False,
        roof_height=None,
        scene_context=_grid_scene_context(),
    )
    return grid


GEOMETRY_GRID: dict[str, ShoeboxGeometry] = _build_geometry_grid()

# A case where geomeppy's surface matching went wrong (floating point heights);
# the idfkit geometry deliberately differs from geomeppy here.
GEOMEPPY_MISMATCHED_KEY = "core/perim-False-None-3-h4.321"
GEOMETRY_SURFACE_CASES: dict[str, ShoeboxGeometry] = {
    **GEOMETRY_GRID,
    GEOMEPPY_MISMATCHED_KEY: ShoeboxGeometry(
        **{**_SHOEBOX, "h": 4.321},
        num_stories=3,
        zoning="core/perim",
        basement=False,
        roof_height=None,
    ),
}


def _by_storey_plain(db: Prisma):
    _, zone = deep_fetcher.Zone.get_deep_object("default_zone", db)
    model = Model(
        Weather=DefaultEPWZipPath,
        Zone=zone,
        Basement=BasementAssumptions(Conditioned=False, UseFraction=None),
        Attic=AtticAssumptions(Conditioned=False, UseFraction=None),
        geometry=ShoeboxGeometry(
            **_SHOEBOX,
            num_stories=2,
            zoning="by_storey",
            basement=False,
            roof_height=None,
        ),
    )
    return model, None


def _core_perim_basement_attic(db: Prisma):
    _, zone = deep_fetcher.Zone.get_deep_object("default_zone", db)
    model = Model(
        Weather=DefaultEPWZipPath,
        Zone=zone,
        Basement=BasementAssumptions(Conditioned=True, UseFraction=None),
        Attic=AtticAssumptions(Conditioned=False, UseFraction=None),
        geometry=ShoeboxGeometry(
            **{**_SHOEBOX, "w": 20, "d": 15},
            num_stories=2,
            zoning="core/perim",
            basement=True,
            roof_height=2.5,
        ),
    )
    return model, None


def _neighbors_overheating(db: Prisma):
    _, zone = deep_fetcher.Zone.get_deep_object("default_zone", db)
    model = Model(
        Weather=DefaultEPWZipPath,
        Zone=zone,
        Basement=BasementAssumptions(Conditioned=False, UseFraction=None),
        Attic=AtticAssumptions(Conditioned=False, UseFraction=None),
        geometry=ShoeboxGeometry(
            **_SHOEBOX,
            num_stories=3,
            zoning="by_storey",
            scene_context=SceneContext(
                building=box(0, 0, 10, 10),
                neighbors=[box(15, 0, 25, 10), box(0, 15, 10, 25)],
                neighbor_heights=[12.0, 0.0],
                orientation=0,
            ),
        ),
    )
    # Thresholds the 21/24 degC thermostat actually crosses, so every overheating
    # frame (including the consecutive-exceedance streaks) is non-trivial. None sits
    # on a setpoint: zone air is held at exactly 21 degC for thousands of hours, so a
    # threshold there makes hour counts flip on float noise between builds.
    oh = OverheatingAnalysisConfig(
        heat_thresholds=(
            ThresholdWithCriteria(threshold=23.0),
            ThresholdWithCriteria(threshold=26.0),
        ),
        cold_thresholds=(ThresholdWithCriteria(threshold=22.5),),
    )
    return model, oh


REGRESSION_CONFIGS: dict[
    str, Callable[[Prisma], tuple[Model, OverheatingAnalysisConfig | None]]
] = {
    "by_storey_plain": _by_storey_plain,
    "core_perim_basement_attic": _core_perim_basement_attic,
    "neighbors_overheating": _neighbors_overheating,
}
