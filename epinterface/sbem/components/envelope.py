"""Envelope components for the SBEM library."""

from typing import Literal

from idfkit import IDFObject
from pydantic import BaseModel, Field, field_validator, model_validator

from epinterface.document import (
    EPDocument,
    add_construction,
    add_or_replace,
)
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
            doc,
            "WindowMaterial:SimpleGlazingSystem",
            self.Name,
            u_factor=self.UValue,
            solar_heat_gain_coefficient=self.SHGF,
            visible_transmittance=self.TVis,
        )
        add_construction(doc, self.Name, [self.Name])
        return doc


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
        inf_schedule = add_constant_schedule(
            doc, infiltration_schedule_name, 1, "Fraction"
        )
        # The coefficients are 1/0/0/0 rather than this component's own: the
        # infiltration values are taken as actual rates, and no assumption is
        # made about the wind velocity.
        add_or_replace(
            doc,
            "ZoneInfiltration:DesignFlowRate",
            infiltration_name,
            zone_or_zonelist_or_space_or_spacelist_name=target_zone_or_zone_list_name,
            schedule_name=inf_schedule.name,
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

    def add_to_idf(self, doc: EPDocument) -> IDFObject:
        """Write the layer as a `Material` object named `self.name`.

        An identical material already in the document (e.g. the same layer of
        another construction) is reused.

        Args:
            doc (EPDocument): The IDF document to write to.

        Returns:
            IDFObject: The `Material` object.
        """
        material = self.ConstructionMaterial
        return add_or_replace(
            doc,
            "Material",
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


class ZoneEnvelopeComponent(NamedObject, MetadataMixin, extra="forbid"):
    """Zone envelope object."""

    Assemblies: EnvelopeAssemblyComponent
    Infiltration: InfiltrationComponent
    AtticInfiltration: InfiltrationComponent
    BasementInfiltration: InfiltrationComponent
    Window: GlazingConstructionSimpleComponent | None

    # Foundation: Foundation | None
    # OtherSettings: OtherSettings | None


# TODO: add envelope to idf zone
# (currently in builder)
