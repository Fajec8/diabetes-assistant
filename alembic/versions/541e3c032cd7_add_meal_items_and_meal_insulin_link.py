"""add meal items and meal insulin link

Revision ID: 541e3c032cd7
Revises: 2a191e90e307
Create Date: 2026-10-18 22:06:39.547642

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "541e3c032cd7"

down_revision: Union[
    str,
    Sequence[str],
    None
] = "2a191e90e307"

branch_labels: Union[
    str,
    Sequence[str],
    None
] = None

depends_on: Union[
    str,
    Sequence[str],
    None
] = None


def upgrade() -> None:
    # -----------------------------------------------------
    # MEAL ITEMS
    # -----------------------------------------------------

    op.create_table(
        "meal_items",

        sa.Column(
            "id",
            sa.UUID(),
            nullable=False
        ),

        sa.Column(
            "meal_id",
            sa.UUID(),
            nullable=False
        ),

        sa.Column(
            "food_name",
            sa.String(
                length=120
            ),
            nullable=False
        ),

        sa.Column(
            "preparation",
            sa.String(
                length=80
            ),
            nullable=True
        ),

        sa.Column(
            "variant",
            sa.String(
                length=120
            ),
            nullable=True
        ),

        sa.Column(
            "amount_g",
            sa.Float(),
            nullable=True
        ),

        sa.Column(
            "carbohydrates_g",
            sa.Float(),
            nullable=True
        ),

        sa.Column(
            "note",
            sa.String(
                length=500
            ),
            nullable=True
        ),

        sa.Column(
            "created_at",
            sa.DateTime(
                timezone=True
            ),
            server_default=sa.text(
                "now()"
            ),
            nullable=False
        ),

        sa.CheckConstraint(
            (
                "amount_g IS NULL "
                "OR amount_g > 0"
            ),
            name=(
                "ck_meal_item_"
                "amount_positive"
            )
        ),

        sa.CheckConstraint(
            (
                "carbohydrates_g IS NULL "
                "OR carbohydrates_g >= 0"
            ),
            name=(
                "ck_meal_item_"
                "carbohydrates_nonnegative"
            )
        ),

        sa.ForeignKeyConstraint(
            [
                "meal_id"
            ],
            [
                "meals.id"
            ],
            name=(
                "fk_meal_items_"
                "meal_id_meals"
            ),
            ondelete="CASCADE"
        ),

        sa.PrimaryKeyConstraint(
            "id"
        )
    )

    op.create_index(
        "ix_meal_item_meal_id",
        "meal_items",
        [
            "meal_id"
        ],
        unique=False
    )

    # -----------------------------------------------------
    # INSULIN -> MEAL LINK
    # -----------------------------------------------------

    op.add_column(
        "insulin_doses",
        sa.Column(
            "meal_id",
            sa.UUID(),
            nullable=True
        )
    )

    op.create_index(
        "ix_insulin_meal_administered_at",
        "insulin_doses",
        [
            "meal_id",
            "administered_at"
        ],
        unique=False
    )

    op.create_foreign_key(
        "fk_insulin_doses_meal_id_meals",
        "insulin_doses",
        "meals",
        [
            "meal_id"
        ],
        [
            "id"
        ],
        ondelete="SET NULL"
    )

    # -----------------------------------------------------
    # Pouze NOVORAPID smi byt navazan na jidlo.
    #
    # TRESIBA nebo jina davka musi mit meal_id NULL.
    # -----------------------------------------------------

    op.create_check_constraint(
        "ck_insulin_meal_only_novorapid",
        "insulin_doses",
        (
            "meal_id IS NULL "
            "OR insulin_type = 'NOVORAPID'"
        )
    )


def downgrade() -> None:
    # -----------------------------------------------------
    # INSULIN -> MEAL LINK
    # -----------------------------------------------------

    op.drop_constraint(
        "ck_insulin_meal_only_novorapid",
        "insulin_doses",
        type_="check"
    )

    op.drop_constraint(
        "fk_insulin_doses_meal_id_meals",
        "insulin_doses",
        type_="foreignkey"
    )

    op.drop_index(
        "ix_insulin_meal_administered_at",
        table_name="insulin_doses"
    )

    op.drop_column(
        "insulin_doses",
        "meal_id"
    )

    # -----------------------------------------------------
    # MEAL ITEMS
    # -----------------------------------------------------

    op.drop_index(
        "ix_meal_item_meal_id",
        table_name="meal_items"
    )

    op.drop_table(
        "meal_items"
    )