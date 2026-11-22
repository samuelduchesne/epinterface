"""Prisma client for SBEM."""

import shutil
import subprocess
from dataclasses import dataclass
from functools import cached_property
from importlib import resources
from typing import Any, Generic, Literal, TypeVar

from pydantic import FilePath, validate_call
from pydantic_settings import BaseSettings

from epinterface._optional import missing
from epinterface.sbem.common import NamedObject
from epinterface.sbem.components.envelope import (
    ConstructionAssemblyComponent,
    EnvelopeAssemblyComponent,
    GlazingConstructionSimpleComponent,
    InfiltrationComponent,
    ZoneEnvelopeComponent,
)
from epinterface.sbem.components.operations import ZoneOperationsComponent
from epinterface.sbem.components.schedules import YearComponent
from epinterface.sbem.components.space_use import (
    EquipmentComponent,
    LightingComponent,
    OccupancyComponent,
    ThermostatComponent,
    WaterUseComponent,
    ZoneSpaceUseComponent,
)
from epinterface.sbem.components.systems import (
    ConditioningSystemsComponent,
    DHWComponent,
    ThermalSystemComponent,
    VentilationComponent,
    ZoneHVACComponent,
)
from epinterface.sbem.components.zones import ZoneComponent

try:
    import prisma  # noqa: F401
except ModuleNotFoundError as e:
    raise missing("prisma", "prisma", "The SBEM component database") from e

try:
    from prisma import Prisma
    from prisma.bases import (
        BaseConditioningSystems,
        BaseConstructionAssembly,
        BaseDHW,
        BaseEnvelope,
        BaseEnvelopeAssembly,
        BaseEquipment,
        BaseGlazingConstructionSimple,
        BaseHVAC,
        BaseInfiltration,
        BaseLighting,
        BaseOccupancy,
        BaseOperations,
        BaseSpaceUse,
        BaseThermalSystem,
        BaseThermostat,
        BaseVentilation,
        BaseWaterUse,
        BaseYear,
        BaseZone,
    )
    from prisma.errors import RecordNotFoundError
    from prisma.models import (
        DHW,
        HVAC,
        ConditioningSystems,
        ConstructionAssembly,
        ConstructionAssemblyLayer,
        ConstructionMaterial,
        Day,
        Envelope,
        EnvelopeAssembly,
        Equipment,
        GlazingConstructionSimple,
        Infiltration,
        Lighting,
        Occupancy,
        Operations,
        SpaceUse,
        ThermalSystem,
        Thermostat,
        Ventilation,
        WaterUse,
        Week,
        Year,
        Zone,
    )
    from prisma.partials import (
        ConstructionAssemblyWithLayers,
        EnvelopeAssemblyWithChildren,
        EnvelopeWithChildren,
        EquipmentWithSchedule,
        HVACWithConditioningSystemsAndVentilation,
        LightingWithSchedule,
        OccupancyWithSchedule,
        OperationsWithChildren,
        SpaceUseWithChildren,
        ThermostatWithSchedule,
        VentilationWithSchedule,
        WaterUseWithSchedule,
        YearWithWeeks,
        ZoneWithChildren,
    )
    from prisma.types import (
        ConditioningSystemsInclude,
        ConstructionAssemblyInclude,
        ConstructionAssemblyLayerInclude,
        DatasourceOverride,
        DHWInclude,
        EnvelopeAssemblyInclude,
        EnvelopeInclude,
        EquipmentInclude,
        GlazingConstructionSimpleInclude,
        HVACInclude,
        InfiltrationInclude,
        LightingInclude,
        OccupancyInclude,
        OperationsInclude,
        SpaceUseInclude,
        ThermalSystemInclude,
        ThermostatInclude,
        VentilationInclude,
        WaterUseInclude,
        WeekInclude,
        YearInclude,
        ZoneInclude,
    )
except (RuntimeError, ImportError) as e:
    msg = "Prisma client has not yet been generated. "
    msg += "Please run `epinterface prisma generate` to generate the client, or if more customization is desired, "
    msg += "run `prisma py generate --schema $(epinterface prisma schemapath) --partials $(epinterface prisma partials-path)` directly."
    raise ImportError(msg) from e


