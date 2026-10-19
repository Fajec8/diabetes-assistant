from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.insulin import InsulinDose
from app.models.meal import Meal
from app.models.user import User
from app.schemas.insulin import (
    InsulinCreate,
    InsulinResponse,
)


router = APIRouter(
    prefix="/insulin",
    tags=["Insulin"]
)


@router.post(
    "",
    response_model=InsulinResponse,
    status_code=status.HTTP_201_CREATED
)
def create_insulin_dose(
    data: InsulinCreate,
    db: Session = Depends(get_db)
):
    user = db.get(
        User,
        data.user_id
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if (
        data.meal_id is not None
    ):
        if (
            data.insulin_type
            != "NOVORAPID"
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Only NOVORAPID can be "
                    "linked to a meal"
                )
            )

        meal = db.get(
            Meal,
            data.meal_id
        )

        if meal is None:
            raise HTTPException(
                status_code=404,
                detail="Meal not found"
            )

        if (
            meal.user_id
            != data.user_id
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Meal belongs to "
                    "a different user"
                )
            )

    dose = InsulinDose(
        user_id=data.user_id,
        meal_id=data.meal_id,
        insulin_type=data.insulin_type,
        units=data.units,
        administered_at=data.administered_at,
        source=data.source,
        note=data.note
    )

    db.add(
        dose
    )

    db.commit()

    db.refresh(
        dose
    )

    return dose