from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.decision_session import (
    DecisionSession,
)


ACTIVE_SESSION_STATUSES = (
    "WAITING_USER_PLAN",
    "WAITING_OUTCOME",
)


def get_active_decision_session_ids(
    db: Session,
    user_id: uuid.UUID,
) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(
                DecisionSession.id
            )
            .where(
                DecisionSession.user_id
                == user_id,

                DecisionSession.status.in_(
                    ACTIVE_SESSION_STATUSES
                ),
            )
            .order_by(
                DecisionSession.decision_at.desc(),
                DecisionSession.created_at.desc(),
            )
        )
        .all()
    )