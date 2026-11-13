"""Seed functions for the prisma database to get dummy data into the db.

NB: The data in here is mostly junk and just written as quickly as possible for testing purposes!
"""

from prisma import Prisma
from prisma.models import Day
from prisma.types import DayCreateInput, WeekCreateInput

typologies = ["office", "residential"]
ages = ["new", "old"]
locations = ["cold", "warm"]
dhw_systems = ["bad", "medium", "good"]
tightnesses = ["unweatherized", "lightly", "moderately", "heavily"]
windows = ["single", "double", "triple"]


def create_schedule(
    db: Prisma,
    name_prefix: str,
    value: float = 0.5,
    day_type: str = "Fraction",
    year_type: str = "Equipment",
):
    """Create a constant schedule for the given name prefix.

    By default the schedule is a 0.5 ``Fraction`` schedule; thermostat setpoint
    schedules pass a ``Temperature`` day type, a ``Setpoint`` year type and a
    setpoint value in degC.
    """
    with db.tx() as tx:
        day_create_input: DayCreateInput = {
            "Name": f"{name_prefix} Monday",
            "Type": day_type,
            "Hour_00": value,
            "Hour_01": value,
            "Hour_02": value,
            "Hour_03": value,
            "Hour_04": value,
            "Hour_05": value,
            "Hour_06": value,
            "Hour_07": value,
            "Hour_08": value,
            "Hour_09": value,
            "Hour_10": value,
            "Hour_11": value,
            "Hour_12": value,
            "Hour_13": value,
            "Hour_14": value,
            "Hour_15": value,
            "Hour_16": value,
            "Hour_17": value,
            "Hour_18": value,
            "Hour_19": value,
            "Hour_20": value,
            "Hour_21": value,
            "Hour_22": value,
            "Hour_23": value,
        }
        day_creations_for_whole_week = {
            "Monday": day_create_input,
            "Tuesday": day_create_input,
            "Wednesday": day_create_input,
            "Thursday": day_create_input,
            "Friday": day_create_input,
            "Saturday": day_create_input,
            "Sunday": day_create_input,
        }
        created_days: dict[str, Day] = {}
        for day_name, day_create_input in day_creations_for_whole_week.items():
            day_create_input["Name"] = f"{name_prefix}_{day_name}"
            day = tx.day.create(data=day_create_input)
            created_days[day_name] = day

        week_a_create_input: WeekCreateInput = {
            "Name": f"{name_prefix}_RegularWeek",
            "Monday": {"connect": {"id": created_days["Monday"].id}},
            "Tuesday": {"connect": {"id": created_days["Tuesday"].id}},
            "Wednesday": {"connect": {"id": created_days["Wednesday"].id}},
            "Thursday": {"connect": {"id": created_days["Thursday"].id}},
            "Friday": {"connect": {"id": created_days["Friday"].id}},
            "Saturday": {"connect": {"id": created_days["Saturday"].id}},
            "Sunday": {"connect": {"id": created_days["Sunday"].id}},
        }
        week_a = tx.week.create(data=week_a_create_input)
        week_b_create_input: WeekCreateInput = {
            "Name": f"{name_prefix}_All_Monday",
            "Monday": {"connect": {"id": created_days["Monday"].id}},
            "Tuesday": {"connect": {"id": created_days["Monday"].id}},
            "Wednesday": {"connect": {"id": created_days["Monday"].id}},
            "Thursday": {"connect": {"id": created_days["Monday"].id}},
            "Friday": {"connect": {"id": created_days["Monday"].id}},
            "Saturday": {"connect": {"id": created_days["Monday"].id}},
            "Sunday": {"connect": {"id": created_days["Monday"].id}},
        }
        week_b = tx.week.create(data=week_b_create_input)
        tx.year.create(
            data={
                "Name": f"{name_prefix}_Year",
                "Type": year_type,
                "January": {"connect": {"id": week_a.id}},
                "February": {"connect": {"id": week_a.id}},
                "March": {"connect": {"id": week_a.id}},
                "April": {"connect": {"id": week_a.id}},
                "May": {"connect": {"id": week_a.id}},
                "June": {"connect": {"id": week_a.id}},
                "July": {"connect": {"id": week_b.id}},
                "August": {"connect": {"id": week_b.id}},
                "September": {"connect": {"id": week_b.id}},
                "October": {"connect": {"id": week_b.id}},
                "November": {"connect": {"id": week_b.id}},
                "December": {"connect": {"id": week_b.id}},
            }
        )


