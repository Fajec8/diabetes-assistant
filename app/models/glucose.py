import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GlucoseReading(Base):
    __tablename__ = "glucose_readings"

    __table_args__ = (
        CheckConstraint(
            "value_mmol_l > 0",
            name="ck_glucose_value_positive"
        ),
        Index(
            "ix_glucose_user_measured_at",
            "user_id",
            "measured_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )

    value_mmol_l: Mapped[float] = mapped_column(
        Float,
        nullable=False
    )

    source: Mapped[str] = mapped_column(
        String(20),
        default="MANUAL",
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
