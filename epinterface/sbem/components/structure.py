"""The building's structure, for life-cycle assessment (UMI's `StructureInformation`).

The structure is descriptive: the builder does not simulate it. It records the
structural materials of a building, either as mass ratios per floor area or as
an advanced structural model (spans, construction systems, soil and loading).
"""

from typing import Literal

from pydantic import BaseModel, Field

from epinterface.sbem.common import MetadataMixin, NamedObject
from epinterface.sbem.components.materials import (
    AssemblyLifeCycleMixin,
    ConstructionMaterialComponent,
)

BeamSystemType = Literal["RectangularSolid", "IBeam", "RectangularTube", "Truss"]
ColumnSystemType = Literal["SquareSolid", "IBeam", "SquareTube"]
FloorSystemType = Literal[
    "OneWayFlatSlab",
    "OneWayRibbedSlab",
    "OneWaySlabOnMetalDeck",
    "OneWayJoistSystem",
    "TwoWayFlatSlab",
    "TwoWayWaffleSlab",
]
FoundationSystemType = Literal[
    "SpreadFootings", "Raft", "PileAndPileCaps", "ShellFootings"
]
LateralSystemType = Literal["CrossBracing", "MomentFrames", "ShearWalls"]
FoundationSoilPresetName = Literal["Clay", "Gravel", "Sand", "Other"]
LiveLoadingPresetName = Literal[
    "Offices",
    "Residential",
    "SchoolsClassrooms",
    "LibrariesReadingRooms",
    "HospitalsLabs",
    "AssemblyAreas",
    "Restaurants",
    "Recreational",
    "Retail",
    "WarehouseLightStorage",
    "LibrariesStackRooms",
]


class MassRatioComponent(BaseModel, extra="forbid"):
    """Structural mass of one material per floor area."""

    Material: ConstructionMaterialComponent
    NormalRatio: float = Field(
        ..., title="Mass per floor area, normal loads [kg/m2]", ge=0
    )
    HighLoadRatio: float = Field(
        ..., title="Mass per floor area, high loads [kg/m2]", ge=0
    )


class ColumnWallSpacingComponent(BaseModel, extra="forbid"):
    """Spans between columns or walls."""

    PrimarySpan: float = Field(default=8.0, title="Primary span [m]", gt=0)
    SecondarySpan: float = Field(default=8.0, title="Secondary span [m]", gt=0)


class BeamSystemComponent(BaseModel, extra="forbid"):
    """The beams' material and type."""

    Material: ConstructionMaterialComponent | None = None
    ConstructionSystemType: BeamSystemType = "RectangularSolid"


class ColumnSystemComponent(BaseModel, extra="forbid"):
    """The columns' material and type."""

    Material: ConstructionMaterialComponent | None = None
    ConstructionSystemType: ColumnSystemType = "SquareSolid"


class FloorSystemComponent(BaseModel, extra="forbid"):
    """The floors' material and type."""

    Material: ConstructionMaterialComponent | None = None
    ConstructionSystemType: FloorSystemType = "OneWayFlatSlab"


class FoundationSystemComponent(BaseModel, extra="forbid"):
    """The foundations' material and type."""

    Material: ConstructionMaterialComponent | None = None
    ConstructionSystemType: FoundationSystemType = "SpreadFootings"


class LateralSystemComponent(BaseModel, extra="forbid"):
    """The lateral system's material and type."""

    Material: ConstructionMaterialComponent | None = None
    ConstructionSystemType: LateralSystemType = "CrossBracing"


class ConstructionSystemsComponent(BaseModel, extra="forbid"):
    """The structural systems of the advanced model."""

    Beams: BeamSystemComponent = Field(default_factory=BeamSystemComponent)
    Columns: ColumnSystemComponent = Field(default_factory=ColumnSystemComponent)
    Floors: FloorSystemComponent = Field(default_factory=FloorSystemComponent)
    Foundations: FoundationSystemComponent = Field(
        default_factory=FoundationSystemComponent
    )
    LateralSystem: LateralSystemComponent = Field(
        default_factory=LateralSystemComponent
    )


class FoundationSoilComponent(BaseModel, extra="forbid"):
    """The soil under the foundations."""

    FoundationSoilPreset: FoundationSoilPresetName = "Clay"
    FoundationSoilValue: float = Field(
        default=72.0, title="Soil value, in UMI's unit", ge=0
    )


class LoadingComponent(BaseModel, extra="forbid"):
    """The live loading the structure carries."""

    LiveLoadingPreset: LiveLoadingPresetName = "Offices"
    LiveLoadingValue: float = Field(default=2.4, title="Live load [kN/m2]", ge=0)


class AdvancedStructuralModelComponent(BaseModel, extra="forbid"):
    """UMI's advanced structural model."""

    ColumnWallSpacing: ColumnWallSpacingComponent = Field(
        default_factory=ColumnWallSpacingComponent
    )
    ConstructionSystems: ConstructionSystemsComponent = Field(
        default_factory=ConstructionSystemsComponent
    )
    FoundationSoilSettings: FoundationSoilComponent = Field(
        default_factory=FoundationSoilComponent
    )
    LoadingSettings: LoadingComponent = Field(default_factory=LoadingComponent)


class StructureComponent(
    NamedObject, AssemblyLifeCycleMixin, MetadataMixin, extra="forbid"
):
    """The building's structure: mass ratios or an advanced structural model."""

    MassRatios: list[MassRatioComponent] = Field(
        default_factory=list, title="Structural mass ratios, one per material"
    )
    UseAdvancedModel: bool = Field(
        default=False,
        title="Use the advanced structural model",
        description="True: AdvancedModel describes the structure; False: MassRatios.",
    )
    AdvancedModel: AdvancedStructuralModelComponent = Field(
        default_factory=AdvancedStructuralModelComponent
    )
