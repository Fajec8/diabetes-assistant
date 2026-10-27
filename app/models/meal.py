from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


if TYPE_CHECKING:
    from app.models.insulin import InsulinDose
    from app.models.meal_assessment import MealAssessment
    from app.models.meal_item import MealItem


class Meal(Base):
    __tablename__ = "meals"

    __table_args__ = (
        CheckConstraint(
            "carbohydrates_g >= 0",
            name="ck_meal_carbohydrates_nonnegative",
        ),
        Index(
            "ix_meal_user_eaten_at",
            "user_id",
            "eaten_at",
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

    eaten_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    carbohydrates_g: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    note: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    items: Mapped[list["MealItem"]] = relationship(
        back_populates="meal",
        cascade="all, delete-orphan",
        order_by="MealItem.created_at",
    )

    insulin_doses: Mapped[list["InsulinDose"]] = relationship(
        back_populates="meal",
    )

    assessment: Mapped["MealAssessment | None"] = relationship(
        back_populates="meal",
        uselist=False,
        cascade="all, delete-orphan",
    )