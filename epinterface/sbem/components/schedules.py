"""This module contains the definitions for the schedules."""

import calendar
import re
from typing import Literal

from idfkit import IDFDocument, IDFObject
from pydantic import Field, field_validator, model_validator

from epinterface.interface import (
    PROTECTED_SCHEDULE_NAMES,
    ScheduleDayHourly,
    ScheduleTypeLimits,
    ScheduleWeekDaily,
    ScheduleYear,
)
from epinterface.sbem.common import NamedObject
from epinterface.schedules import HOURS_PER_YEAR, add_values_schedule

# TODO: handle schedule type limits in a consistent way once?
ScheduleTypeLimitType = Literal["Fraction", "Temperature", "AnyNumber"]

TypeLimits: dict[ScheduleTypeLimitType, ScheduleTypeLimits] = {
    "Fraction": ScheduleTypeLimits(
        Name="Fraction",
        Unit_Type="Dimensionless",
        Lower_Limit_Value=0,
        Upper_Limit_Value=1,
        Numeric_Type="Continuous",
    ),
    "Temperature": ScheduleTypeLimits(
        Name="Temperature",
        Unit_Type="Temperature",
        Lower_Limit_Value=-270,
        Upper_Limit_Value=1000,
        Numeric_Type="Continuous",
    ),
    "AnyNumber": ScheduleTypeLimits(
        Name="AnyNumber",
        Lower_Limit_Value=-1000,
        Upper_Limit_Value=1000,
        Numeric_Type="Continuous",
    ),
}


def add_constant_year_schedule(
    doc: IDFDocument, name: str, value: float, type_limits: ScheduleTypeLimitType
) -> IDFObject:
    """Add a constant `Schedule:Year` (with its week/day objects), replacing any of that name.

    Matches archetypal, where writing a schedule whose name already exists
    replaces it, so adding the same zone's schedules twice never raises.

    Args:
        doc (IDFDocument): The IDF document to add the schedule to.
        name (str): The name of the `Schedule:Year`.
        value (float): The value held all year.
        type_limits (ScheduleTypeLimitType): The name of an existing `ScheduleTypeLimits`.

    Returns:
        IDFObject: The `Schedule:Year` object.
    """
    if name in doc["Schedule:Year"]:
        doc.removeidfobject(doc["Schedule:Year"][name])
        generated = re.compile(rf"[dw]_{re.escape(name)}_\d\d", re.IGNORECASE)
        for obj_type in ("Schedule:Week:Daily", "Schedule:Day:Hourly"):
            for obj in list(doc[obj_type]):
                if generated.fullmatch(obj.name):
                    doc.removeidfobject(obj)
    return add_values_schedule(doc, name, [value] * HOURS_PER_YEAR, type_limits)


class DayComponent(NamedObject, extra="forbid"):
    """A day of the week with a schedule type limit and a list of values."""

    Type: ScheduleTypeLimitType = Field(
        ..., description="The ScheduleTypeLimits of the day."
    )
    Hour_00: float
    Hour_01: float
    Hour_02: float
    Hour_03: float
    Hour_04: float
    Hour_05: float
    Hour_06: float
    Hour_07: float
    Hour_08: float
    Hour_09: float
    Hour_10: float
    Hour_11: float
    Hour_12: float
    Hour_13: float
    Hour_14: float
    Hour_15: float
    Hour_16: float
    Hour_17: float
    Hour_18: float
    Hour_19: float
    Hour_20: float
    Hour_21: float
    Hour_22: float
    Hour_23: float

    @property
    def AverageValue(self) -> float:
        """Get the average value of the day."""
        return sum(self.Values) / len(self.Values)

    @property
    def bounds(self) -> tuple[float, float]:
        """Get the bounds of the day."""
        return min(self.Values), max(self.Values)

    @property
    def Values(self) -> list[float]:
        """Get the values of the day as a list."""
        return [
            self.Hour_00,
            self.Hour_01,
            self.Hour_02,
            self.Hour_03,
            self.Hour_04,
            self.Hour_05,
            self.Hour_06,
            self.Hour_07,
            self.Hour_08,
            self.Hour_09,
            self.Hour_10,
            self.Hour_11,
            self.Hour_12,
            self.Hour_13,
            self.Hour_14,
            self.Hour_15,
            self.Hour_16,
            self.Hour_17,
            self.Hour_18,
            self.Hour_19,
            self.Hour_20,
            self.Hour_21,
            self.Hour_22,
            self.Hour_23,
        ]

    @model_validator(mode="after")
    def validate_values(self):
        """Validate the values of the day are consistent with the schedule type limit."""
        # TODO: Implement with a eye for Archetypal

        lim_low = TypeLimits[self.Type].Lower_Limit_Value
        lim_high = TypeLimits[self.Type].Upper_Limit_Value
        if lim_low is not None and any(v < lim_low for v in self.Values):
            msg = f"Values are less than the lower limit: {lim_low}"
            raise ValueError(msg)
        if lim_high is not None and any(v > lim_high for v in self.Values):
            msg = f"Values are greater than the upper limit: {lim_high}"
            raise ValueError(msg)
        return self

    def add_day_to_idf(
        self, doc: IDFDocument, name_prefix: str | None
    ) -> tuple[IDFDocument, str]:
        """Add the day to the IDF document.

        The name prefix can be used to scope the schedule creation to ensure a unique schedule per object.

        Args:
            doc (IDFDocument): The IDF document to add the day to.
            name_prefix (str | None): The prefix to use for the schedule name.

        Returns:
            doc (IDFDocument): The IDF document with the day added.
            day_name (str): The name of the day schedule.
        """
        desired_name = self.Name
        if name_prefix is not None:
            desired_name = f"{name_prefix}_DAY_{desired_name}"

        if desired_name in doc["Schedule:Day:Hourly"]:
            return doc, desired_name

        day_sched = ScheduleDayHourly(
            Name=desired_name,
            Schedule_Type_Limits_Name=self.Type,
            Hour_1=self.Hour_00,
            Hour_2=self.Hour_01,
            Hour_3=self.Hour_02,
            Hour_4=self.Hour_03,
            Hour_5=self.Hour_04,
            Hour_6=self.Hour_05,
            Hour_7=self.Hour_06,
            Hour_8=self.Hour_07,
            Hour_9=self.Hour_08,
            Hour_10=self.Hour_09,
            Hour_11=self.Hour_10,
            Hour_12=self.Hour_11,
            Hour_13=self.Hour_12,
            Hour_14=self.Hour_13,
            Hour_15=self.Hour_14,
            Hour_16=self.Hour_15,
            Hour_17=self.Hour_16,
            Hour_18=self.Hour_17,
            Hour_19=self.Hour_18,
            Hour_20=self.Hour_19,
            Hour_21=self.Hour_20,
            Hour_22=self.Hour_21,
            Hour_23=self.Hour_22,
            Hour_24=self.Hour_23,
        )
        doc = day_sched.add(doc)
        return doc, day_sched.Name


class WeekComponent(NamedObject, extra="forbid"):
    """A week with a list of days."""

    Monday: DayComponent
    Tuesday: DayComponent
    Wednesday: DayComponent
    Thursday: DayComponent
    Friday: DayComponent
    Saturday: DayComponent
    Sunday: DayComponent

    @model_validator(mode="after")
    def validate_type_limits_are_consistent(self):
        """Validate that the type limits are consistent."""
        lim = self.Monday.Type
        for day in self.Days:
            if day.Type != lim:
                msg = "Type limits are not consistent"
                raise ValueError(msg)
        return self

    @property
    def bounds(self) -> tuple[float, float]:
        """Get the bounds of the week."""
        lows = [day.bounds[0] for day in self.Days]
        highs = [day.bounds[1] for day in self.Days]
        return min(lows), max(highs)

    @property
    def AverageValue(self) -> float:
        """Get the average value of the week."""
        return sum(day.AverageValue for day in self.Days) / len(self.Days)

    @property
    def Days(self) -> list[DayComponent]:
        """Get the days of the week as a list."""
        return [
            self.Monday,
            self.Tuesday,
            self.Wednesday,
            self.Thursday,
            self.Friday,
            self.Saturday,
            self.Sunday,
        ]

    def add_week_to_idf(
        self,
        doc: IDFDocument,
        name_prefix: str | None,
        summer_design_day_sch_name: str | None = None,
        winter_design_day_sch_name: str | None = None,
    ) -> tuple[IDFDocument, str]:
        """Add the week to the IDF document.

        The name prefix can be used to scope the schedule creation to ensure a unique schedule per object.

        Args:
            doc (IDFDocument): The IDF document to add the week to.
            name_prefix (str | None): The prefix to use for the schedule name.
            summer_design_day_sch_name (str | None): The name of the summer design day schedule.
            winter_design_day_sch_name (str | None): The name of the winter design day schedule.

        Returns:
            doc (IDFDocument): The IDF document with the week added.
            week_name (str): The name of the week schedule.
        """
        desired_name = self.Name
        if name_prefix is not None:
            desired_name = f"{name_prefix}_WEEK_{desired_name}"

        if desired_name in doc["Schedule:Week:Daily"]:
            return doc, desired_name

        doc, monday_name = self.Monday.add_day_to_idf(doc, name_prefix)
        doc, tuesday_name = self.Tuesday.add_day_to_idf(doc, name_prefix)
        doc, wednesday_name = self.Wednesday.add_day_to_idf(doc, name_prefix)
        doc, thursday_name = self.Thursday.add_day_to_idf(doc, name_prefix)
        doc, friday_name = self.Friday.add_day_to_idf(doc, name_prefix)
        doc, saturday_name = self.Saturday.add_day_to_idf(doc, name_prefix)
        doc, sunday_name = self.Sunday.add_day_to_idf(doc, name_prefix)
        week_sched = ScheduleWeekDaily(
            Name=desired_name,
            Monday_ScheduleDay_Name=monday_name,
            Tuesday_ScheduleDay_Name=tuesday_name,
            Wednesday_ScheduleDay_Name=wednesday_name,
            Thursday_ScheduleDay_Name=thursday_name,
            Friday_ScheduleDay_Name=friday_name,
            Saturday_ScheduleDay_Name=saturday_name,
            Sunday_ScheduleDay_Name=sunday_name,
            SummerDesignDay_ScheduleDay_Name=summer_design_day_sch_name,
            WinterDesignDay_ScheduleDay_Name=winter_design_day_sch_name,
        )
        doc = week_sched.add(doc)
        return doc, week_sched.Name

    @property
    def Type(self) -> ScheduleTypeLimitType:
        """Get the type limit of the week."""
        return self.Monday.Type


