from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


if TYPE_CHECKING:
    from app.models.meal import Meal


class MealAssessment(Base):
    __tablename__ = "meal_assessments"

    __table_args__ = (
        CheckConstraint(
            (
                "reported_prebolus_minutes IS NULL "
                "OR reported_prebolus_minutes >= 0"
            ),
            name="ck_meal_assessment_prebolus_nonnegative",
        ),
        CheckConstraint(
            (
                "insulin_feedback IS NULL "
                "OR insulin_feedback IN "
                "('TOO_LITTLE', 'OK', 'TOO_MUCH')"
            ),
            name="ck_meal_assessment_feedback_valid",
        ),
        CheckConstraint(
            (
                "reported_meal_type IS NULL "
                "OR reported_meal_type IN "
                "('BREAKFAST', 'LUNCH', 'DINNER')"
            ),
            name="ck_meal_assessment_meal_type_valid",
        ),
        CheckConstraint(
            (
                "NOT ("
                "prebolus_explicit_none = TRUE "
                "AND reported_prebolus_minutes IS NOT NULL"
                ")"
            ),
            name="ck_meal_assessment_prebolus_consistent",
        ),
        UniqueConstraint(
            "meal_id",
            name="uq_meal_assessment_meal_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    meal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meals.id",
            name="fk_meal_assessments_meal_id_meals",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    reported_prebolus_minutes: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    prebolus_explicit_none: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    insulin_feedback: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    reported_meal_type: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    timing_note: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    raw_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    meal: Mapped["Meal"] = relationship(
        back_populates="assessment",
    )