def create_schedules(db: Prisma):
    """Create schedules for the given database for the typical uses."""
    create_schedule(db, "Lights")
    create_schedule(db, "Equipment")
    create_schedule(db, "Occupancy")
    create_schedule(db, "WaterUse")
    # Thermostat setpoints are temperature schedules in degC.
    create_schedule(
        db, "Heating", value=21, day_type="Temperature", year_type="Setpoint"
    )
    create_schedule(
        db, "Cooling", value=24, day_type="Temperature", year_type="Setpoint"
    )
    create_schedule(db, "Ventilation")


def create_space_use_children(db: Prisma):
    """Create space use children objects for the given database for the typical uses."""
    last_equipment_name = ""
    for typology in typologies:
        for age in ages:
            epd = 10 if typology == "office" else 20
            epd = epd * 0.83 if age == "new" else epd
            last_equipment_name = f"{age}_{typology}"
            db.equipment.create(
                data={
                    "Name": last_equipment_name,
                    "Schedule": {"connect": {"Name": "Equipment_Year"}},
                    "PowerDensity": epd,
                    "IsOn": True,
                }
            )

    last_lighting_name = ""
    for typology in typologies:
        for age in ages:
            for loc in locations:
                lpd = 10 if typology == "office" else 20
                lpd = lpd * 0.8 if age == "old" else lpd
                lpd = lpd * 1.23 if loc == "cold" else lpd
                last_lighting_name = f"{age}_{loc}_{typology}"
                db.lighting.create(
                    data={
                        "Name": last_lighting_name,
                        "Schedule": {"connect": {"Name": "Lights_Year"}},
                        "PowerDensity": lpd,
                        "DimmingType": "Stepped" if typology == "office" else "Off",
                        "IsOn": True,
                    }
                )

    last_thermostat_name = ""
    for typology in typologies:
        for loc in locations:
            last_thermostat_name = f"{loc}_{typology}"
            db.thermostat.create(
                data={
                    "Name": last_thermostat_name,
                    "HeatingSchedule": {"connect": {"Name": "Heating_Year"}},
                    "CoolingSchedule": {"connect": {"Name": "Cooling_Year"}},
                    "IsOn": True,
                    "HeatingSetpoint": 20 if loc == "cold" else 23,
                    "CoolingSetpoint": 24 if typology == "office" else 23,
                }
            )

    last_occupancy_name = ""
    for typology in typologies:
        last_occupancy_name = typology
        db.occupancy.create(
            data={
                "Name": last_occupancy_name,
                "Schedule": {"connect": {"Name": "Occupancy_Year"}},
                "PeopleDensity": 0.05 if typology == "office" else 0.01,
                "IsOn": True,
                "MetabolicRate": 1.2,
            }
        )

    last_water_use_name = ""
    for typology in typologies:
        last_water_use_name = typology
        db.wateruse.create(
            data={
                "Name": last_water_use_name,
                "Schedule": {"connect": {"Name": "WaterUse_Year"}},
                "FlowRatePerPerson": 0.1 if typology == "office" else 0.239,
            }
        )

    space_use_name = "default"
    db.spaceuse.create(
        data={
            "Name": space_use_name,
            "Equipment": {"connect": {"Name": last_equipment_name}},
            "Lighting": {"connect": {"Name": last_lighting_name}},
            "Thermostat": {"connect": {"Name": last_thermostat_name}},
            "Occupancy": {"connect": {"Name": last_occupancy_name}},
            "WaterUse": {"connect": {"Name": last_water_use_name}},
        }
    )
    return space_use_name


