"""An SBEM archetype: several zone groups and the building they make up.

A single SBEM `ZoneComponent` describes one kind of zone. An archetype describes a
whole building as a set of zone groups, each a zone definition with the share of the
conditioned floor area it covers, plus building-level characteristics: geometry
characteristics and attic and basement assumptions. The shares sum to 1.

An archetype is saved as indented JSON (`Archetype.save`) and read back with
`Archetype.load`. The file records `SchemaVersion`, so a reader can tell which
version of this model wrote it.

This module needs neither a generated Prisma client nor EnergyPlus.
"""

import math
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from epinterface.sbem.common import NamedObject
from epinterface.sbem.components.zones import ZoneComponent

ARCHETYPE_SCHEMA_VERSION = "1.0"
"""The version of the archetype file format this module reads and writes."""

ARCHETYPE_FILE_SUFFIX = ".sbem.json"
"""The conventional suffix of an archetype file (not enforced)."""

SHARE_SUM_TOLERANCE = 1e-6
"""How far the sum of set floor-area shares may be from 1."""

Orientation = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
"""Eight 45-degree sectors of azimuth, centred on north (0 deg), clockwise."""

ORIENTATIONS: tuple[Orientation, ...] = get_args(Orientation)

ExposureType = Literal["core", "perimeter"]
"""Where a group's zones sit: on the facade (perimeter) or away from it (core)."""


class AtticAssumptions(BaseModel):
    """The conditions of the attic."""

    UseFraction: float | None = Field(..., ge=0, le=1)
    Conditioned: bool


class BasementAssumptions(BaseModel):
    """The conditions of the basement."""

    UseFraction: float | None = Field(..., ge=0, le=1)
    Conditioned: bool


def orientation_of(azimuth_deg: float) -> Orientation:
    """Return the 45-degree sector an azimuth falls in.

    Args:
        azimuth_deg: Azimuth in degrees, clockwise from north.

    Returns:
        orientation: The sector, for example `"NE"` for 22.5 <= azimuth < 67.5.
    """
    index = math.floor(((azimuth_deg % 360) + 22.5) / 45) % 8
    return ORIENTATIONS[index]


def _check_by_orientation(
    value: dict[Orientation, float] | None, name: str
) -> dict[Orientation, float] | None:
    """Require all eight orientations and return them in canonical order.

    Raises:
        ValueError: If an orientation is missing.
    """
    if value is None:
        return None
    missing = [o for o in ORIENTATIONS if o not in value]
    if missing:
        msg = f"{name} must give every orientation; missing {missing}."
        raise ValueError(msg)
    return {o: value[o] for o in ORIENTATIONS}


class BuildingGeometry(BaseModel):
    """The building's geometry characteristics, as intensities.

    These describe the building; they do not generate geometry. Every field is
    optional: `None` means "not known" (for example a UMI template has no number of
    storeys), and the geometry it is applied to decides.

    Areas are relative to the conditioned floor area. Facade areas are gross
    (windows included), so window area by orientation is
    `FacadeAreaPerFloorArea[o] * WindowToWallRatio[o]`.
    """

    model_config = ConfigDict(extra="forbid")

    Storeys: int | None = Field(
        default=None, ge=1, description="Number of storeys above ground."
    )
    ConditionedFloorArea: float | None = Field(
        default=None, gt=0, description="Conditioned floor area of the building [m2]."
    )
    WindowToWallRatio: dict[Orientation, float] | None = Field(
        default=None,
        description="Window-to-wall ratio of each orientation [0-1].",
    )
    FacadeAreaPerFloorArea: dict[Orientation, float] | None = Field(
        default=None,
        description="Gross exterior wall area of each orientation per conditioned floor area [m2/m2].",
    )
    RoofAreaPerFloorArea: float | None = Field(
        default=None, ge=0, description="Exterior roof area per conditioned floor area."
    )
    ExposedFloorAreaPerFloorArea: float | None = Field(
        default=None,
        ge=0,
        description="Floor area exposed to outdoor air per conditioned floor area.",
    )
    GroundContactAreaPerFloorArea: float | None = Field(
        default=None,
        ge=0,
        description="Floor and wall area in contact with the ground per conditioned floor area.",
    )

    @field_validator("WindowToWallRatio", mode="after")
    @classmethod
    def _check_wwr(
        cls, v: dict[Orientation, float] | None
    ) -> dict[Orientation, float] | None:
        v = _check_by_orientation(v, "WindowToWallRatio")
        if v is not None and any(not 0 <= r <= 1 for r in v.values()):
            msg = f"WindowToWallRatio values must be within [0, 1]; got {v}."
            raise ValueError(msg)
        return v

    @field_validator("FacadeAreaPerFloorArea", mode="after")
    @classmethod
    def _check_facade(
        cls, v: dict[Orientation, float] | None
    ) -> dict[Orientation, float] | None:
        v = _check_by_orientation(v, "FacadeAreaPerFloorArea")
        if v is not None and any(a < 0 for a in v.values()):
            msg = f"FacadeAreaPerFloorArea values must be >= 0; got {v}."
            raise ValueError(msg)
        return v

    @staticmethod
    def uniform(value: float) -> dict[Orientation, float]:
        """The same value for every orientation, e.g. a single window-to-wall ratio."""
        return dict.fromkeys(ORIENTATIONS, value)

    @property
    def WindowAreaPerFloorArea(self) -> dict[Orientation, float] | None:
        """Window area of each orientation per conditioned floor area, when known."""
        if self.WindowToWallRatio is None or self.FacadeAreaPerFloorArea is None:
            return None
        return {
            o: self.FacadeAreaPerFloorArea[o] * self.WindowToWallRatio[o]
            for o in ORIENTATIONS
        }

    @property
    def OverallWindowToWallRatio(self) -> float | None:
        """Window-to-wall ratio of the whole facade.

        Facade-area-weighted when facade areas are known, else the plain mean of the
        orientations' ratios.
        """
        if self.WindowToWallRatio is None:
            return None
        if self.FacadeAreaPerFloorArea is not None:
            total = sum(self.FacadeAreaPerFloorArea.values())
            if total > 0:
                return (
                    sum(
                        self.FacadeAreaPerFloorArea[o] * self.WindowToWallRatio[o]
                        for o in ORIENTATIONS
                    )
                    / total
                )
        return sum(self.WindowToWallRatio.values()) / len(ORIENTATIONS)


