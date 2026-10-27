from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DecisionSession(Base):
    __tablename__ = "decision_sessions"

    __table_args__ = (
        CheckConstraint(
            (
                "status IN ("
                "'WAITING_USER_PLAN', "
                "'WAITING_OUTCOME', "
                "'COMPLETED', "
                "'CANCELLED'"
                ")"
            ),
            name="ck_decision_session_status",
        ),
        Index(
            "ix_decision_session_user_decision_at",
            "user_id",
            "decision_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    decision_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="WAITING_USER_PLAN",
    )

    # Neměnný snapshot faktů dostupných
    # v okamžiku rozhodnutí.
    #
    # Neobsahuje USER ani SYSTEM plán.
    input_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )