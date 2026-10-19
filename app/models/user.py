import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    display_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    timezone: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Europe/Prague"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    settings: Mapped["UserSettings"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True
    )

    glucose_unit: Mapped[str] = mapped_column(
        String(20),
        default="MMOL_L",
        nullable=False
    )

    carb_unit: Mapped[str] = mapped_column(
        String(20),
        default="GRAMS",
        nullable=False
    )

    grams_per_vj: Mapped[float] = mapped_column(
        Float,
        default=10.0,
        nullable=False
    )

    bolus_insulin: Mapped[str] = mapped_column(
        String(50),
        default="NOVORAPID",
        nullable=False
    )

    basal_insulin: Mapped[str] = mapped_column(
        String(50),
        default="TRESIBA",
        nullable=False
    )

    glucose_source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )

    user: Mapped["User"] = relationship(
        back_populates="settings"
    )