def create_hvac_systems(db: Prisma):
    """Create HVAC systems for the given database for the typical uses."""
    last_heating_name = ""
    last_cooling_name = ""
    last_con_systems_name = ""
    last_ventilation_name = ""
    last_hvac_name = ""
    for typology in typologies:
        for location in locations:
            last_heating_name = f"Heating_{location}_{typology}"
            last_cooling_name = f"Cooling_{location}_{typology}"
            last_con_systems_name = f"{location}_{typology}"
            last_ventilation_name = f"{location}_{typology}"
            last_hvac_name = f"{location}_{typology}"
            db.thermalsystem.create(
                data={
                    "Name": last_heating_name,
                    "ConditioningType": "Heating",
                    "Fuel": "Electricity" if typology == "office" else "NaturalGas",
                    "SystemCOP": 3.5
                    if location == "cold" and typology == "office"
                    else 0.95,
                    "DistributionCOP": 0.9 if typology == "office" else 0.8,
                }
            )
            db.thermalsystem.create(
                data={
                    "Name": last_cooling_name,
                    "ConditioningType": "Cooling",
                    "Fuel": "Electricity",
                    "SystemCOP": 3.5 if location == "cold" else 4.5,
                    "DistributionCOP": 0.9 if typology == "office" else 0.8,
                }
            )
            db.conditioningsystems.create(
                data={
                    "Name": last_con_systems_name,
                    "Heating": {"connect": {"Name": last_heating_name}},
                    "Cooling": {"connect": {"Name": last_cooling_name}},
                }
            )
            db.ventilation.create(
                data={
                    "Name": last_ventilation_name,
                    "Schedule": {"connect": {"Name": "Ventilation_Year"}},
                    "FreshAirPerPerson": 0.008 if location == "cold" else 0.006,
                    "FreshAirPerFloorArea": 0.0004 if typology == "office" else 0.0002,
                    "Provider": "Mechanical",
                    "HRV": "Sensible",
                    "Economizer": "NoEconomizer",
                    "DCV": "NoDCV",
                }
            )
            db.hvac.create(
                data={
                    "Name": last_hvac_name,
                    "ConditioningSystems": {"connect": {"Name": last_con_systems_name}},
                    "Ventilation": {"connect": {"Name": last_ventilation_name}},
                }
            )
    return last_hvac_name


def create_dhw_systems(db: Prisma):
    """Create DHW systems for the given database for the typical uses."""
    last_dhw_name = ""
    for dhw_system in dhw_systems:
        last_dhw_name = dhw_system
        db.dhw.create(
            data={
                "Name": last_dhw_name,
                "SystemCOP": 3.5 if dhw_system == "good" else 0.95,
                "DistributionCOP": 0.9 if dhw_system == "good" else 0.8,
                "WaterTemperatureInlet": 10,
                "WaterSupplyTemperature": 55,
                "IsOn": True,
                "FuelType": "Electricity" if dhw_system == "medium" else "NaturalGas",
            }
        )
    return last_dhw_name


def create_operations(db: Prisma, space_use_name: str, hvac_name: str, dhw_name: str):
    """Create operations for the given database for the typical uses."""
    db.operations.create(
        data={
            "Name": "default_ops",
            "SpaceUse": {"connect": {"Name": space_use_name}},
            "HVAC": {"connect": {"Name": hvac_name}},
            "DHW": {"connect": {"Name": dhw_name}},
        }
    )
    return "default_ops"