class ZoneGroup(BaseModel):
    """A zone definition and the share of conditioned floor area it covers."""

    model_config = ConfigDict(extra="forbid")

    Name: str = Field(..., min_length=1, description="Unique within the archetype.")
    Zone: ZoneComponent
    FloorAreaShare: float = Field(
        ..., gt=0, le=1, description="Share of conditioned floor area."
    )
    Exposure: ExposureType | None = Field(
        default=None,
        description="Where the group's zones sit; None: not tied to an exposure.",
    )


class Archetype(NamedObject):
    """A building described by its zone groups and building-level characteristics.

    Validation:

    - group names are unique;
    - the `FloorAreaShare`s sum to 1 (within `SHARE_SUM_TOLERANCE`).
    """

    model_config = ConfigDict(extra="forbid")

    SchemaVersion: str = Field(
        default=ARCHETYPE_SCHEMA_VERSION,
        description="Version of the archetype file format.",
    )
    Groups: list[ZoneGroup] = Field(..., min_length=1)
    Geometry: BuildingGeometry = Field(default_factory=BuildingGeometry)
    Attic: AtticAssumptions = Field(
        default_factory=lambda: AtticAssumptions(UseFraction=None, Conditioned=False)
    )
    Basement: BasementAssumptions = Field(
        default_factory=lambda: BasementAssumptions(UseFraction=None, Conditioned=False)
    )

    @field_validator("SchemaVersion", mode="after")
    @classmethod
    def _check_schema_version(cls, v: str) -> str:
        if v != ARCHETYPE_SCHEMA_VERSION:
            msg = (
                f"Archetype schema version {v!r} is not supported; this epinterface "
                f"reads version {ARCHETYPE_SCHEMA_VERSION!r}."
            )
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _check_groups(self) -> "Archetype":
        names = [g.Name for g in self.Groups]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            msg = f"Zone group names must be unique; repeated: {duplicates}."
            raise ValueError(msg)

        total = sum(g.FloorAreaShare for g in self.Groups)
        if abs(total - 1) > SHARE_SUM_TOLERANCE:
            msg = f"Floor-area shares must sum to 1; they sum to {total!r}."
            raise ValueError(msg)
        return self

    def group(self, name: str) -> ZoneGroup:
        """Return the group with this name.

        Raises:
            KeyError: If no group has that name.
        """
        for g in self.Groups:
            if g.Name == name:
                return g
        raise KeyError(name)

    def to_json(self) -> str:
        """Serialise as indented JSON, keys in model order, ending with a newline."""
        return self.model_dump_json(indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str | bytes) -> "Archetype":
        """Read an archetype from its JSON text."""
        return cls.model_validate_json(text)

    def save(self, path: Path | str) -> Path:
        """Write the archetype to a JSON file (conventionally `<name>.sbem.json`).

        Returns:
            path: The path written.
        """
        path = Path(path)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path | str) -> "Archetype":
        """Read an archetype from a JSON file written by `save`."""
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
