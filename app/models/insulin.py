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


class InsulinDose(Base):
    __tablename__ = "insulin_doses"

    __table_args__ = (
        CheckConstraint(
            "units > 0",
            name="ck_insulin_units_positive"
        ),
        CheckConstraint(
            (
                "insulin_type IN "
                "('NOVORAPID', 'TRESIBA')"
            ),
            name="ck_insulin_type"
        ),
        CheckConstraint(
            (
                "meal_id IS NULL "
                "OR insulin_type = 'NOVORAPID'"
            ),
            name="ck_insulin_meal_only_novorapid"
        ),
        Index(
            "ix_insulin_user_administered_at",
            "user_id",
            "administered_at"
        ),
        Index(
            "ix_insulin_meal_administered_at",
            "meal_id",
            "administered_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE"
        ),
        nullable=False
    )

    meal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meals.id",
            name="fk_insulin_doses_meal_id_meals",
            ondelete="SET NULL"
        ),
        nullable=True
    )

    insulin_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )

    units: Mapped[float] = mapped_column(
        Float,
        nullable=False
    )

    administered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )

    source: Mapped[str] = mapped_column(
        String(20),
        default="MANUAL",
        nullable=False
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

    meal: Mapped["Meal | None"] = relationship(
        back_populates="insulin_doses"
    )