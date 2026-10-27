from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActionPlan(Base):
    __tablename__ = "action_plans"

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "source",
            name="uq_action_plan_session_source",
        ),
        CheckConstraint(
            (
                "source IN ("
                "'USER', "
                "'SYSTEM_SHADOW'"
                ")"
            ),
            name="ck_action_plan_source",
        ),
        CheckConstraint(
            (
                "status IN ("
                "'PLAN', "
                "'ABSTAIN'"
                ")"
            ),
            name="ck_action_plan_status",
        ),
        CheckConstraint(
            (
                "strategy IS NULL "
                "OR strategy IN ("
                "'NONE', "
                "'SINGLE', "
                "'SPLIT'"
                ")"
            ),
            name="ck_action_plan_strategy",
        ),
        CheckConstraint(
            (
                "total_novorapid_units IS NULL "
                "OR total_novorapid_units >= 0"
            ),
            name="ck_action_plan_total_units",
        ),
        CheckConstraint(
            (
                "prebolus_minutes IS NULL "
                "OR prebolus_minutes >= 0"
            ),
            name="ck_action_plan_prebolus",
        ),
        CheckConstraint(
            (
                "first_dose_units IS NULL "
                "OR first_dose_units >= 0"
            ),
            name="ck_action_plan_first_units",
        ),
        CheckConstraint(
            (
                "second_dose_units IS NULL "
                "OR second_dose_units >= 0"
            ),
            name="ck_action_plan_second_units",
        ),
        CheckConstraint(
            (
                "second_dose_delay_minutes IS NULL "
                "OR second_dose_delay_minutes >= 0"
            ),
            name="ck_action_plan_second_delay",
        ),
        CheckConstraint(
            (
                "("
                "status = 'PLAN' "
                "AND total_novorapid_units IS NOT NULL "
                "AND strategy IS NOT NULL"
                ") "
                "OR "
                "("
                "status = 'ABSTAIN' "
                "AND total_novorapid_units IS NULL "
                "AND strategy IS NULL"
                ")"
            ),
            name="ck_action_plan_status_content",
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

    # USER = tvoje vlastní vyhodnocení.
    # SYSTEM_SHADOW = skrytý plán systému.
    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    # PLAN nebo ABSTAIN.
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    # NONE / SINGLE / SPLIT
    strategy: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # Celková plánovaná dávka NovoRapidu.
    total_novorapid_units: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    # Kolik minut před jídlem.
    # Pro korekci bez jídla může být NULL.
    prebolus_minutes: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    # První část dávky.
    first_dose_units: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    # Druhá část dávky při SPLIT.
    second_dose_units: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    # Za kolik minut po první dávce
    # má přijít druhá část.
    second_dose_delay_minutes: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    # -------------------------------------------------
    # SYSTEM_SHADOW metadata
    # -------------------------------------------------

    model_version: Mapped[
        str | None
    ] = mapped_column(
        String(50),
        nullable=True,
    )

    confidence_score: Mapped[
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

    support_count: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    strongest_evidence: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    average_evidence: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    evidence_snapshot: Mapped[
        dict | None
    ] = mapped_column(
        JSON,
        nullable=True,
    )

    abstain_reason: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    # U systémového plánu zůstává NULL,
    # dokud nemá být odhalen.
    revealed_at: Mapped[
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