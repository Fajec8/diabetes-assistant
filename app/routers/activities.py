from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.activity import Activity
from app.models.user import User
from app.schemas.activity import ActivityCreate, ActivityResponse


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
    db: Session = Depends(get_db)
):
    user = db.get(User, data.user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if data.ended_at <= data.started_at:
        raise HTTPException(
            status_code=400,
            detail="Activity end must be after start"
        )

    activity = Activity(
        user_id=data.user_id,
        started_at=data.started_at,
        ended_at=data.ended_at,
        activity_type=data.activity_type,
        intensity=data.intensity,
        note=data.note
    )

    db.add(activity)
    db.commit()
    db.refresh(activity)

    return activity