from pathlib import Path


class PrismaSettings(BaseSettings):
    """Settings for the Prisma client."""

    database_path: FilePath
    auto_register: bool = True

    @classmethod
    @validate_call
    def New(
        cls,
        database_path: Path,
        if_exists: Literal["raise", "migrate", "overwrite", "ignore"],
        auto_register: bool = True,
    ):
        """Create a new PrismaSettings object which can be used to yield a Prisma instance.

        If the provided database path exists already, then we can either raise an error,
        create a new database and overwrite it, ignore it (i.e. use as is) or migrate it.

        Note that there is some special handling since normally prisma expects either a hardcoded strin
        in the datasource of the schema.prisma or to load it from the env file, but unfortunatley
        so instead we do a little trick where we will let database.db in the scoped directory
        be the working copy which we can move/copy from.


        Args:
            database_path (Path): The path to the database file.
            if_exists (Literal["raise", "migrate", "overwrite", "ignore"]): What to do if the database file already exists.
            auto_register (bool): Whether to automatically register the prisma client.

        Returns:
            settings (PrismaSettings): A PrismaSettings object.
        """
        # 1. check if the path exists and handle appropriately.
        epinterface_path = resources.files("epinterface")
        prisma_path = epinterface_path / "sbem" / "prisma"
        schema_path = prisma_path / "schema.prisma"
        path_exists = database_path.exists()
        generator_output_path = Path(str(prisma_path / "database.db"))
        _generator_output_path_exists = generator_output_path.exists()
        accepted_commands = ("prisma", "prisma.exe")
        prisma_cmd = shutil.which("prisma")
        if not prisma_cmd or not prisma_cmd.lower().endswith(accepted_commands):
            msg = "Prisma executable not found."
            raise RuntimeError(msg)

        def apply_migrations():
            try:
                subprocess.run(  # noqa: S603
                    [prisma_cmd, "migrate", "deploy", "--schema", str(schema_path)],
                    check=True,
                    text=True,
                    capture_output=False,
                    shell=False,
                )
            except subprocess.CalledProcessError as e:
                msg = f"Error applying migrations: {e}"
                raise RuntimeError(msg) from e

        # if generator_output_path_exists:
        #     msg = f"Temp database file {generator_output_path} already exists and would be overwritten.."
        #     raise FileExistsError(msg)

        if path_exists and if_exists == "raise":
            msg = f"Database file {database_path} already exists."
            raise FileExistsError(msg)
        elif path_exists and if_exists == "migrate":
            shutil.copy(database_path, database_path.with_suffix(".db.bak"))
            shutil.move(database_path, generator_output_path)
            apply_migrations()
            shutil.move(generator_output_path, database_path)
        elif path_exists and if_exists == "ignore":
            pass
        elif path_exists and if_exists == "overwrite":
            shutil.copy(database_path, database_path.with_suffix(".db.bak"))
            apply_migrations()
            shutil.move(generator_output_path, database_path)
        elif path_exists:
            msg = f"Database file {database_path} exists but unknown special case handler is set to {if_exists}."
            raise ValueError(msg)
        else:
            apply_migrations()
            shutil.move(generator_output_path, database_path)
        return cls(database_path=database_path, auto_register=auto_register)

    @cached_property
    def db(self) -> Prisma:
        """Get the Prisma client."""
        datasource: DatasourceOverride | None = (
            {"url": f"file:{self.database_path}"}
            if self.database_path is not None
            else None
        )
        return Prisma(auto_register=self.auto_register, datasource=datasource)


