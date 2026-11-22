"""Envelope components for the SBEM library."""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from epinterface.document import (
    EPDocument,
    add_construction,
    add_or_replace,
)
from epinterface.geometry import get_zone_windows
from epinterface.interface import (
    InfDesignFlowRateCalculationMethodType,
    add_constant_schedule,
)
from epinterface.sbem.common import BoolStr, MetadataMixin, NamedObject, NanStr
from epinterface.sbem.components.materials import (
    ConstructionComponentSurfaceType,
    ConstructionMaterialComponent,
    StandardMaterialMetadataMixin,
)
from epinterface.sbem.components.schedules import YearComponent

if TYPE_CHECKING:
    # The object classes exist only in idfkit's stubs.
    from idfkit.document import AnyMaterial

WindowType = Literal["Single", "Double", "Triple"]


class GlazingConstructionSimpleComponent(
    NamedObject,
    StandardMaterialMetadataMixin,
    MetadataMixin,
    extra="forbid",
):
    """Glazing construction object."""

    SHGF: float = Field(..., title="Solar heat gain factor", ge=0, le=1)
    UValue: float = Field(
        ...,
        title="U-value [W/m²K]",
        ge=0,
    )
    TVis: float = Field(..., title="Visible transmittance", ge=0, le=1)
    Type: WindowType = Field(..., title="Type of the glazing construction")

    def add_to_idf(self, doc: EPDocument) -> EPDocument:
        """Adds the glazing construction to an IDF document.

        Args:
            doc (EPDocument): The IDF document to add the construction to.

        Returns:
            EPDocument: The updated IDF document.
        """
        add_or_replace(
            doc["WindowMaterial:SimpleGlazingSystem"].add,
            self.Name,
            u_factor=self.UValue,
            solar_heat_gain_coefficient=self.SHGF,
            visible_transmittance=self.TVis,
        )
        add_construction(doc, self.Name, [self.Name])
        return doc


GasTypeName = Literal["Air", "Argon", "Krypton", "Xenon"]


class GlazingMaterialComponent(
    NamedObject,
    StandardMaterialMetadataMixin,
    MetadataMixin,
    extra="forbid",
):
    """A glass pane's optical and thermal properties, at normal incidence."""

    Conductivity: float = Field(..., title="Conductivity [W/mK]", gt=0)
    Density: float | None = Field(
        default=None, title="Density [kg/m3]", ge=0, description="Not simulated."
    )
    SolarTransmittance: float = Field(..., title="Solar transmittance", ge=0, le=1)
    SolarReflectanceFront: float = Field(
        ..., title="Front-side solar reflectance", ge=0, le=1
    )
    SolarReflectanceBack: float = Field(
        ..., title="Back-side solar reflectance", ge=0, le=1
    )
    VisibleTransmittance: float = Field(..., title="Visible transmittance", ge=0, le=1)
    VisibleReflectanceFront: float = Field(
        ..., title="Front-side visible reflectance", ge=0, le=1
    )
    VisibleReflectanceBack: float = Field(
        ..., title="Back-side visible reflectance", ge=0, le=1
    )
    IRTransmittance: float = Field(..., title="Infrared transmittance", ge=0, lt=1)
    IREmissivityFront: float = Field(
        ..., title="Front-side infrared hemispherical emissivity", gt=0, lt=1
    )
    IREmissivityBack: float = Field(
        ..., title="Back-side infrared hemispherical emissivity", gt=0, lt=1
    )
    DirtFactor: float = Field(
        default=1.0,
        title="Dirt correction factor for solar and visible transmittance",
        gt=0,
        le=1,
    )


class GasMaterialComponent(
    NamedObject,
    StandardMaterialMetadataMixin,
    MetadataMixin,
    extra="forbid",
):
    """The gas filling a cavity between two panes."""

    GasType: GasTypeName = Field(..., title="Gas")


