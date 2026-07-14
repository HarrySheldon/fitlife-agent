from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, field_validator


AppLanguage = Literal["en-US", "zh-CN"]
UnitSystem = Literal["metric", "imperial"]


def validate_iana_timezone(value: str) -> str:
    timezone = value.strip()
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Timezone must be a valid IANA timezone") from None
    return timezone


class UserPreferences(BaseModel):
    language: AppLanguage = "en-US"
    unit_system: UnitSystem = "metric"
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return validate_iana_timezone(value)

