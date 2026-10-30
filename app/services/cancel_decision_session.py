from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.decision_session import DecisionSession


CANCELLABLE_SESSION_STATUSES = (
    "WAITING_USER_PLAN",
    "WAITING_OUTCOME",
)


def cancel_decision_session(
    db: Session,
    session_id: uuid.UUID,
) -> DecisionSession:
    session = db.get(
        DecisionSession,
        session_id,
    )

    if session is None:
        raise KeyError(
            "Decision session not found"
        )

    if session.status == "CANCELLED":
        return session

    if (
        session.status
        not in CANCELLABLE_SESSION_STATUSES
    ):
        raise RuntimeError(
            "Only an active decision session "
            "can be cancelled"
        )

    session.status = "CANCELLED"

    db.commit()
    db.refresh(
        session
    )

    return session