WEEK_INCLUDE: WeekInclude = {
    "Monday": True,
    "Tuesday": True,
    "Wednesday": True,
    "Thursday": True,
    "Friday": True,
    "Saturday": True,
    "Sunday": True,
}
YEAR_INCLUDE: YearInclude = {
    "January": {"include": WEEK_INCLUDE},
    "February": {"include": WEEK_INCLUDE},
    "March": {"include": WEEK_INCLUDE},
    "April": {"include": WEEK_INCLUDE},
    "May": {"include": WEEK_INCLUDE},
    "June": {"include": WEEK_INCLUDE},
    "July": {"include": WEEK_INCLUDE},
    "August": {"include": WEEK_INCLUDE},
    "September": {"include": WEEK_INCLUDE},
    "October": {"include": WEEK_INCLUDE},
    "November": {"include": WEEK_INCLUDE},
    "December": {"include": WEEK_INCLUDE},
}
LIGHTING_INCLUDE: LightingInclude = {
    "Schedule": {"include": YEAR_INCLUDE},
}
EQUIPMENT_INCLUDE: EquipmentInclude = {
    "Schedule": {"include": YEAR_INCLUDE},
}
THERMOSTAT_INCLUDE: ThermostatInclude = {
    "HeatingSchedule": {"include": YEAR_INCLUDE},
    "CoolingSchedule": {"include": YEAR_INCLUDE},
}
WATER_USE_INCLUDE: WaterUseInclude = {
    "Schedule": {"include": YEAR_INCLUDE},
}
OCCUPANCY_INCLUDE: OccupancyInclude = {
    "Schedule": {"include": YEAR_INCLUDE},
}
SPACE_USE_INCLUDE: SpaceUseInclude = {
    "Lighting": {"include": LIGHTING_INCLUDE},
    "Equipment": {"include": EQUIPMENT_INCLUDE},
    "Thermostat": {"include": THERMOSTAT_INCLUDE},
    "WaterUse": {"include": WATER_USE_INCLUDE},
    "Occupancy": {"include": OCCUPANCY_INCLUDE},
}
THERMAL_SYSTEM_INCLUDE: ThermalSystemInclude = {}
DHW_INCLUDE: DHWInclude = {}
CONDITIONING_SYSTEMS_INCLUDE: ConditioningSystemsInclude = {
    "Heating": True,
    "Cooling": True,
}
VENTILATION_INCLUDE: VentilationInclude = {
    "Schedule": {"include": YEAR_INCLUDE},
}
HVAC_INCLUDE: HVACInclude = {
    "ConditioningSystems": {"include": CONDITIONING_SYSTEMS_INCLUDE},
    "Ventilation": {"include": VENTILATION_INCLUDE},
}
OPERATIONS_INCLUDE: OperationsInclude = {
    "SpaceUse": {"include": SPACE_USE_INCLUDE},
    "HVAC": {"include": HVAC_INCLUDE},
    "DHW": True,
}


LAYER_INCLUDE: ConstructionAssemblyLayerInclude = {
    "ConstructionMaterial": True,
}
CONSTRUCTION_ASSEMBLY_INCLUDE: ConstructionAssemblyInclude = {
    "Layers": {"include": LAYER_INCLUDE, "order_by": {"LayerOrder": "asc"}},
}
ENVELOPE_ASSEMBLY_INCLUDE: EnvelopeAssemblyInclude = {
    "FlatRoofAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "AtticRoofAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "AtticFloorAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "FacadeAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "FloorCeilingAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "PartitionAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "ExternalFloorAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "BasementCeilingAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "GroundSlabAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "GroundWallAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
    "InternalMassAssembly": {"include": CONSTRUCTION_ASSEMBLY_INCLUDE},
}

ENVELOPE_INCLUDE: EnvelopeInclude = {
    "Assemblies": {"include": ENVELOPE_ASSEMBLY_INCLUDE},
    "Infiltration": True,
    "AtticInfiltration": True,
    "BasementInfiltration": True,
    "Window": True,
}
INFILTRATION_INCLUDE: InfiltrationInclude = {}
GLAZING_CONSTRUCTION_SIMPLE_INCLUDE: GlazingConstructionSimpleInclude = {}
ZONE_INCLUDE: ZoneInclude = {
    "Envelope": {"include": ENVELOPE_INCLUDE},
    "Operations": {"include": OPERATIONS_INCLUDE},
}

