import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GlucoseCreate(BaseModel):
    user_id: uuid.UUID
    measured_at: datetime
    value_mmol_l: float = Field(gt=0)
    source: str = "MANUAL"


class GlucoseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    measured_at: datetime
    value_mmol_l: float
    source: str
    created_at: datetime
