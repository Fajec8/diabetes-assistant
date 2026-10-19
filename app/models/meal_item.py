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
    from app.models.meal import Meal


class MealItem(Base):
    __tablename__ = "meal_items"

    __table_args__ = (
        CheckConstraint(
            (
                "amount_g IS NULL "
                "OR amount_g > 0"
            ),
            name="ck_meal_item_amount_positive"
        ),
        CheckConstraint(
            (
                "carbohydrates_g IS NULL "
                "OR carbohydrates_g >= 0"
            ),
            name="ck_meal_item_carbohydrates_nonnegative"
        ),
        Index(
            "ix_meal_item_meal_id",
            "meal_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    meal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meals.id",
            name="fk_meal_items_meal_id_meals",
            ondelete="CASCADE"
        ),
        nullable=False
    )

    food_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False
    )

    preparation: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True
    )

    variant: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True
    )

    amount_g: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )

    carbohydrates_g: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )

    note: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    meal: Mapped["Meal"] = relationship(
        back_populates="items"
    )