BaseT = TypeVar(
    "BaseT",
    bound=BaseYear
    | BaseOccupancy
    | BaseLighting
    | BaseEquipment
    | BaseWaterUse
    | BaseThermostat
    | BaseVentilation
    | BaseConditioningSystems
    | BaseSpaceUse
    | BaseOperations
    | BaseHVAC
    | BaseThermalSystem
    | BaseDHW
    | BaseConstructionAssembly
    | BaseEnvelopeAssembly
    | BaseEnvelope
    | BaseInfiltration
    | BaseGlazingConstructionSimple
    | BaseZone,
)
IncludeT = TypeVar(
    "IncludeT",
    YearInclude,
    OccupancyInclude,
    LightingInclude,
    EquipmentInclude,
    WaterUseInclude,
    ThermostatInclude,
    VentilationInclude,
    ConditioningSystemsInclude,
    SpaceUseInclude,
    OperationsInclude,
    HVACInclude,
    ThermalSystemInclude,
    DHWInclude,
    ConstructionAssemblyInclude,
    EnvelopeAssemblyInclude,
    EnvelopeInclude,
    InfiltrationInclude,
    GlazingConstructionSimpleInclude,
    ZoneInclude,
)
ValidatorT = TypeVar("ValidatorT", bound=NamedObject, contravariant=True)
YearT = TypeVar("YearT", bound=BaseYear)
OccupancyT = TypeVar("OccupancyT", bound=BaseOccupancy)
LightingT = TypeVar("LightingT", bound=BaseLighting)
EquipmentT = TypeVar("EquipmentT", bound=BaseEquipment)
WaterUseT = TypeVar("WaterUseT", bound=BaseWaterUse)
ThermostatT = TypeVar("ThermostatT", bound=BaseThermostat)
VentilationT = TypeVar("VentilationT", bound=BaseVentilation)
ConditioningSystemsT = TypeVar("ConditioningSystemsT", bound=BaseConditioningSystems)
SpaceUseT = TypeVar("SpaceUseT", bound=BaseSpaceUse)
OperationsT = TypeVar("OperationsT", bound=BaseOperations)
HVACT = TypeVar("HVACT", bound=BaseHVAC)
ThermalSystemT = TypeVar("ThermalSystemT", bound=BaseThermalSystem)
DHWT = TypeVar("DHWT", bound=BaseDHW)
ConstructionAssemblyT = TypeVar("ConstructionAssemblyT", bound=BaseConstructionAssembly)
EnvelopeAssemblyT = TypeVar("EnvelopeAssemblyT", bound=BaseEnvelopeAssembly)
EnvelopeT = TypeVar("EnvelopeT", bound=BaseEnvelope)
InfiltrationT = TypeVar("InfiltrationT", bound=BaseInfiltration)
GlazingConstructionSimpleT = TypeVar(
    "GlazingConstructionSimpleT", bound=BaseGlazingConstructionSimple
)
ZoneT = TypeVar("ZoneT", bound=BaseZone)


class SBEMDeepObjectNotFoundError(Exception):
    """Error raised when a deep object is not found."""

    def __init__(self, name: str, prisma_model: type[BaseT]):
        """Initialize the error."""
        msg = f"Deep object {name} not found in {prisma_model.__name__}."
        super().__init__(msg)


@dataclass
class Link(Generic[BaseT, IncludeT, ValidatorT]):
    """The Link class is used to link a prisma model to an SBEM NamedObject validator class."""

    prisma_model: type[BaseT]
    include: IncludeT
    validator: type[ValidatorT]

    def get_deep_object(
        self, name: str, db: Prisma | None = None
    ) -> tuple[BaseT, ValidatorT]:
        """Get a deep object by name.

        Note that you can pass a different database to use in case you need to load from
        multiple different databases in the same process, which requires setting auto_register=False on at least
        one of them.

        Args:
            name (str): The name of the object to get.
            db (Prisma | None): The database to use. If None, the default database will be used.

        Returns:
            tuple[BaseT, ValidatorT]: A tuple containing the base object and the validator object.
        """
        # It would be great if we could disable the type checker for this line,
        # but right now the BaseT / IncludeT are not constrained to only allow certain combinations.

        try:
            record = self.prisma_model.prisma(db).find_unique_or_raise(
                where={"Name": name},
                include=self.include,  # pyright: ignore [reportArgumentType]
            )
            return record, self.validator.model_validate(record, from_attributes=True)
        except RecordNotFoundError as e:
            raise SBEMDeepObjectNotFoundError(name, self.prisma_model) from e