def create_materials(db: Prisma):
    """Create materials for the given database."""
    db.constructionmaterial.create_many(
        data=[
            {
                "Name": "Concrete",
                "Density": 2400,
                "Roughness": "MediumRough",
                "TemperatureCoefficientThermalConductivity": 0.02,
                "Type": "Concrete",
                "Conductivity": 1.74,
                "SpecificHeat": 880,
                "ThermalAbsorptance": 0.7,
                "SolarAbsorptance": 0.3,
                "VisibleAbsorptance": 0.3,
            },
            {
                "Name": "Gypsum",
                "Density": 800,
                "Roughness": "MediumRough",
                "TemperatureCoefficientThermalConductivity": 0.01,
                "Type": "Finishes",
                "Conductivity": 0.36,
                "SpecificHeat": 880,
                "ThermalAbsorptance": 0.7,
                "SolarAbsorptance": 0.3,
                "VisibleAbsorptance": 0.3,
            },
            {
                "Name": "XPS",
                "Density": 20,
                "Roughness": "Smooth",
                "TemperatureCoefficientThermalConductivity": 0.01,
                "Type": "Insulation",
                "Conductivity": 0.03,
                "SpecificHeat": 880,
                "ThermalAbsorptance": 0.7,
                "SolarAbsorptance": 0.3,
                "VisibleAbsorptance": 0.3,
            },
            {
                "Name": "EPS",
                "Density": 10,
                "Roughness": "Smooth",
                "TemperatureCoefficientThermalConductivity": 0.01,
                "Type": "Insulation",
                "Conductivity": 0.03,
                "SpecificHeat": 880,
                "ThermalAbsorptance": 0.7,
                "SolarAbsorptance": 0.3,
                "VisibleAbsorptance": 0.3,
            },
        ]
    )


def create_construction_assemblies(db: Prisma):
    """Create construction assemblies for the given database."""
    # we will create one of type: Partition, one of type: Roof, one of type: Slab and so on.
    create_materials(db)
    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "Roof",
            "Type": "FlatRoof",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "XPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 2,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "EPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 1,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Gypsum"}},
                        "Thickness": 0.01,
                        "LayerOrder": 3,
                    },
                ],
            },
        },
    )
    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "Partition",
            "Type": "Partition",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Gypsum"}},
                        "Thickness": 0.01,
                        "LayerOrder": 1,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "XPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 2,
                    },
                ]
            },
        }
    )
    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "FloorCeiling",
            "Type": "FloorCeiling",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "XPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 1,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "EPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 2,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Gypsum"}},
                        "Thickness": 0.01,
                        "LayerOrder": 3,
                    },
                ]
            },
        }
    )
    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "GroundSlab",
            "Type": "GroundSlab",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "XPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 1,
                    },
                ]
            },
        }
    )

    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "GroundWall",
            "Type": "GroundWall",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "XPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 1,
                    },
                ]
            },
        }
    )

    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "Facade",
            "Type": "Facade",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Gypsum"}},
                        "Thickness": 0.01,
                        "LayerOrder": 1,
                    },
                ]
            },
        }
    )

    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "ExternalFloor",
            "Type": "ExternalFloor",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "XPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 1,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Gypsum"}},
                        "Thickness": 0.01,
                        "LayerOrder": 2,
                    },
                ]
            },
        }
    )
    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "InternalMass",
            "Type": "InternalMass",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Gypsum"}},
                        "Thickness": 0.01,
                        "LayerOrder": 1,
                    },
                ],
            },
        }
    )

    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "AtticFloor",
            "Type": "AtticFloor",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "XPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 1,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Gypsum"}},
                        "Thickness": 0.01,
                        "LayerOrder": 2,
                    },
                ]
            },
        }
    )
    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "AtticRoof",
            "Type": "AtticRoof",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "XPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 1,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Gypsum"}},
                        "Thickness": 0.01,
                        "LayerOrder": 2,
                    },
                ]
            },
        }
    )
    db.constructionassembly.create(
        data={  # pyright: ignore [reportArgumentType]
            "Name": "BasementCeiling",
            "Type": "BasementCeiling",
            "Layers": {
                "create": [
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Concrete"}},
                        "Thickness": 0.1,
                        "LayerOrder": 0,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "XPS"}},
                        "Thickness": 0.05,
                        "LayerOrder": 1,
                    },
                    {
                        "ConstructionMaterial": {"connect": {"Name": "Gypsum"}},
                        "Thickness": 0.01,
                        "LayerOrder": 2,
                    },
                ]
            },
        }
    )


