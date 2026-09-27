"""Pydantic models for the LibreLinkUp payloads this server reads."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_TIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.strptime(value, _TIME_FORMAT)


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="ignore")


class Patient(_Model):
    id: UUID
    patient_id: UUID = Field(alias="patientId")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")


class Trend(IntEnum):
    UNKNOWN = 0
    DOWN_FAST = 1
    DOWN_SLOW = 2
    STABLE = 3
    UP_SLOW = 4
    UP_FAST = 5

    @property
    def indicator(self) -> str:
        return _ARROWS[self]


_ARROWS = {
    Trend.UNKNOWN: "?",
    Trend.DOWN_FAST: "↓",
    Trend.DOWN_SLOW: "↘",
    Trend.STABLE: "→",
    Trend.UP_SLOW: "↗",
    Trend.UP_FAST: "↑",
}


class GlucoseMeasurement(_Model):
    timestamp: datetime = Field(alias="Timestamp")  # sensor local time, no offset
    factory_timestamp: datetime = Field(alias="FactoryTimestamp")  # UTC
    value: float = Field(alias="Value")
    value_in_mg_per_dl: float = Field(alias="ValueInMgPerDl")
    glucose_units: int = Field(alias="GlucoseUnits")  # 1 = mg/dL, 0 = mmol/L
    is_high: bool = Field(alias="isHigh")
    is_low: bool = Field(alias="isLow")

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_local(cls, value: Any) -> datetime:
        return _parse_time(value)

    @field_validator("factory_timestamp", mode="before")
    @classmethod
    def _parse_utc(cls, value: Any) -> datetime:
        return _parse_time(value).replace(tzinfo=UTC)


class GlucoseMeasurementWithTrend(GlucoseMeasurement):
    trend: Trend = Field(default=Trend.UNKNOWN, alias="TrendArrow")

    @field_validator("trend", mode="before")
    @classmethod
    def _parse_trend(cls, value: Any) -> Trend:
        try:
            return Trend(value)
        except (TypeError, ValueError):
            return Trend.UNKNOWN