@dataclass
class DeepObjectLinkers(
    Generic[
        YearT,
        OccupancyT,
        LightingT,
        EquipmentT,
        WaterUseT,
        ThermostatT,
        VentilationT,
        ConditioningSystemsT,
        SpaceUseT,
        OperationsT,
        HVACT,
        DHWT,
        ThermalSystemT,
        ConstructionAssemblyT,
        EnvelopeAssemblyT,
        EnvelopeT,
        InfiltrationT,
        GlazingConstructionSimpleT,
        ZoneT,
    ]
):
    """Deep object linkers."""

    Year: Link[YearT, YearInclude, YearComponent]
    Occupancy: Link[OccupancyT, OccupancyInclude, OccupancyComponent]
    Lighting: Link[LightingT, LightingInclude, LightingComponent]
    Equipment: Link[EquipmentT, EquipmentInclude, EquipmentComponent]
    WaterUse: Link[WaterUseT, WaterUseInclude, WaterUseComponent]
    Thermostat: Link[ThermostatT, ThermostatInclude, ThermostatComponent]
    Ventilation: Link[VentilationT, VentilationInclude, VentilationComponent]
    ConditioningSystems: Link[
        ConditioningSystemsT, ConditioningSystemsInclude, ConditioningSystemsComponent
    ]
    SpaceUse: Link[SpaceUseT, SpaceUseInclude, ZoneSpaceUseComponent]
    Operations: Link[OperationsT, OperationsInclude, ZoneOperationsComponent]
    HVAC: Link[HVACT, HVACInclude, ZoneHVACComponent]
    DHW: Link[DHWT, DHWInclude, DHWComponent]
    ThermalSystem: Link[ThermalSystemT, ThermalSystemInclude, ThermalSystemComponent]
    ConstructionAssembly: Link[
        ConstructionAssemblyT,
        ConstructionAssemblyInclude,
        ConstructionAssemblyComponent,
    ]
    EnvelopeAssembly: Link[
        EnvelopeAssemblyT, EnvelopeAssemblyInclude, EnvelopeAssemblyComponent
    ]
    Envelope: Link[EnvelopeT, EnvelopeInclude, ZoneEnvelopeComponent]
    Infiltration: Link[InfiltrationT, InfiltrationInclude, InfiltrationComponent]
    GlazingConstructionSimple: Link[
        GlazingConstructionSimpleT,
        GlazingConstructionSimpleInclude,
        GlazingConstructionSimpleComponent,
    ]
    Zone: Link[ZoneT, ZoneInclude, ZoneComponent]

    def get_deep_fetcher(
        self, val_class: type[ValidatorT]
    ) -> Link[Any, IncludeT, ValidatorT]:
        """Get the deep fetcher for a given class."""
        for _key, link_type in self.__annotations__.items():
            if hasattr(link_type, "__args__") and link_type.__args__[-1] == val_class:
                return getattr(self, _key)

        msg = f"No link found for {val_class}"
        raise ValueError(msg)


