from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.services.cancel_decision_session import (
    CANCELLABLE_SESSION_STATUSES,
    cancel_decision_session,
)


def test_cancellable_session_statuses():
    assert CANCELLABLE_SESSION_STATUSES == (
        "WAITING_USER_PLAN",
        "WAITING_OUTCOME",
    )


def test_cancel_active_decision_session():
    db = Mock(
        spec=Session
    )

    session = SimpleNamespace(
        status="WAITING_OUTCOME"
    )

    db.get.return_value = session

    session_id = uuid.uuid4()

    result = cancel_decision_session(
        db=db,
        session_id=session_id,
    )

    assert result is session
    assert session.status == "CANCELLED"

    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(
        session
    )


def test_cancel_is_idempotent():
    db = Mock(
        spec=Session
    )

    session = SimpleNamespace(
        status="CANCELLED"
    )

    db.get.return_value = session

    result = cancel_decision_session(
        db=db,
        session_id=uuid.uuid4(),
    )

    assert result is session
    assert session.status == "CANCELLED"

    db.commit.assert_not_called()
    db.refresh.assert_not_called()


def test_completed_session_cannot_be_cancelled():
    db = Mock(
        spec=Session
    )

    session = SimpleNamespace(
        status="COMPLETED"
    )

    db.get.return_value = session

    with pytest.raises(
        RuntimeError,
        match=(
            "Only an active decision session "
            "can be cancelled"
        ),
    ):
        cancel_decision_session(
            db=db,
            session_id=uuid.uuid4(),
        )

    db.commit.assert_not_called()


def test_cancel_missing_session():
    db = Mock(
        spec=Session
    )

    db.get.return_value = None

    with pytest.raises(
        KeyError,
        match="Decision session not found",
    ):
        cancel_decision_session(
            db=db,
            session_id=uuid.uuid4(),
        )

    db.commit.assert_not_called()