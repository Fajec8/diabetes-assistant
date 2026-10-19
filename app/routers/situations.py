import uuid
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import (
    ensure_user_access,
    get_current_user,
)
from app.services.history_search import (
    find_similar_situations,
)
from app.services.situation_builder import (
    build_situation,
)


router = APIRouter(
    prefix="/situations",
    tags=["Situations"]
)


@router.get(
    "/build"
)
def get_situation(
    user_id: uuid.UUID,
    timestamp: datetime,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        get_current_user
    )
):
    ensure_user_access(
        requested_user_id=
            user_id,

        current_user=
            current_user
    )

    if timestamp.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Timestamp must contain "
                "timezone information"
            )
        )

    try:
        return build_situation(
            db=db,
            user_id=current_user.id,
            t0=timestamp
        )

    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )


@router.get(
    "/similar"
)
def get_similar_situations(
    user_id: uuid.UUID,
    timestamp: datetime,
    limit: int = 10,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        get_current_user
    )
):
    ensure_user_access(
        requested_user_id=
            user_id,

        current_user=
            current_user
    )

    if timestamp.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Timestamp must contain "
                "timezone information"
            )
        )

    if (
        limit < 1
        or limit > 20
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Limit must be "
                "between 1 and 20"
            )
        )

    try:
        return (
            find_similar_situations(
                db=db,
                user_id=
                    current_user.id,
                t0=timestamp,
                limit=limit
            )
        )

    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )