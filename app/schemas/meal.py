import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MealItemCreate(BaseModel):
    food_name: str = Field(
        min_length=1,
        max_length=120
    )

    preparation: str | None = Field(
        default=None,
        max_length=80
    )

    variant: str | None = Field(
        default=None,
        max_length=120
    )

    amount_g: float | None = Field(
        default=None,
        gt=0
    )

    carbohydrates_g: float | None = Field(
        default=None,
        ge=0
    )

    note: str | None = Field(
        default=None,
        max_length=500
    )


class MealItemResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: uuid.UUID
    meal_id: uuid.UUID

    food_name: str
    preparation: str | None
    variant: str | None

    amount_g: float | None
    carbohydrates_g: float | None

    note: str | None
    created_at: datetime


class MealCreate(BaseModel):
    user_id: uuid.UUID

    eaten_at: datetime

    carbohydrates_g: float = Field(
        ge=0
    )

    description: str | None = Field(
        default=None,
        max_length=255
    )

    note: str | None = Field(
        default=None,
        max_length=500
    )

    items: list[MealItemCreate] = Field(
        default_factory=list
    )


class MealResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: uuid.UUID
    user_id: uuid.UUID

    eaten_at: datetime
    carbohydrates_g: float

    description: str | None
    note: str | None

    created_at: datetime

    items: list[MealItemResponse] = Field(
        default_factory=list
    )


class MealBolusDoseResponse(BaseModel):
    part: int

    dose_id: uuid.UUID

    units: float

    administered_at: datetime

    relative_to_meal_minutes: float

    percentage_of_total: float | None

    fraction_of_total: str | None


class MealBolusAnalysisResponse(BaseModel):
    meal_id: uuid.UUID

    eaten_at: datetime

    carbohydrates_g: float

    strategy: str

    dose_count: int

    total_bolus_units: float

    prebolus_minutes: float | None

    first_dose_relative_minutes: float | None

    split: bool

    split_ratio: str | None

    doses: list[MealBolusDoseResponse]