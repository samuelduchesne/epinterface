"""An SBEM archetype: several zone groups and the building they make up.

A single SBEM `ZoneComponent` describes one kind of zone. An archetype describes a
whole building as a set of zone groups, each a zone definition with the share of the
conditioned floor area it covers, plus building-level characteristics: geometry
characteristics and attic and basement assumptions.

Floor-area shares are either all set, summing to 1, or all unset (`None`). Unset
shares mean "set by the building's geometry when the archetype is applied": the
shoebox builder then takes the core and perimeter areas from its width, depth and
perimeter depth (see `epinterface.sbem.builder.Model.from_archetype`).

An archetype is saved as indented JSON (`Archetype.save`) and read back with
`Archetype.load`. The file records `SchemaVersion`, so a reader can tell which
version of this model wrote it.

This module needs neither a generated Prisma client nor EnergyPlus.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from epinterface.geometry import ORIENTATIONS, Orientation, orientation_of
from epinterface.sbem.common import NamedObject
from epinterface.sbem.components.structure import StructureComponent
from epinterface.sbem.components.zones import ZoneComponent

__all__ = [
    "ARCHETYPE_FILE_SUFFIX",
    "ARCHETYPE_SCHEMA_VERSION",
    "ORIENTATIONS",
    "SUPPORTED_ARCHETYPE_SCHEMA_VERSIONS",
    "Archetype",
    "ArchetypeSchemaVersionError",
    "AtticAssumptions",
    "BasementAssumptions",
    "BuildingGeometry",
    "Orientation",
    "ZoneGroup",
    "orientation_of",
]

ARCHETYPE_SCHEMA_VERSION = "1.1"
"""The version of the archetype file format this module writes.

1.0: zone groups, unset shares, geometry characteristics.
1.1: adds the optional fields of UP-8 and UP-2's extra fields (specific fan power,
supply-air temperature limits, temperature-dependent energy input ratio, numeric
heat-recovery effectiveness, infiltration schedule, holiday and design-day slots).
A 1.0 file is a valid 1.1 file.
"""

SUPPORTED_ARCHETYPE_SCHEMA_VERSIONS: tuple[str, ...] = ("1.0", "1.1")
"""The archetype file format versions this module reads."""


class ArchetypeSchemaVersionError(ValueError):
    """Raised when an archetype file has a schema version this module cannot read."""

    def __init__(self, version: object) -> None:
        """Name the file's version and the supported ones."""
        super().__init__(
            f"Archetype schema version {version!r} is not supported; this "
            f"epinterface reads versions {list(SUPPORTED_ARCHETYPE_SCHEMA_VERSIONS)} "
            f"and writes {ARCHETYPE_SCHEMA_VERSION!r}."
        )
        self.version = version


ARCHETYPE_FILE_SUFFIX = ".sbem.json"
"""The conventional suffix of an archetype file (not enforced)."""

SHARE_SUM_TOLERANCE = 1e-6
"""How far the sum of set floor-area shares may be from 1."""

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
    FloorAreaShare: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="Share of conditioned floor area; None: set by the geometry when applied.",
    )
    Exposure: ExposureType | None = Field(
        default=None,
        description="Where the group's zones sit; None: not tied to an exposure.",
    )


