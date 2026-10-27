"""add meal assessments

Revision ID: 57741d0dff62
Revises: 541e3c032cd7
Create Date: 2026-10-27 09:35:45.010950

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "57741d0dff62"
down_revision: Union[str, Sequence[str], None] = "541e3c032cd7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "meal_assessments",

        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "meal_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "reported_prebolus_minutes",
            sa.Float(),
            nullable=True,
        ),

        sa.Column(
            "prebolus_explicit_none",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),

        sa.Column(
            "insulin_feedback",
            sa.String(length=20),
            nullable=True,
        ),

        sa.Column(
            "reported_meal_type",
            sa.String(length=20),
            nullable=True,
        ),

        sa.Column(
            "timing_note",
            sa.String(length=500),
            nullable=True,
        ),

        sa.Column(
            "raw_notes",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "source",
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        sa.CheckConstraint(
            (
                "insulin_feedback IS NULL "
                "OR insulin_feedback IN "
                "('TOO_LITTLE', 'OK', 'TOO_MUCH')"
            ),
            name="ck_meal_assessment_feedback_valid",
        ),

        sa.CheckConstraint(
            (
                "reported_meal_type IS NULL "
                "OR reported_meal_type IN "
                "('BREAKFAST', 'LUNCH', 'DINNER')"
            ),
            name="ck_meal_assessment_meal_type_valid",
        ),

        sa.CheckConstraint(
            (
                "NOT ("
                "prebolus_explicit_none = TRUE "
                "AND reported_prebolus_minutes IS NOT NULL"
                ")"
            ),
            name="ck_meal_assessment_prebolus_consistent",
        ),

        sa.CheckConstraint(
            (
                "reported_prebolus_minutes IS NULL "
                "OR reported_prebolus_minutes >= 0"
            ),
            name="ck_meal_assessment_prebolus_nonnegative",
        ),

        sa.ForeignKeyConstraint(
            ["meal_id"],
            ["meals.id"],
            name="fk_meal_assessments_meal_id_meals",
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint(
            "id",
        ),

        sa.UniqueConstraint(
            "meal_id",
            name="uq_meal_assessment_meal_id",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_table(
        "meal_assessments"
    )