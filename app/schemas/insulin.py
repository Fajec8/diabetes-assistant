import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InsulinCreate(BaseModel):
    user_id: uuid.UUID

    meal_id: uuid.UUID | None = None

    insulin_type: Literal[
        "NOVORAPID",
        "TRESIBA"
    ]

    units: float = Field(
        gt=0
    )

    administered_at: datetime

    source: str = "MANUAL"

    note: str | None = Field(
        default=None,
        max_length=500
    )


class InsulinResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: uuid.UUID
    user_id: uuid.UUID

    meal_id: uuid.UUID | None

    insulin_type: str
    units: float

    administered_at: datetime
    source: str

    note: str | None
    created_at: datetime