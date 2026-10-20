"""Synthetic business contract; never contains a user's records or profile."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConnectionBusinessSample(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    food: Literal["oats"]
    amount: int = Field(ge=1, le=100000)
    unit: Literal["g"]


def check_business_sample(output: BaseModel) -> None:
    sample = ConnectionBusinessSample.model_validate(output.model_dump())
    if sample.amount != 40:
        raise ValueError("The synthetic food amount was not preserved")
