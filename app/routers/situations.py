import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.situation_builder import build_situation

from app.services.history_search import find_similar_situations


router = APIRouter(
    prefix="/situations",
    tags=["Situations"]
)


@router.get("/build")
def get_situation(
    user_id: uuid.UUID,
    timestamp: datetime,
    db: Session = Depends(get_db)
):
    if timestamp.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail="Timestamp must contain timezone information"
        )

    try:
        return build_situation(
            db=db,
            user_id=user_id,
            t0=timestamp
        )

    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

@router.get("/similar")
def get_similar_situations(
    user_id: uuid.UUID,
    timestamp: datetime,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    if timestamp.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail="Timestamp must contain timezone information"
        )

    if limit < 1 or limit > 20:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 20"
        )

    try:
        return find_similar_situations(
            db=db,
            user_id=user_id,
            t0=timestamp,
            limit=limit
        )

    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