class GlazingLayerComponent(BaseModel, extra="forbid"):
    """A glass pane of a layered window."""

    Thickness: float = Field(..., title="Thickness [m]", gt=0, le=0.1)
    GlazingMaterial: GlazingMaterialComponent

    @property
    def name(self) -> str:
        """The name of the layer's `WindowMaterial:Glazing`."""
        return f"{self.GlazingMaterial.Name}_{self.Thickness}m"

    def add_to_idf(self, doc: EPDocument) -> EPDocument:
        """Write the pane as a spectral-average `WindowMaterial:Glazing`."""
        m = self.GlazingMaterial
        add_or_replace(
            doc["WindowMaterial:Glazing"].add,
            self.name,
            optical_data_type="SpectralAverage",
            thickness=self.Thickness,
            solar_transmittance_at_normal_incidence=m.SolarTransmittance,
            front_side_solar_reflectance_at_normal_incidence=m.SolarReflectanceFront,
            back_side_solar_reflectance_at_normal_incidence=m.SolarReflectanceBack,
            visible_transmittance_at_normal_incidence=m.VisibleTransmittance,
            front_side_visible_reflectance_at_normal_incidence=m.VisibleReflectanceFront,
            back_side_visible_reflectance_at_normal_incidence=m.VisibleReflectanceBack,
            infrared_transmittance_at_normal_incidence=m.IRTransmittance,
            front_side_infrared_hemispherical_emissivity=m.IREmissivityFront,
            back_side_infrared_hemispherical_emissivity=m.IREmissivityBack,
            conductivity=m.Conductivity,
            dirt_correction_factor_for_solar_and_visible_transmittance=m.DirtFactor,
        )
        return doc


class GasLayerComponent(BaseModel, extra="forbid"):
    """A gas-filled cavity of a layered window."""

    Thickness: float = Field(..., title="Thickness [m]", gt=0, le=0.1)
    GasMaterial: GasMaterialComponent

    @property
    def name(self) -> str:
        """The name of the layer's `WindowMaterial:Gas`."""
        return f"{self.GasMaterial.Name}_{self.Thickness}m"

    def add_to_idf(self, doc: EPDocument) -> EPDocument:
        """Write the cavity as a `WindowMaterial:Gas`."""
        add_or_replace(
            doc["WindowMaterial:Gas"].add,
            self.name,
            gas_type=self.GasMaterial.GasType,
            thickness=self.Thickness,
        )
        return doc


MAX_GLAZING_LAYERS = 4
"""The most panes EnergyPlus's window model takes."""


class GlazingConstructionLayeredComponent(
    NamedObject,
    StandardMaterialMetadataMixin,
    MetadataMixin,
    extra="forbid",
):
    """A window of glass panes and gas cavities, outside first.

    An alternative to `GlazingConstructionSimpleComponent` in a zone envelope's
    window slot: EnergyPlus computes its U-value, solar heat gain and visible
    transmittance from the layers, angle by angle.
    """

    Layers: list[GlazingLayerComponent | GasLayerComponent] = Field(
        ...,
        title="Layers, outside first",
        description=(
            "Panes and cavities alternate, starting and ending with a pane; at most "
            "4 panes."
        ),
    )
    Type: WindowType | None = Field(
        default=None,
        title="Type of the glazing construction",
        description="None: named by its number of panes.",
    )

    @field_validator("Layers", mode="after")
    @classmethod
    def validate_layers(
        cls, v: list["GlazingLayerComponent | GasLayerComponent"]
    ) -> list["GlazingLayerComponent | GasLayerComponent"]:
        """Panes and gases alternate, panes outermost; at most four panes."""
        if not v:
            msg = "A layered window needs at least one pane."
            raise ValueError(msg)
        for i, layer in enumerate(v):
            expected = GlazingLayerComponent if i % 2 == 0 else GasLayerComponent
            if not isinstance(layer, expected):
                msg = (
                    "Layers must alternate pane and gas, starting with a pane; "
                    f"layer {i} is a {type(layer).__name__}."
                )
                raise ValueError(msg)  # noqa: TRY004 (pydantic needs ValueError)
        if len(v) % 2 == 0:
            msg = "The innermost layer of a window must be a pane."
            raise ValueError(msg)
        if (len(v) + 1) // 2 > MAX_GLAZING_LAYERS:
            msg = f"A window has at most {MAX_GLAZING_LAYERS} panes."
            raise ValueError(msg)
        return v

    @property
    def pane_count(self) -> int:
        """The number of glass panes."""
        return (len(self.Layers) + 1) // 2

    def add_to_idf(self, doc: EPDocument) -> EPDocument:
        """Write the layers and the window `Construction` named `Name`."""
        for layer in self.Layers:
            doc = layer.add_to_idf(doc)
        add_construction(doc, self.Name, [layer.name for layer in self.Layers])
        return doc


