from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.glucose import GlucoseReading
from app.models.user import User
from app.schemas.glucose import GlucoseCreate, GlucoseResponse


router = APIRouter(
    prefix="/glucose",
    tags=["Glucose"]
)


@router.post(
    "",
    response_model=GlucoseResponse,
    status_code=status.HTTP_201_CREATED
)
def create_glucose_reading(
    data: GlucoseCreate,
    db: Session = Depends(get_db)
):
    user = db.get(User, data.user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    reading = GlucoseReading(
        user_id=data.user_id,
        measured_at=data.measured_at,
        value_mmol_l=data.value_mmol_l,
        source=data.source
    )

    db.add(reading)
    db.commit()
    db.refresh(reading)

    return reading
