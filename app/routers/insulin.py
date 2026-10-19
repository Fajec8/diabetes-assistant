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
from app.routers.auth import (
    ensure_user_access,
    get_current_user,
)
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

    if (
        data.meal_id
        is not None
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

        if (
            meal is None
            or meal.user_id
            != current_user.id
        ):
            raise HTTPException(
                status_code=404,
                detail="Meal not found"
            )

    dose = InsulinDose(
        user_id=current_user.id,
        meal_id=data.meal_id,
        insulin_type=
            data.insulin_type,
        units=data.units,
        administered_at=
            data.administered_at,
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