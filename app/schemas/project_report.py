import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectReportCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    site_id: uuid.UUID
    report_type: Literal["DRILLING_UPDATE", "PROGRESS_UPDATE", "SAFETY_REPORT", "SITE_ISSUE"]
    report_date: date
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=20000)
    metres: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    drill_holes: int | None = Field(default=None, ge=0, le=2147483647)
    average_depth: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.report_date > datetime.now(UTC).date():
            raise ValueError("Report date cannot be in the future")
        values = (self.metres, self.drill_holes, self.average_depth)
        if self.report_type == "DRILLING_UPDATE":
            if any(v is None for v in values):
                raise ValueError("Drilling updates require metres, drill holes and average depth")
            if self.drill_holes == 0 and self.average_depth != 0:
                raise ValueError("Average depth must be zero when no holes are reported")
        elif any(v is not None for v in values):
            raise ValueError("Drilling metrics are only accepted for drilling updates")
        return self


class ProjectReportUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    site_id: uuid.UUID | None = None
    report_type: Literal["DRILLING_UPDATE", "PROGRESS_UPDATE", "SAFETY_REPORT", "SITE_ISSUE"] | None = None
    report_date: date | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=20000)
    metres: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    drill_holes: int | None = Field(default=None, ge=0, le=2147483647)
    average_depth: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