# class RepeatedWeekComponent(BaseModel, extra="forbid"):
#     """A week to repeat with a start and end date and a list of days."""

#     StartDay: int = Field(..., description="", ge=1, le=31)
#     StartMonth: int = Field(..., description="", ge=1, le=12)
#     EndDay: int = Field(..., description="", ge=1, le=31)
#     EndMonth: int = Field(..., description="", ge=1, le=12)
#     Week: WeekComponent

#     @model_validator(mode="after")
#     def validate_days(self):
#         """Validate the start and end days are valid for the chosen months."""
#         # check that the mm/dd for start is before the mm/dd for end
#         if self.StartMonth > self.EndMonth:
#             msg = "Start month must be before end month"
#             raise ValueError(msg)
#         if self.StartMonth == self.EndMonth and self.StartDay > self.EndDay:
#             msg = "Start day must be before end day"
#             raise ValueError(msg)

#         # check that the start day is valid for the chosen month (e.g. no 31 in february)
#         def check_day_valid_for_month(month: int, day: int):
#             if month in [1, 3, 5, 7, 8, 10, 12]:
#                 return day <= 31
#             elif month in [4, 6, 9, 11]:
#                 return day <= 30
#             elif month == 2:
#                 return day <= 29
#             else:
#                 msg = f"Invalid month: {month}"
#                 raise ValueError(msg)

#         start_day_is_valid = check_day_valid_for_month(self.StartMonth, self.StartDay)
#         if not start_day_is_valid:
#             msg = f"Start day {self.StartDay} is invalid for the chosen month: {self.StartMonth}"
#             raise ValueError(msg)

#         end_day_is_valid = check_day_valid_for_month(self.EndMonth, self.EndDay)
#         if not end_day_is_valid:
#             msg = f"End day {self.EndDay} is invalid for the chosen month: {self.EndMonth}"
#             raise ValueError(msg)

#         return self

# TODO: change flow rate to water use.
YearScheduleCategory = Literal[
    "Equipment", "Lighting", "Occupancy", "WaterUse", "Setpoint", "Window"
]


