from __future__ import annotations

import uuid
from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.services.active_decision_session import (
    ACTIVE_SESSION_MAX_AGE_HOURS,
    ACTIVE_SESSION_STATUSES,
    get_active_decision_session_id,
)


def test_active_session_statuses():
    assert ACTIVE_SESSION_STATUSES == (
        "WAITING_USER_PLAN",
        "WAITING_OUTCOME",
    )


def test_active_session_max_age():
    assert (
        ACTIVE_SESSION_MAX_AGE_HOURS
        == 24
    )


def test_get_active_decision_session_id():
    db = Mock(
        spec=Session
    )

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()

    db.scalar.return_value = (
        session_id
    )

    result = (
        get_active_decision_session_id(
            db=db,
            user_id=user_id,
        )
    )

    assert result == session_id

    db.scalar.assert_called_once()


def test_get_active_decision_session_id_returns_none():
    db = Mock(
        spec=Session
    )

    user_id = uuid.uuid4()

    db.scalar.return_value = None

    result = (
        get_active_decision_session_id(
            db=db,
            user_id=user_id,
        )
    )

    assert result is None

    db.scalar.assert_called_once()