class Archetype(NamedObject):
    """A building described by its zone groups and building-level characteristics.

    Validation:

    - group names are unique;
    - either every `FloorAreaShare` is set and they sum to 1 (within
      `SHARE_SUM_TOLERANCE`), or every one is `None`;
    - when shares are unset and there are several groups, each group has an
      `Exposure` and no two groups share one: the geometry can only split the
      floor area between core and perimeter.
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
    Structure: StructureComponent | None = Field(
        default=None,
        description="The building's structure, for life-cycle assessment; not simulated.",
    )
    YearFrom: int | None = Field(
        default=None, description="First construction year the archetype covers."
    )
    YearTo: int | None = Field(
        default=None, description="Last construction year the archetype covers."
    )
    Country: list[str] = Field(
        default_factory=list, description="Countries the archetype applies to."
    )
    ClimateZone: list[str] = Field(
        default_factory=list, description="Climate zones the archetype applies to."
    )
    Authors: list[str] = Field(
        default_factory=list, description="Authors of the archetype."
    )
    AuthorEmails: list[str] = Field(
        default_factory=list, description="E-mail addresses of the authors."
    )
    Version: str | None = Field(
        default=None, description="Version of the archetype's content."
    )
    Lifespan: int | None = Field(
        default=None, ge=0, description="Lifespan of the building [years]."
    )
    Category: str | None = Field(default=None, description="Category of the archetype.")
    Comment: str | None = Field(default=None, description="Comment on the archetype.")
    DataSource: str | None = Field(
        default=None, description="Source of the archetype's data."
    )

    @field_validator("SchemaVersion", mode="after")
    @classmethod
    def _check_schema_version(cls, v: str) -> str:
        """Accept every supported version; the archetype is then of the current one.

        Raises:
            ArchetypeSchemaVersionError: If the version is not supported.
        """
        if v not in SUPPORTED_ARCHETYPE_SCHEMA_VERSIONS:
            raise ArchetypeSchemaVersionError(v)
        return ARCHETYPE_SCHEMA_VERSION

    @model_validator(mode="after")
    def _check_years(self) -> "Archetype":
        if (
            self.YearFrom is not None
            and self.YearTo is not None
            and self.YearFrom > self.YearTo
        ):
            msg = (
                f"YearFrom ({self.YearFrom}) must not be after YearTo ({self.YearTo})."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_groups(self) -> "Archetype":
        names = [g.Name for g in self.Groups]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            msg = f"Zone group names must be unique; repeated: {duplicates}."
            raise ValueError(msg)

        shares = [g.FloorAreaShare for g in self.Groups]
        set_count = sum(s is not None for s in shares)
        if 0 < set_count < len(shares):
            unset = [g.Name for g in self.Groups if g.FloorAreaShare is None]
            msg = (
                "Floor-area shares must be set for every group or for none; "
                f"unset for {unset}."
            )
            raise ValueError(msg)
        if set_count:
            total = sum(s for s in shares if s is not None)
            if abs(total - 1) > SHARE_SUM_TOLERANCE:
                msg = f"Floor-area shares must sum to 1; they sum to {total!r}."
                raise ValueError(msg)
        elif len(self.Groups) > 1:
            exposures = [g.Exposure for g in self.Groups]
            if None in exposures or len(set(exposures)) != len(exposures):
                msg = (
                    "With unset floor-area shares, each group needs its own Exposure "
                    f"('core' or 'perimeter'); got {dict(zip(names, exposures, strict=True))}."
                )
                raise ValueError(msg)
        return self

    @property
    def shares_set(self) -> bool:
        """Whether the floor-area shares are set (else the geometry sets them)."""
        return self.Groups[0].FloorAreaShare is not None

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
        """Read an archetype from its JSON text.

        The schema version is checked before the rest, so a file from a newer
        epinterface is refused for its version rather than for its unknown
        fields. A file of an older supported version (or without a version,
        which is read as 1.0) is read as the current version.

        Raises:
            ArchetypeSchemaVersionError: If the file's version is not supported.
            pydantic.ValidationError: If the file is not a valid archetype.
        """
        data = json.loads(text)
        if isinstance(data, dict):
            version = data.get("SchemaVersion", "1.0")
            if version not in SUPPORTED_ARCHETYPE_SCHEMA_VERSIONS:
                raise ArchetypeSchemaVersionError(version)
        return cls.model_validate_json(text)

    @staticmethod
    def schema_version_of(path: Path | str) -> str:
        """The schema version recorded in an archetype file, without reading the rest.

        Returns:
            version: The file's `SchemaVersion`, or "1.0" when it records none.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return str(data.get("SchemaVersion", "1.0"))

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
