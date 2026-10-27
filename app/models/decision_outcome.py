from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DecisionOutcome(Base):
    __tablename__ = "decision_outcomes"

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            name="uq_decision_outcome_session",
        ),
        CheckConstraint(
            (
                "quality_score IS NULL "
                "OR "
                "("
                "quality_score >= 0 "
                "AND quality_score <= 100"
                ")"
            ),
            name="ck_decision_outcome_quality",
        ),
        CheckConstraint(
            (
                "confidence IS NULL "
                "OR "
                "("
                "confidence >= 0 "
                "AND confidence <= 100"
                ")"
            ),
            name="ck_decision_outcome_confidence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "decision_sessions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    baseline_glucose: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    glucose_30m: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    glucose_60m: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    glucose_90m: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    glucose_120m: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    glucose_180m: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    quality_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    quality_status: Mapped[
        str | None
    ] = mapped_column(
        String(30),
        nullable=True,
    )

    confidence: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    confidence_level: Mapped[
        str | None
    ] = mapped_column(
        String(20),
        nullable=True,
    )

    low_detected: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    high_detected: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    outcome_snapshot: Mapped[
        dict | None
    ] = mapped_column(
        JSON,
        nullable=True,
    )

    evaluated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )