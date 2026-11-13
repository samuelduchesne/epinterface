"""A module to inject DDY files into IDF documents."""

from collections.abc import Sequence
from enum import Enum
from typing import Literal

from idfkit import IDFDocument, IDFObject
from pydantic import BaseModel, Field


class DDYField(Enum):
    """An enumeration of the object types in a DDY file that can be injected into an IDF document."""

    site_location = "Site:Location"
    design_day = "SizingPeriod:DesignDay"
    weather_file_condition_type = "SizingPeriod:WeatherFileConditionType"
    run_period_dst = "RunPeriodControl:DaylightSavingTime"
    site_precipitation = "Site:Precipitation"
    roof_irrigation = "RoofIrrigation"
    schedule_file = "Schedule:File"


DesignDayName = Literal[
    "Ann Htg 99.6% Condns DB",
    "Ann Htg 99% Condns DB",
    "Ann Hum_n 99.6% Condns DP=>MCDB",
    "Ann Hum_n 99% Condns DP=>MCDB",
    "Ann Htg Wind 99.6% Condns WS=>MCDB",
    "Ann Htg Wind 99% Condns WS=>MCDB",
    "Ann Clg .4% Condns DB=>MWB",
    "Ann Clg 1% Condns DB=>MWB",
    "Ann Clg 2% Condns DB=>MWB",
    "Ann Clg .4% Condns WB=>MDB",
    "Ann Clg 1% Condns WB=>MDB",
    "Ann Clg 2% Condns WB=>MDB",
    "Ann Clg .4% Condns DP=>MDB",
    "Ann Clg 1% Condns DP=>MDB",
    "Ann Clg 2% Condns DP=>MDB",
    "Ann Clg .4% Condns Enth=>MDB",
    "Ann Clg 1% Condns Enth=>MDB",
    "Ann Clg 2% Condns Enth=>MDB",
    "January .4% Condns DB=>MCWB",
    "February .4% Condns DB=>MCWB",
    "March .4% Condns DB=>MCWB",
    "April .4% Condns DB=>MCWB",
    "May .4% Condns DB=>MCWB",
    "June .4% Condns DB=>MCWB",
    "July .4% Condns DB=>MCWB",
    "August .4% Condns DB=>MCWB",
    "September .4% Condns DB=>MCWB",
    "October .4% Condns DB=>MCWB",
    "November .4% Condns DB=>MCWB",
    "December .4% Condns DB=>MCWB",
    "January 2% Condns DB=>MCWB",
    "February 2% Condns DB=>MCWB",
    "March 2% Condns DB=>MCWB",
    "April 2% Condns DB=>MCWB",
    "May 2% Condns DB=>MCWB",
    "June 2% Condns DB=>MCWB",
    "July 2% Condns DB=>MCWB",
    "August 2% Condns DB=>MCWB",
    "September 2% Condns DB=>MCWB",
    "October 2% Condns DB=>MCWB",
    "November 2% Condns DB=>MCWB",
    "December 2% Condns DB=>MCWB",
    "January 5% Condns DB=>MCWB",
    "February 5% Condns DB=>MCWB",
    "March 5% Condns DB=>MCWB",
    "April 5% Condns DB=>MCWB",
    "May 5% Condns DB=>MCWB",
    "June 5% Condns DB=>MCWB",
    "July 5% Condns DB=>MCWB",
    "August 5% Condns DB=>MCWB",
    "September 5% Condns DB=>MCWB",
    "October 5% Condns DB=>MCWB",
    "November 5% Condns DB=>MCWB",
    "December 5% Condns DB=>MCWB",
    "January 10% Condns DB=>MCWB",
    "February 10% Condns DB=>MCWB",
    "March 10% Condns DB=>MCWB",
    "April 10% Condns DB=>MCWB",
    "May 10% Condns DB=>MCWB",
    "June 10% Condns DB=>MCWB",
    "July 10% Condns DB=>MCWB",
    "August 10% Condns DB=>MCWB",
    "September 10% Condns DB=>MCWB",
    "October 10% Condns DB=>MCWB",
    "November 10% Condns DB=>MCWB",
    "December 10% Condns DB=>MCWB",
    "January .4% Condns WB=>MCDB",
    "February .4% Condns WB=>MCDB",
    "March .4% Condns WB=>MCDB",
    "April .4% Condns WB=>MCDB",
    "May .4% Condns WB=>MCDB",
    "June .4% Condns WB=>MCDB",
    "July .4% Condns WB=>MCDB",
    "August .4% Condns WB=>MCDB",
    "September .4% Condns WB=>MCDB",
    "October .4% Condns WB=>MCDB",
    "November .4% Condns WB=>MCDB",
    "December .4% Condns WB=>MCDB",
    "January 2% Condns WB=>MCDB",
    "February 2% Condns WB=>MCDB",
    "March 2% Condns WB=>MCDB",
    "April 2% Condns WB=>MCDB",
    "May 2% Condns WB=>MCDB",
    "June 2% Condns WB=>MCDB",
    "July 2% Condns WB=>MCDB",
    "August 2% Condns WB=>MCDB",
    "September 2% Condns WB=>MCDB",
    "October 2% Condns WB=>MCDB",
    "November 2% Condns WB=>MCDB",
    "December 2% Condns WB=>MCDB",
    "January 5% Condns WB=>MCDB",
    "February 5% Condns WB=>MCDB",
    "March 5% Condns WB=>MCDB",
    "April 5% Condns WB=>MCDB",
    "May 5% Condns WB=>MCDB",
    "June 5% Condns WB=>MCDB",
    "July 5% Condns WB=>MCDB",
    "August 5% Condns WB=>MCDB",
    "September 5% Condns WB=>MCDB",
    "October 5% Condns WB=>MCDB",
    "November 5% Condns WB=>MCDB",
    "December 5% Condns WB=>MCDB",
    "January 10% Condns WB=>MCDB",
    "February 10% Condns WB=>MCDB",
    "March 10% Condns WB=>MCDB",
    "April 10% Condns WB=>MCDB",
    "May 10% Condns WB=>MCDB",
    "June 10% Condns WB=>MCDB",
    "July 10% Condns WB=>MCDB",
    "August 10% Condns WB=>MCDB",
    "September 10% Condns WB=>MCDB",
    "October 10% Condns WB=>MCDB",
    "November 10% Condns WB=>MCDB",
    "December 10% Condns WB=>MCDB",
]

WeatherFileConditionType = Literal[
    "Summer Extreme",
    "Summer Typical",
    "Winter Extreme",
    "Winter Typical",
    "Autumn Typical",
    "Spring Typical",
]


class DDYSizingSpec(BaseModel):
    """A class to define how to inject a DDY file into an IDF file."""

    match: bool = Field(
        True,
        description="If True, will attempt to match design days adn weather condition types from the DDY to existing design days in the IDF file.",
    )
    design_days: list[DesignDayName] | Literal["All"] | None = Field(
        default=None,
        description="Additional design days to inject from the DDY into the IDF file.",
    )
    conditions_types: list[WeatherFileConditionType] | Literal["All"] | None = Field(
        default=None,
        description="Additional weather file condition types to inject from the DDY into the IDF file.",
    )
    raise_on_not_found: bool = Field(
        default=True,
        description="If True, will raise an error if a design day or weather file condition type is not found in the DDY file.",
    )

    def inject_ddy(self, doc: IDFDocument, ddy: IDFDocument):
        """Copies the DDY file into the IDF document according to the spec.

        Currently, only the following DDY fields are supported:
        - SITE:LOCATION
        - SIZINGPERIOD:DESIGNDAY
        - SIZINGPERIOD:WEATHERFILECONDITIONTYPE

        The following DDY fields are ignored as the just contain rain information or are not used:
        - RUNPERIODCONTROL:DAYLIGHTSAVINGTIME
        - SITE:PRECIPITATION
        - ROOFIRRIGATION
        - SCHEDULE:FILE


        Args:
            doc (IDFDocument): The document to inject the DDY file into.
            ddy (IDFDocument): The DDY file to inject into the document.
        """
        for obj_type, sequence in ddy.items():
            if not len(sequence):
                continue

            # will raise an error if the type is not in the DDYField enum to protect
            # against additional object types being added to ddys in the future
            field = DDYField(obj_type)

            if field == DDYField.site_location:
                self.handle_site_location(doc, ddy)
            elif field == DDYField.design_day:
                self.handle_design_days(doc, ddy)
            elif field == DDYField.weather_file_condition_type:
                self.handle_weather_file_condition_types(doc, ddy)
            else:
                # skip dst, site_precipitation, roof_irrigation, and schedule_file for now
                pass

    def remove_and_replace(
        self,
        doc: IDFDocument,
        ddy: IDFDocument,
        field: DDYField,
        copy_names: Sequence[str],
    ):
        """Removes all objects of the given field and replaces them with the new ones.

        Raises an error if the object is not found in the DDY file and `self.raise_on_not_found` is True.

        Args:
            doc (IDFDocument): The document to remove and replace objects from.
            ddy (IDFDocument): The DDY file to copy objects from.
            field (DDYField): The field to remove and replace objects from.
            copy_names (Sequence[WeatherFileConditionType] | Sequence[DesignDayName]): The names of the objects to copy,
                in the order they are added (EnergyPlus runs sizing periods in file order); duplicates are ignored.
        """
        _remove_all(doc, field)
        for obj_name in dict.fromkeys(copy_names):
            obj = ddy[field.value].get(obj_name)
            if obj is None:
                if self.raise_on_not_found:
                    raise DDYFieldNotFoundError(field=field, obj=obj_name)
                continue
            _copy_object(doc, obj)

    def handle_site_location(self, doc: IDFDocument, ddy: IDFDocument):
        """Handles the Site:Location object in the DDY file.

        Args:
            doc (IDFDocument): The document to inject the DDY file into.
            ddy (IDFDocument): The DDY file to inject into the document.
        """
        field = DDYField.site_location
        _remove_all(doc, field)
        for obj in ddy[field.value]:
            _copy_object(doc, obj)

    def handle_design_days(self, doc: IDFDocument, ddy: IDFDocument):
        """Handles the SizingPeriod:DesignDay objects in the DDY file.

        Args:
            doc (IDFDocument): The document to inject the DDY file into.
            ddy (IDFDocument): The DDY file to inject into the document.
        """
        field = DDYField.design_day
        sequence = list(ddy[field.value])
        all_design_day_names = [d.name for d in sequence]
        ddy_prefix = sequence[0].name.split(" ")[0]
        obj_names = (
            [f"{ddy_prefix} {day}" for day in self.design_days]
            if isinstance(self.design_days, list)
            else (all_design_day_names if self.design_days == "All" else [])
        )

        existing_sequence = list(doc[field.value])
        if self.match and existing_sequence:
            desired_objects = [
                " ".join([ddy_prefix, *obj.name.split(" ")[1:]])
                for obj in existing_sequence
            ]
            obj_names.extend(desired_objects)
        self.remove_and_replace(doc, ddy, field, obj_names)

    def handle_weather_file_condition_types(self, doc: IDFDocument, ddy: IDFDocument):
        """Handles the SizingPeriod:WeatherFileConditionType objects in the DDY file.

        Args:
            doc (IDFDocument): The document to inject the DDY file into.
            ddy (IDFDocument): The DDY file to inject into the document.
        """
        field = DDYField.weather_file_condition_type
        all_condition_types = [c.name for c in ddy[field.value]]
        obj_names: list[str]
        if self.conditions_types == "All":
            obj_names = all_condition_types
        elif isinstance(self.conditions_types, list):
            obj_names = list(self.conditions_types)
        else:
            obj_names = []

        existing_sequence = list(doc[field.value])
        if self.match and existing_sequence:
            desired_objects = [obj.name for obj in existing_sequence]
            obj_names.extend(desired_objects)
        self.remove_and_replace(doc, ddy, field, obj_names)


def _remove_all(doc: IDFDocument, field: DDYField) -> None:
    """Remove every object of the field's type from the document."""
    for obj in list(doc[field.value]):
        doc.removeidfobject(obj)


def _copy_object(doc: IDFDocument, obj: IDFObject) -> IDFObject:
    """Add a copy of a DDY object to the document (idfkit's own copy primitive)."""
    return doc.copyidfobject(obj)


class DDYFieldNotFoundError(Exception):
    """Raised when a field is not found in a DDY file."""

    # excepts a field name and object name and raises an error

    def __init__(self, field: DDYField, obj: str):
        """Initialize the error.

        Args:
            field (DDYField): The field that was not found.
            obj (str): The object that was not found.
        """
        message = f"{field.value}::{obj} not found in ddy file."
        super().__init__(message)


if __name__ == "__main__":
    from pathlib import Path

    from idfkit import load_idf

    from epinterface.settings import energyplus_settings

    idf_path = Path("US+SF+CZ4A+oilfurnace+unheatedbsmt+IECC_2021.idf")
    epw_path = Path(
        "D:/onebuilding/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/MA_Massachusetts/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.epw"
    )

    ddy_path = epw_path.with_suffix(".ddy")
    doc = load_idf(str(idf_path), version=energyplus_settings.version_tuple)
    ddy = load_idf(str(ddy_path), version=energyplus_settings.version_tuple)

    ddyspec = DDYSizingSpec(
        design_days=["January 10% Condns WB=>MCDB"],
        conditions_types=["Summer Extreme"],
        match=True,
    )

    ddyspec.inject_ddy(doc, ddy)