class YearComponent(NamedObject, extra="forbid"):
    """A year with a schedule type limit and a list of repeated weeks."""

    Type: YearScheduleCategory = Field(
        ..., description="The system that the schedule is applicable to."
    )
    January: WeekComponent
    February: WeekComponent
    March: WeekComponent
    April: WeekComponent
    May: WeekComponent
    June: WeekComponent
    July: WeekComponent
    August: WeekComponent
    September: WeekComponent
    October: WeekComponent
    November: WeekComponent
    December: WeekComponent

    @property
    def AverageValue(self) -> float:
        """Get the average value of the year."""
        return sum(week.AverageValue for week in self.Weeks) / len(self.Weeks)

    @property
    def MonthlyAverageValues(self) -> list[float]:
        """Get the average values of the year."""
        return [week.AverageValue for week in self.Weeks]

    @property
    def bounds(self) -> tuple[float, float]:
        """Get the bounds of the year."""
        lows = [week.bounds[0] for week in self.Weeks]
        highs = [week.bounds[1] for week in self.Weeks]
        return min(lows), max(highs)

    @property
    def Weeks(self) -> list[WeekComponent]:
        """Get the weeks of the year as a list."""
        return [
            self.January,
            self.February,
            self.March,
            self.April,
            self.May,
            self.June,
            self.July,
            self.August,
            self.September,
            self.October,
            self.November,
            self.December,
        ]

    @model_validator(mode="after")
    def check_weeks_have_consistent_type(self):
        """Check that the weeks have a consistent type."""
        lim = self.January.Type
        for week in self.Weeks:
            if week.Type != lim:
                msg = "Type limits are not consistent"
                raise ValueError(msg)

        return self

    @property
    def schedule_type_limits(self):
        """Get the schedule type limits for the year."""
        return self.January.Type

    def add_year_to_idf(
        self,
        doc: IDFDocument,
        name_prefix: str | None = None,
        summer_design_day_sch_name: str | None = None,
        winter_design_day_sch_name: str | None = None,
    ):
        """Add the year to the IDF document.

        The name prefix can be used to scope the schedule creation to ensure a unique schedule per object.

        Args:
            doc (IDFDocument): The IDF document to add the year to.
            name_prefix (str | None): The prefix to use for the schedule name.
            summer_design_day_sch_name (str | None): The name of the summer design day schedule.
            winter_design_day_sch_name (str | None): The name of the winter design day schedule.

        Returns:
            doc (IDFDocument): The IDF document with the year added.
            year_name (str): The name of the year schedule.
        """
        desired_name = self.Name
        if name_prefix is not None:
            desired_name = f"{name_prefix}_YEAR_{desired_name}"

        if desired_name in doc["Schedule:Year"]:
            return doc, desired_name

        doc, jan_name = self.January.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, feb_name = self.February.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, mar_name = self.March.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, apr_name = self.April.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, may_name = self.May.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, jun_name = self.June.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, jul_name = self.July.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, aug_name = self.August.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, sep_name = self.September.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, oct_name = self.October.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, nov_name = self.November.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        doc, dec_name = self.December.add_week_to_idf(
            doc,
            name_prefix,
            summer_design_day_sch_name=summer_design_day_sch_name,
            winter_design_day_sch_name=winter_design_day_sch_name,
        )
        year_sched = ScheduleYear(
            Name=self.Name,
            Schedule_Type_Limits_Name=self.schedule_type_limits,
            ScheduleWeek_Name_1=jan_name,
            Start_Month_1=1,
            Start_Day_1=1,
            End_Month_1=1,
            End_Day_1=31,
            ScheduleWeek_Name_2=feb_name,
            Start_Month_2=2,
            Start_Day_2=1,
            End_Month_2=2,
            End_Day_2=28,
            ScheduleWeek_Name_3=mar_name,
            Start_Month_3=3,
            Start_Day_3=1,
            End_Month_3=3,
            End_Day_3=31,
            ScheduleWeek_Name_4=apr_name,
            Start_Month_4=4,
            Start_Day_4=1,
            End_Month_4=4,
            End_Day_4=30,
            ScheduleWeek_Name_5=may_name,
            Start_Month_5=5,
            Start_Day_5=1,
            End_Month_5=5,
            End_Day_5=31,
            ScheduleWeek_Name_6=jun_name,
            Start_Month_6=6,
            Start_Day_6=1,
            End_Month_6=6,
            End_Day_6=30,
            ScheduleWeek_Name_7=jul_name,
            Start_Month_7=7,
            Start_Day_7=1,
            End_Month_7=7,
            End_Day_7=31,
            ScheduleWeek_Name_8=aug_name,
            Start_Month_8=8,
            Start_Day_8=1,
            End_Month_8=8,
            End_Day_8=31,
            ScheduleWeek_Name_9=sep_name,
            Start_Month_9=9,
            Start_Day_9=1,
            End_Month_9=9,
            End_Day_9=30,
            ScheduleWeek_Name_10=oct_name,
            Start_Month_10=10,
            Start_Day_10=1,
            End_Month_10=10,
            End_Day_10=31,
            ScheduleWeek_Name_11=nov_name,
            Start_Month_11=11,
            Start_Day_11=1,
            End_Month_11=11,
            End_Day_11=30,
            ScheduleWeek_Name_12=dec_name,
            Start_Month_12=12,
            Start_Day_12=1,
            End_Month_12=12,
            End_Day_12=31,
        )
        doc = year_sched.add(doc)

        type_lim = self.schedule_type_limits
        if type_lim not in doc["ScheduleTypeLimits"]:
            if type_lim not in TypeLimits:
                msg = f"Type {type_lim} not in TypeLimits, unsure how to add to IDF."
                raise ValueError(msg)
            lim = TypeLimits[type_lim]
            lim.add(doc)

        return doc, year_sched.Name

    def fractional_year_sum(self, year: int):
        """Compute the sum of the year as a fraction of the year."""
        if self.schedule_type_limits != "Fraction":
            msg = "Schedule type limits are not Fraction, cannot compute year sum."
            raise ValueError(msg)

        # get the numer of Mondays in each month, tuesdays in each month, etc.

        def get_num_days_in_month(
            month: Literal[
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ],
            year: int,
            day_of_week: Literal[
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ],
        ):
            """Get the number of days in a month for a given year and day of the week."""
            # get the number of days in the month
            month_map = {
                "January": 1,
                "February": 2,
                "March": 3,
                "April": 4,
                "May": 5,
                "June": 6,
                "July": 7,
                "August": 8,
                "September": 9,
                "October": 10,
                "November": 11,
                "December": 12,
            }
            _weekday, num_days = calendar.monthrange(year, month_map[month])

            # get the number of days of the week in the month
            days_of_week = [calendar.day_name[(day + 1) % 7] for day in range(num_days)]
            return days_of_week.count(day_of_week)

        # get the number of Mondays in each month
        months: list[
            Literal[
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ]
        ] = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
        num_mondays = [get_num_days_in_month(month, year, "Monday") for month in months]
        num_tuesdays = [
            get_num_days_in_month(month, year, "Tuesday") for month in months
        ]
        num_wednesdays = [
            get_num_days_in_month(month, year, "Wednesday") for month in months
        ]
        num_thursdays = [
            get_num_days_in_month(month, year, "Thursday") for month in months
        ]
        num_fridays = [get_num_days_in_month(month, year, "Friday") for month in months]
        num_saturdays = [
            get_num_days_in_month(month, year, "Saturday") for month in months
        ]
        num_sundays = [get_num_days_in_month(month, year, "Sunday") for month in months]

        monday_sums = [
            sum(getattr(self, month).Monday.Values) * num_days
            for month, num_days in zip(months, num_mondays, strict=True)
        ]
        tuesday_sums = [
            sum(getattr(self, month).Tuesday.Values) * num_days
            for month, num_days in zip(months, num_tuesdays, strict=True)
        ]
        wednesday_sums = [
            sum(getattr(self, month).Wednesday.Values) * num_days
            for month, num_days in zip(months, num_wednesdays, strict=True)
        ]
        thursday_sums = [
            sum(getattr(self, month).Thursday.Values) * num_days
            for month, num_days in zip(months, num_thursdays, strict=True)
        ]
        friday_sums = [
            sum(getattr(self, month).Friday.Values) * num_days
            for month, num_days in zip(months, num_fridays, strict=True)
        ]
        saturday_sums = [
            sum(getattr(self, month).Saturday.Values) * num_days
            for month, num_days in zip(months, num_saturdays, strict=True)
        ]
        sunday_sums = [
            sum(getattr(self, month).Sunday.Values) * num_days
            for month, num_days in zip(months, num_sundays, strict=True)
        ]

        monday_sum = sum(monday_sums)
        tuesday_sum = sum(tuesday_sums)
        wednesday_sum = sum(wednesday_sums)
        thursday_sum = sum(thursday_sums)
        friday_sum = sum(friday_sums)
        saturday_sum = sum(saturday_sums)
        sunday_sum = sum(sunday_sums)

        annual_sum = (
            monday_sum
            + tuesday_sum
            + wednesday_sum
            + thursday_sum
            + friday_sum
            + saturday_sum
            + sunday_sum
        )
        days_in_year = calendar.isleap(year) * 366 + (1 - calendar.isleap(year)) * 365

        return annual_sum / (days_in_year * 24)

    @field_validator("Name")
    def validate_name(cls, v):
        """Validate the name of the schedule, specifically that it cannot be a protected name."""
        if v in PROTECTED_SCHEDULE_NAMES or "Activity_Schedule" in v:
            msg = f"Schedule name {v} is protected, please choose another name."
            raise ValueError(msg)
        return v