def create_envelope_assemblies(db: Prisma):
    """Create envelope assemblies for the given database."""
    create_construction_assemblies(db)

    db.envelopeassembly.create(
        data={
            "Name": "default",
            "FlatRoofAssembly": {"connect": {"Name": "Roof"}},
            "FacadeAssembly": {"connect": {"Name": "Facade"}},
            "FloorCeilingAssembly": {"connect": {"Name": "FloorCeiling"}},
            "AtticRoofAssembly": {"connect": {"Name": "AtticRoof"}},
            "AtticFloorAssembly": {"connect": {"Name": "AtticFloor"}},
            "PartitionAssembly": {"connect": {"Name": "Partition"}},
            "GroundSlabAssembly": {"connect": {"Name": "GroundSlab"}},
            "GroundWallAssembly": {"connect": {"Name": "GroundWall"}},
            "BasementCeilingAssembly": {"connect": {"Name": "BasementCeiling"}},
            "ExternalFloorAssembly": {"connect": {"Name": "ExternalFloor"}},
            "InternalMassAssembly": {"connect": {"Name": "InternalMass"}},
            "InternalMassExposedAreaPerArea": 0.2,
        }
    )


def create_infiltration(db: Prisma):
    """Create infiltration for the given database."""
    for typology in typologies:
        for tightness in tightnesses:
            infil = 0.2 if typology == "office" else 0.3
            if tightness == "unweatherized":
                infil = infil * 1.5
            elif tightness == "lightly":
                infil = infil * 1.2
            elif tightness == "moderately":
                infil = infil * 1.0
            elif tightness == "heavily":
                infil = infil * 0.8
            db.infiltration.create(
                data={
                    "Name": f"{typology}_{tightness}",
                    "IsOn": True,
                    "ConstantCoefficient": 0.01,
                    "TemperatureCoefficient": 0.01,
                    "WindVelocityCoefficient": 0.01,
                    "WindVelocitySquaredCoefficient": 0.01,
                    "AFNAirMassFlowCoefficientCrack": 0.01,
                    "FlowPerExteriorSurfaceArea": 0.00,
                    "AirChangesPerHour": infil,
                    "CalculationMethod": "AirChanges/Hour",
                }
            )


def create_glazing_constructions(db: Prisma):
    """Create glazing constructions for the given database."""
    for window in windows:
        u_value = 1.0 if window == "single" else 0.5 if window == "double" else 0.3
        shgc = 0.7 if window == "single" else 0.5 if window == "double" else 0.3
        window_type = (
            "Single"
            if window == "single"
            else "Double"
            if window == "double"
            else "Triple"
        )
        db.glazingconstructionsimple.create(
            data={
                "Name": f"{window}",
                "UValue": u_value,
                "SHGF": shgc,
                "TVis": 0.5,
                "Type": window_type,
            }
        )


def create_envelope(db: Prisma):
    """Create envelopes for the given database."""
    create_envelope_assemblies(db)
    create_infiltration(db)
    create_glazing_constructions(db)

    db.envelope.create(
        data={
            "Name": "default_env",
            "Assemblies": {"connect": {"Name": "default"}},
            "Infiltration": {"connect": {"Name": "office_unweatherized"}},
            "AtticInfiltration": {"connect": {"Name": "office_unweatherized"}},
            "BasementInfiltration": {"connect": {"Name": "office_unweatherized"}},
            "Window": {"connect": {"Name": "single"}},
        }
    )


def create_zone(db: Prisma):
    """Create zones for the given database."""
    db.zone.create(
        data={
            "Name": "default_zone",
            "Envelope": {"connect": {"Name": "default_env"}},
            "Operations": {"connect": {"Name": "default_ops"}},
        }
    )