WindowConstruction = (
    GlazingConstructionSimpleComponent | GlazingConstructionLayeredComponent
)
"""A window construction: simple glazing or glass and gas layers."""


class InfiltrationComponent(
    NamedObject,
    MetadataMixin,
    extra="forbid",
):
    """Zone infiltration object."""

    IsOn: BoolStr = Field(..., title="Infiltration is on")
    # TODO: add assumed_constants
    # TODO: these values should have stronger validators are on them or be dropped entirely and use defaults from EP wrapper classes
    ConstantCoefficient: float = Field(
        ...,
        title="Infiltration constant coefficient",
    )
    TemperatureCoefficient: float = Field(
        ...,
        title="Infiltration temperature coefficient",
    )
    WindVelocityCoefficient: float = Field(
        ...,
        title="Infiltration wind velocity coefficient",
    )
    WindVelocitySquaredCoefficient: float = Field(
        ...,
        title="Infiltration wind velocity squared coefficient",
    )
    AFNAirMassFlowCoefficientCrack: float = Field(
        ...,
        title="AFN air mass flow coefficient crack",
    )

    AirChangesPerHour: float = Field(
        ...,
        title="Infiltration air changes per hour [ACH]",
        ge=0,
    )
    FlowPerExteriorSurfaceArea: float = Field(
        ...,
        title="Infiltration flow per exterior surface area [m3/s/m2]",
        ge=0,
    )
    CalculationMethod: InfDesignFlowRateCalculationMethodType = Field(
        ...,
        title="Calculation method",
    )
    Schedule: YearComponent | None = Field(
        default=None,
        title="Infiltration schedule",
        description=(
            "Hourly multiplier of the infiltration flow (Fraction or AnyNumber "
            "type limits). None: the flow is constant (a schedule of 1)."
        ),
    )

    @field_validator("Schedule", mode="after")
    @classmethod
    def check_schedule_type(cls, v: YearComponent | None) -> YearComponent | None:
        """An infiltration schedule is a multiplier, not a temperature."""
        if v is not None and v.schedule_type_limits == "Temperature":
            msg = "The infiltration schedule must be a Fraction or AnyNumber schedule."
            raise ValueError(msg)
        return v

    def add_infiltration_to_idf_zone(
        self, doc: EPDocument, target_zone_or_zone_list_name: str
    ):
        """Add infiltration to an IDF zone.

        Args:
            doc (EPDocument): The IDF document to add the infiltration to.
            target_zone_or_zone_list_name (str): The name of the zone or zone list to add the infiltration to.

        Returns:
            doc (EPDocument): The updated IDF document.
        """
        if not self.IsOn:
            return doc

        infiltration_schedule_name = (
            f"{target_zone_or_zone_list_name}_{self.safe_name}_INFILTRATION_Schedule"
        )
        infiltration_name = (
            f"{target_zone_or_zone_list_name}_{self.safe_name}_INFILTRATION"
        )
        if self.Schedule is None:
            schedule_name = add_constant_schedule(
                doc, infiltration_schedule_name, 1, "Fraction"
            ).name
        else:
            doc, schedule_name = self.Schedule.add_year_to_idf(doc, name_prefix=None)
        # The coefficients are 1/0/0/0 rather than this component's own: the
        # infiltration values are taken as actual rates, and no assumption is
        # made about the wind velocity.
        add_or_replace(
            doc["ZoneInfiltration:DesignFlowRate"].add,
            infiltration_name,
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            schedule_name=schedule_name,
            design_flow_rate_calculation_method=self.CalculationMethod,
            flow_rate_per_exterior_surface_area=self.FlowPerExteriorSurfaceArea,
            air_changes_per_hour=self.AirChangesPerHour,
            constant_term_coefficient=1.0,
            temperature_term_coefficient=0.0,
            velocity_term_coefficient=0.0,
            velocity_squared_term_coefficient=0.0,
        )
        return doc


