from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CustomFoodValuesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    basis_type: Literal["per_100g", "per_100ml", "per_serving"]
    basis_amount: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    calories: float = Field(ge=0)
    carbs: float = Field(ge=0)
    protein: float = Field(ge=0)
    fat: float = Field(ge=0)
    @model_validator(mode="after")
    def require_basis_unit(self):
        expected = {
            "per_100g": "g",
            "per_100ml": "ml",
        }.get(self.basis_type)
        if expected is not None and self.unit != expected:
            raise ValueError("unit is incompatible with nutrition basis")
        return self


class CustomFoodRequest(CustomFoodValuesRequest):
    aliases: list[str] = Field(default_factory=list, max_length=20)


class DraftCustomFoodRequest(CustomFoodValuesRequest):
    pass


class MealDraftItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    amount: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    catalog_food_id: str | None = Field(default=None, min_length=1)
    custom_food: DraftCustomFoodRequest | None = None

    @model_validator(mode="after")
    def require_exactly_one_food_source(self):
        if (self.catalog_food_id is None) == (self.custom_food is None):
            raise ValueError("exactly one food source is required")
        return self


class MealDraftMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    log_date: date
    name: str = Field(min_length=1, max_length=100)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "custom"]
    entry_method: Literal["form"] = "form"
    items: list[MealDraftItemRequest] = Field(
        default_factory=list,
        max_length=50,
    )