deep_fetcher = DeepObjectLinkers(
    Year=Link(
        prisma_model=YearWithWeeks,
        include=YEAR_INCLUDE,
        validator=YearComponent,
    ),
    Occupancy=Link(
        prisma_model=OccupancyWithSchedule,
        include=OCCUPANCY_INCLUDE,
        validator=OccupancyComponent,
    ),
    Lighting=Link(
        prisma_model=LightingWithSchedule,
        include=LIGHTING_INCLUDE,
        validator=LightingComponent,
    ),
    Equipment=Link(
        prisma_model=EquipmentWithSchedule,
        include=EQUIPMENT_INCLUDE,
        validator=EquipmentComponent,
    ),
    WaterUse=Link(
        prisma_model=WaterUseWithSchedule,
        include=WATER_USE_INCLUDE,
        validator=WaterUseComponent,
    ),
    Thermostat=Link(
        prisma_model=ThermostatWithSchedule,
        include=THERMOSTAT_INCLUDE,
        validator=ThermostatComponent,
    ),
    Ventilation=Link(
        prisma_model=VentilationWithSchedule,
        include=VENTILATION_INCLUDE,
        validator=VentilationComponent,
    ),
    ConditioningSystems=Link(
        prisma_model=ConditioningSystems,
        include=CONDITIONING_SYSTEMS_INCLUDE,
        validator=ConditioningSystemsComponent,
    ),
    SpaceUse=Link(
        prisma_model=SpaceUseWithChildren,
        include=SPACE_USE_INCLUDE,
        validator=ZoneSpaceUseComponent,
    ),
    Operations=Link(
        prisma_model=OperationsWithChildren,
        include=OPERATIONS_INCLUDE,
        validator=ZoneOperationsComponent,
    ),
    HVAC=Link(
        prisma_model=HVACWithConditioningSystemsAndVentilation,
        include=HVAC_INCLUDE,
        validator=ZoneHVACComponent,
    ),
    DHW=Link(
        prisma_model=DHW,
        include=DHW_INCLUDE,
        validator=DHWComponent,
    ),
    ThermalSystem=Link(
        prisma_model=ThermalSystem,
        include=THERMAL_SYSTEM_INCLUDE,
        validator=ThermalSystemComponent,
    ),
    ConstructionAssembly=Link(
        prisma_model=ConstructionAssemblyWithLayers,
        include=CONSTRUCTION_ASSEMBLY_INCLUDE,
        validator=ConstructionAssemblyComponent,
    ),
    EnvelopeAssembly=Link(
        prisma_model=EnvelopeAssemblyWithChildren,
        include=ENVELOPE_ASSEMBLY_INCLUDE,
        validator=EnvelopeAssemblyComponent,
    ),
    Envelope=Link(
        prisma_model=EnvelopeWithChildren,
        include=ENVELOPE_INCLUDE,
        validator=ZoneEnvelopeComponent,
    ),
    Infiltration=Link(
        prisma_model=Infiltration,
        include=INFILTRATION_INCLUDE,
        validator=InfiltrationComponent,
    ),
    GlazingConstructionSimple=Link(
        prisma_model=GlazingConstructionSimple,
        include=GLAZING_CONSTRUCTION_SIMPLE_INCLUDE,
        validator=GlazingConstructionSimpleComponent,
    ),
    Zone=Link(
        prisma_model=ZoneWithChildren,
        include=ZONE_INCLUDE,
        validator=ZoneComponent,
    ),
)


@dataclass
class PrismaClient:
    """Prisma client for SBEM."""

    db: Prisma


def delete_all(db: Prisma):
    """Delete all the objects in the database."""
    # delete everything in the db
    Zone.prisma(db).delete_many()
    Envelope.prisma(db).delete_many()
    EnvelopeAssembly.prisma(db).delete_many()
    ConstructionAssemblyLayer.prisma(db).delete_many()
    ConstructionAssembly.prisma(db).delete_many()
    ConstructionMaterial.prisma(db).delete_many()
    Infiltration.prisma(db).delete_many()
    GlazingConstructionSimple.prisma(db).delete_many()
    Operations.prisma(db).delete_many()
    HVAC.prisma(db).delete_many()
    ConditioningSystems.prisma(db).delete_many()
    SpaceUse.prisma(db).delete_many()
    Occupancy.prisma(db).delete_many()
    Lighting.prisma(db).delete_many()
    Thermostat.prisma(db).delete_many()
    Equipment.prisma(db).delete_many()
    WaterUse.prisma(db).delete_many()
    ThermalSystem.prisma(db).delete_many()
    DHW.prisma(db).delete_many()
    Ventilation.prisma(db).delete_many()
    Year.prisma(db).delete_many()
    Week.prisma(db).delete_many()
    Day.prisma(db).delete_many()