class ConstructionLayerComponent(BaseModel, extra="forbid"):
    """Layer of an opaque construction."""

    Thickness: float = Field(..., title="Thickness of the layer [m]", ge=0, le=2)
    LayerOrder: int
    ConstructionMaterial: ConstructionMaterialComponent

    @property
    def name(self):
        """Return the name of the layer."""
        # TODO: do we want to consider scoping construction layer names by parent construction?
        # We currently have disabled LayerOrder in the name because it was causing
        # warnings to be rised by EP since a reversed construction would end up with
        # using different materials though with identical definitions; energyplus would
        # throw a warning but still proceed.
        # by not name scoping here by the parent construction, we end up with silent logical
        # failures in the event where a user has mutated
        # post-instantiated, decoupled ConstructionMaterial definitions with the same
        # name.
        # return f"{self.LayerOrder}_{self.ConstructionMaterial.Name}_{self.Thickness}m"
        return f"{self.ConstructionMaterial.Name}_{self.Thickness}m"

    def add_to_idf(self, doc: EPDocument) -> "AnyMaterial":
        """Write the layer as a `Material` object named `self.name`.

        An identical material already in the document (e.g. the same layer of
        another construction) is reused.

        Args:
            doc (EPDocument): The IDF document to write to.

        Returns:
            AnyMaterial: The `Material` object.
        """
        material = self.ConstructionMaterial
        return add_or_replace(
            doc["Material"].add,
            self.name,
            roughness=material.Roughness,
            thickness=self.Thickness,
            conductivity=material.Conductivity,
            density=material.Density,
            specific_heat=material.SpecificHeat,
            thermal_absorptance=material.ThermalAbsorptance,
            solar_absorptance=material.SolarAbsorptance,
            visible_absorptance=material.VisibleAbsorptance,
        )

    @property
    def r_value(self):
        """Return the R-value of the layer in m²K/W."""
        return self.Thickness / self.ConstructionMaterial.Conductivity

    @property
    def u_value(self):
        """Return the U-value of the layer in W/m²K."""
        return 1 / self.r_value


class ConstructionAssemblyComponent(
    NamedObject,
    MetadataMixin,
    extra="forbid",
):
    """Opaque construction object."""

    Layers: list[ConstructionLayerComponent] = Field(
        ..., title="Layers of the opaque construction"
    )
    VegetationLayer: NanStr | None = Field(
        default=None, title="Vegetation layer of the opaque construction"
    )
    Type: ConstructionComponentSurfaceType = Field(
        ..., title="Type of the opaque construction"
    )

    @field_validator("Layers", mode="after")
    def validate_layers(cls, v: list[ConstructionLayerComponent]):
        """Validate the layers of the construction."""
        if len(v) == 0:
            msg = "At least one layer is required"
            raise ValueError(msg)
        layer_orders = [layer.LayerOrder for layer in v]
        if set(layer_orders) != set(range(0, len(v))):
            msg = "Layer orders must be consecutive integers starting from 0"
            raise ValueError(msg)
        v = sorted(v, key=lambda x: x.LayerOrder)
        total_thickness = sum(layer.Thickness for layer in v)
        if total_thickness > 3:
            msg = "Total construction assembly thickness must be less than 3 meters"
            raise ValueError(msg)
        return v

    def add_to_idf(self, doc: EPDocument) -> EPDocument:
        """Adds an opaque construction to an IDF document.

        Note that this will add the individual materials as well.

        Args:
            doc (EPDocument): The IDF document to add the construction to.

        Returns:
            doc (EPDocument): The updated IDF document.
        """
        for layer in self.Layers:
            layer.add_to_idf(doc)
        add_construction(doc, self.Name, [layer.name for layer in self.Layers])
        return doc

    @property
    def sorted_layers(self):
        """Return the layers of the construction sorted by layer order."""
        return sorted(self.Layers, key=lambda x: x.LayerOrder)

    @property
    def reversed(self):
        """Return a reversed version of the construction."""
        copy = self.model_copy(deep=True)
        for i, layer in enumerate(copy.sorted_layers[::-1]):
            layer.LayerOrder = i
        copy.Layers = copy.sorted_layers
        copy.Name = f"{self.Name}_Reversed"
        return copy

    @property
    def r_value(self):
        """Return the R-value of the construction in m²K/W."""
        return sum(layer.r_value for layer in self.sorted_layers)

    @property
    def u_value(self):
        """Return the U-value of the construction in W/m²K."""
        return 1 / self.r_value


