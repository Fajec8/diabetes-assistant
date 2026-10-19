from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.activity import Activity
from app.models.user import User
from app.routers.auth import (
    ensure_user_access,
    get_current_user,
)
from app.schemas.activity import (
    ActivityCreate,
    ActivityResponse,
)


router = APIRouter(
    prefix="/activities",
    tags=["Activities"]
)


@router.post(
    "",
    response_model=ActivityResponse,
    status_code=status.HTTP_201_CREATED
)
def create_activity(
    data: ActivityCreate,
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
        data.ended_at
        <= data.started_at
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Activity end must "
                "be after start"
            )
        )

    activity = Activity(
        user_id=current_user.id,
        started_at=data.started_at,
        ended_at=data.ended_at,
        activity_type=
            data.activity_type,
        intensity=
            data.intensity,
        note=data.note
    )

    db.add(
        activity
    )

    db.commit()

    db.refresh(
        activity
    )

    return activity