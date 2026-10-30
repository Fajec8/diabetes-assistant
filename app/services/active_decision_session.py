from __future__ import annotations

import uuid
from datetime import (
    datetime,
    timedelta,
    timezone,
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.decision_session import DecisionSession


ACTIVE_SESSION_STATUSES = (
    "WAITING_USER_PLAN",
    "WAITING_OUTCOME",
)

ACTIVE_SESSION_MAX_AGE_HOURS = 24


def get_active_decision_session_id(
    db: Session,
    user_id: uuid.UUID,
) -> uuid.UUID | None:
    cutoff = (
        datetime.now(
            timezone.utc
        )
        - timedelta(
            hours=
                ACTIVE_SESSION_MAX_AGE_HOURS
        )
    )

    statement = (
        select(
            DecisionSession.id
        )
        .where(
            DecisionSession.user_id
            == user_id,

            DecisionSession.status.in_(
                ACTIVE_SESSION_STATUSES
            ),

            DecisionSession.created_at
            >= cutoff,
        )
        .order_by(
            DecisionSession.decision_at.desc(),
            DecisionSession.created_at.desc(),
        )
        .limit(1)
    )

    return db.scalar(
        statement
    )