import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DexcomConnection(Base):
    __tablename__ = "dexcom_connections"

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
        unique=True,
        nullable=False,
        index=True,
    )

    environment: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="sandbox",
    )

    dexcom_user_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    access_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    refresh_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    token_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="Bearer",
    )

    access_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    refresh_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_sync_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DexcomGlucoseReading(Base):
    __tablename__ = "dexcom_glucose_readings"

    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "record_id",
            name="uq_dexcom_glucose_connection_record",
        ),
        Index(
            "ix_dexcom_glucose_user_system_time",
            "user_id",
            "system_time",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "dexcom_connections.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    record_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    system_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    display_time: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    value_mg_dl: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    value_mmol_l: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    trend: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    trend_rate_mg_dl_min: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    display_device: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    transmitter_generation: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    display_app: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )