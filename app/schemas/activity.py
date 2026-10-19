import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ActivityCreate(BaseModel):
    user_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    activity_type: Literal[
        "GYM",
        "RUNNING",
        "CYCLING",
        "TEAM_SPORT",
        "WALKING",
        "OTHER"
    ]
    intensity: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    note: str | None = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    activity_type: str
    intensity: str | None
    note: str | None
    created_at: datetime
