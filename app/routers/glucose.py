from fastapi import (
    APIRouter,
    Depends,
    status,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.glucose import GlucoseReading
from app.models.user import User
from app.routers.auth import (
    ensure_user_access,
    get_current_user,
)
from app.schemas.glucose import (
    GlucoseCreate,
    GlucoseResponse,
)


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
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        get_current_user
    )
):
    ensure_user_access(
        requested_user_id=
            data.user_id,

        current_user=
            current_user
    )

    reading = GlucoseReading(
        user_id=current_user.id,
        measured_at=data.measured_at,
        value_mmol_l=data.value_mmol_l,
        source=data.source
    )

    db.add(
        reading
    )

    db.commit()

    db.refresh(
        reading
    )

    return reading