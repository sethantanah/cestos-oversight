import calendar
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class TimesheetDayInput(BaseModel):
    work_date: date
    hours: Decimal = Field(ge=0, le=24, max_digits=6, decimal_places=2)


class EmployeeTimesheetWrite(BaseModel):
    employee_id: uuid.UUID
    project_id: uuid.UUID | None = None
    period_start: date
    site_name: str | None = Field(default=None, max_length=200)
    entries: list[TimesheetDayInput] = Field(default_factory=list, max_length=31)

    @model_validator(mode="after")
    def validate_period_and_days(self) -> "EmployeeTimesheetWrite":
        if self.period_start.day != 1:
            raise ValueError("Period start must be the first day of the month")
        days_in_month = calendar.monthrange(self.period_start.year, self.period_start.month)[1]
        seen: set[date] = set()
        for entry in self.entries:
            if (entry.work_date.year, entry.work_date.month) != (self.period_start.year, self.period_start.month):
                raise ValueError("Every daily entry must be within the selected month")
            if entry.work_date in seen:
                raise ValueError("A day can only be entered once")
            if entry.work_date.day > days_in_month:
                raise ValueError("The selected day is not valid for this month")
            seen.add(entry.work_date)
        return self
