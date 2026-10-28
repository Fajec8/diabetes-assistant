"""add dexcom integration

Revision ID: 9f5d2c1a7b4e
Revises: 31de8c5038e5
Create Date: 2026-10-28

"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa


revision: str = (
    "9f5d2c1a7b4e"
)

down_revision: (
    Union[
        str,
        Sequence[str],
        None,
    ]
) = "31de8c5038e5"

branch_labels: (
    Union[
        str,
        Sequence[str],
        None,
    ]
) = None

depends_on: (
    Union[
        str,
        Sequence[str],
        None,
    ]
) = None


def upgrade() -> None:
    op.create_table(
        "dexcom_connections",

        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "environment",
            sa.String(
                length=20
            ),
            nullable=False,
        ),

        sa.Column(
            "dexcom_user_id",
            sa.String(
                length=128
            ),
            nullable=True,
        ),

        sa.Column(
            "access_token",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "refresh_token",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "token_type",
            sa.String(
                length=30
            ),
            nullable=False,
        ),

        sa.Column(
            "access_expires_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=False,
        ),

        sa.Column(
            "refresh_expires_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
        ),

        sa.Column(
            "last_sync_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "last_successful_sync_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "last_sync_error",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "connected_at",
            sa.DateTime(
                timezone=True
            ),
            server_default=(
                sa.text(
                    "now()"
                )
            ),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(
                timezone=True
            ),
            server_default=(
                sa.text(
                    "now()"
                )
            ),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint(
            "id"
        ),

        sa.UniqueConstraint(
            "user_id"
        ),
    )

    op.create_index(
        op.f(
            "ix_dexcom_connections_user_id"
        ),
        "dexcom_connections",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "dexcom_glucose_readings",

        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "connection_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "record_id",
            sa.String(
                length=100
            ),
            nullable=False,
        ),

        sa.Column(
            "system_time",
            sa.DateTime(
                timezone=True
            ),
            nullable=False,
        ),

        sa.Column(
            "display_time",
            sa.String(
                length=80
            ),
            nullable=True,
        ),

        sa.Column(
            "value_mg_dl",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "value_mmol_l",
            sa.Float(),
            nullable=True,
        ),

        sa.Column(
            "status",
            sa.String(
                length=30
            ),
            nullable=True,
        ),

        sa.Column(
            "trend",
            sa.String(
                length=30
            ),
            nullable=True,
        ),

        sa.Column(
            "trend_rate_mg_dl_min",
            sa.Float(),
            nullable=True,
        ),

        sa.Column(
            "display_device",
            sa.String(
                length=30
            ),
            nullable=True,
        ),

        sa.Column(
            "transmitter_generation",
            sa.String(
                length=30
            ),
            nullable=True,
        ),

        sa.Column(
            "display_app",
            sa.String(
                length=50
            ),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(
                timezone=True
            ),
            server_default=(
                sa.text(
                    "now()"
                )
            ),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["dexcom_connections.id"],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint(
            "id"
        ),

        sa.UniqueConstraint(
            "connection_id",
            "record_id",
            name=(
                "uq_dexcom_glucose_"
                "connection_record"
            ),
        ),
    )

    op.create_index(
        (
            "ix_dexcom_glucose_"
            "user_system_time"
        ),
        "dexcom_glucose_readings",
        [
            "user_id",
            "system_time",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        (
            "ix_dexcom_glucose_"
            "user_system_time"
        ),
        table_name=(
            "dexcom_glucose_readings"
        ),
    )

    op.drop_table(
        "dexcom_glucose_readings"
    )

    op.drop_index(
        op.f(
            "ix_dexcom_connections_user_id"
        ),
        table_name=(
            "dexcom_connections"
        ),
    )

    op.drop_table(
        "dexcom_connections"
    )