class EnvelopeAssemblyComponent(
    NamedObject,
    MetadataMixin,
    extra="forbid",
):
    """Zone construction object."""

    FlatRoofAssembly: ConstructionAssemblyComponent = Field(
        ..., title="Flat roof construction object; only used when no attic is present."
    )
    FacadeAssembly: ConstructionAssemblyComponent = Field(
        ..., title="Facade construction object"
    )
    FloorCeilingAssembly: ConstructionAssemblyComponent = Field(
        ..., title="Floor/ceiling construction object"
    )
    AtticRoofAssembly: ConstructionAssemblyComponent = Field(
        ...,
        title="Attic roof construction object (outer surface) - only used when attic is present.",
    )
    AtticFloorAssembly: ConstructionAssemblyComponent = Field(
        ..., title="Attic floor construction object  - only used when attic is present."
    )
    PartitionAssembly: ConstructionAssemblyComponent = Field(
        ..., title="Partition construction object"
    )
    ExternalFloorAssembly: ConstructionAssemblyComponent = Field(
        ..., title="External floor construction object"
    )
    GroundSlabAssembly: ConstructionAssemblyComponent = Field(
        ..., title="Ground slab construction object"
    )
    GroundWallAssembly: ConstructionAssemblyComponent = Field(
        ...,
        title="Ground wall construction object (only used when basement is present)",
    )
    BasementCeilingAssembly: ConstructionAssemblyComponent = Field(
        ...,
        title="Basement ceiling construction object (only used when basement is present)",
    )
    InternalMassAssembly: ConstructionAssemblyComponent | None = Field(
        default=None, title="Internal mass construction object"
    )
    InternalMassExposedAreaPerArea: float | None = Field(
        default=None,
        title="Internal mass exposed area per area [m²/m²]",
        ge=0,
    )

    PartitionAreaPerFloorArea: float = Field(
        default=0.0,
        title="Internal partition area per floor area [m2/m2]",
        description=(
            "Area of the internal partitions inside a zone, exposed to the zone, "
            "per floor area. Modelled as internal mass of the partition assembly. "
            "0: none."
        ),
        ge=0,
    )
    IsFacadeAdiabatic: bool = Field(
        default=False,
        title="Facade is adiabatic",
        description="Exterior walls exchange no heat with the outdoors.",
    )
    IsRoofAdiabatic: bool = Field(
        default=False,
        title="Roof is adiabatic",
        description="Exterior roofs exchange no heat with the outdoors.",
    )
    IsGroundAdiabatic: bool = Field(
        default=False,
        title="Ground contact is adiabatic",
        description="Floors and walls on the ground exchange no heat with it.",
    )
    IsPartitionAdiabatic: bool = Field(
        default=False,
        title="Partitions are adiabatic",
        description="Walls between zones exchange no heat between them.",
    )
    IsSlabAdiabatic: bool = Field(
        default=False,
        title="Floor/ceiling slabs are adiabatic",
        description=(
            "Floors and ceilings between storeys of the main zones exchange no "
            "heat between them."
        ),
    )

    @model_validator(mode="after")
    def validate_internal_mass_exposed_area_per_area(self):
        """Validate that either both internal mass assembly and internal mass exposed area are provided, or neither."""
        if self.InternalMassAssembly and (
            self.InternalMassExposedAreaPerArea is None
            or self.InternalMassExposedAreaPerArea == 0
        ):
            msg = "Internal mass assembly cannot be provided if internal mass exposed area per area is not provided (or 0)."
            raise ValueError(msg)
        if (
            self.InternalMassExposedAreaPerArea is not None
            and self.InternalMassExposedAreaPerArea != 0
        ) and self.InternalMassAssembly is None:
            msg = "Internal mass exposed area per area must be provided if internal mass assembly is provided"
            raise ValueError(msg)
        return self


ShadingTypeName = Literal["ExteriorShade", "InteriorShade"]

SHADE_THICKNESS = 0.005
"""Thickness of a window shade [m]."""
SHADE_CONDUCTIVITY = 0.1
"""Conductivity of a window shade [W/mK]."""
SHADE_TO_GLASS_DISTANCE = 0.05
"""Distance between a window shade and the glass [m]."""
SHADE_EMISSIVITY = 0.9
"""Infrared hemispherical emissivity of a window shade."""


class WindowSettingsComponent(NamedObject, MetadataMixin, extra="forbid"):
    """How a zone's windows open and are shaded (UMI's `WindowSettings`)."""

    OperableArea: float = Field(
        default=1.0,
        title="Operable fraction of the window area [0-1]",
        description="Fraction of the window area that opens for natural ventilation.",
        ge=0,
        le=1,
    )
    IsShadingSystemOn: bool = Field(
        default=False, title="Windows have a shading system"
    )
    ShadingSystemType: ShadingTypeName = Field(
        default="ExteriorShade", title="Position of the shade"
    )
    ShadingSystemSetpoint: float = Field(
        default=180.0,
        title="Shading setpoint [W/m2]",
        description="The shade is drawn when the solar radiation on the window exceeds it.",
        ge=0,
    )
    ShadingSystemTransmittance: float = Field(
        default=0.5,
        title="Solar and visible transmittance of the shade [0-1]",
        ge=0,
        lt=1,
    )
    ShadingSystemAvailabilitySchedule: YearComponent | None = Field(
        default=None,
        title="Shading availability schedule",
        description=(
            "When the shade may be drawn (Fraction type limits; 0 is never). None: "
            "always."
        ),
    )

    @field_validator("ShadingSystemAvailabilitySchedule", mode="after")
    @classmethod
    def check_schedule_type(cls, v: YearComponent | None) -> YearComponent | None:
        """The availability schedule is on or off."""
        if v is not None and v.schedule_type_limits != "Fraction":
            msg = "ShadingSystemAvailabilitySchedule must be a Fraction schedule."
            raise ValueError(msg)
        return v

    @property
    def shade_reflectance(self) -> float:
        """The shade's solar and visible reflectance: half of what it does not transmit."""
        return (1 - self.ShadingSystemTransmittance) / 2

    def add_shading_to_idf_zone(self, doc: EPDocument, zone_name: str) -> EPDocument:
        """Shade the zone's windows when the sun on them is strong.

        Writes a `WindowMaterial:Shade` and a `WindowShadingControl` covering the
        zone's windows, drawn when the solar radiation incident on a window
        exceeds `ShadingSystemSetpoint` (and the availability schedule allows).
        Nothing is written without a shading system or without windows.

        Args:
            doc (EPDocument): The IDF document, with the zone's windows.
            zone_name (str): The zone.

        Returns:
            doc (EPDocument): The updated IDF document.
        """
        if not self.IsShadingSystemOn:
            return doc
        windows = get_zone_windows(doc, zone_name)
        if not windows:
            return doc
        shade_name = f"{self.safe_name}_SHADE"
        add_or_replace(
            doc["WindowMaterial:Shade"].add,
            shade_name,
            solar_transmittance=self.ShadingSystemTransmittance,
            solar_reflectance=self.shade_reflectance,
            visible_transmittance=self.ShadingSystemTransmittance,
            visible_reflectance=self.shade_reflectance,
            infrared_hemispherical_emissivity=SHADE_EMISSIVITY,
            infrared_transmittance=0.0,
            thickness=SHADE_THICKNESS,
            conductivity=SHADE_CONDUCTIVITY,
            shade_to_glass_distance=SHADE_TO_GLASS_DISTANCE,
        )
        schedule_name = None
        if self.ShadingSystemAvailabilitySchedule is not None:
            doc, schedule_name = self.ShadingSystemAvailabilitySchedule.add_year_to_idf(
                doc, name_prefix=None
            )
        add_or_replace(
            doc["WindowShadingControl"].add,
            f"{zone_name}_{self.safe_name}_SHADING",
            zone_name=zone_name,
            shading_control_sequence_number=1,
            shading_type=self.ShadingSystemType,
            shading_control_type="OnIfHighSolarOnWindow",
            schedule_name=schedule_name,
            setpoint=self.ShadingSystemSetpoint,
            shading_control_is_scheduled="No" if schedule_name is None else "Yes",
            glare_control_is_active="No",
            shading_device_material_name=shade_name,
            multiple_surface_control_type="Sequential",
            fenestration_surfaces=[
                {"fenestration_surface_name": w.name} for w in windows
            ],
        )
        return doc


class ZoneEnvelopeComponent(NamedObject, MetadataMixin, extra="forbid"):
    """Zone envelope object."""

    Assemblies: EnvelopeAssemblyComponent
    Infiltration: InfiltrationComponent
    AtticInfiltration: InfiltrationComponent
    BasementInfiltration: InfiltrationComponent
    Window: WindowConstruction | None
    WindowSettings: WindowSettingsComponent | None = Field(
        default=None,
        title="Window settings",
        description="How the windows open and are shaded. None: fully operable, unshaded.",
    )

    # Foundation: Foundation | None
    # OtherSettings: OtherSettings | None


# TODO: add envelope to idf zone
# (currently in builder)
