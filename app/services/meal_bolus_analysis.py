import uuid
from datetime import datetime
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.insulin import InsulinDose
from app.models.meal import Meal


def _round_optional(
    value,
    digits=1
):
    if value is None:
        return None

    return round(
        value,
        digits
    )


def _minutes_between(
    first,
    second
):
    return (
        (
            second
            - first
        ).total_seconds()
        / 60
    )


def _fraction_label(
    units,
    total_units
):
    if (
        total_units is None
        or total_units <= 0
    ):
        return None

    ratio = Fraction(
        units / total_units
    ).limit_denominator(
        12
    )

    return (
        f"{ratio.numerator}/"
        f"{ratio.denominator}"
    )


def build_meal_bolus_analysis(
    meal,
    doses,
    as_of: datetime | None = None
):
    available_doses = list(
        doses
    )

    # -----------------------------------------------------
    # Dulezite pro Situation(t0):
    #
    # Situace nesmi obsahovat davku, ktera byla
    # aplikovana az PO t0.
    #
    # Jinak by vznikl future leakage.
    # -----------------------------------------------------

    if as_of is not None:
        available_doses = [
            dose
            for dose in available_doses
            if (
                dose.administered_at
                <= as_of
            )
        ]

    ordered_doses = sorted(
        available_doses,
        key=lambda dose:
            dose.administered_at
    )

    dose_count = len(
        ordered_doses
    )

    total_units = round(
        sum(
            dose.units
            for dose
            in ordered_doses
        ),
        2
    )

    if dose_count == 0:
        return {
            "meal_id":
                meal.id,

            "eaten_at":
                meal.eaten_at,

            "carbohydrates_g":
                meal.carbohydrates_g,

            "strategy":
                "NO_LINKED_BOLUS",

            "dose_count":
                0,

            "total_bolus_units":
                0.0,

            "prebolus_minutes":
                None,

            "first_dose_relative_minutes":
                None,

            "split":
                False,

            "split_ratio":
                None,

            "doses":
                []
        }

    first_dose = (
        ordered_doses[
            0
        ]
    )

    first_relative_minutes = (
        _minutes_between(
            meal.eaten_at,
            first_dose.administered_at
        )
    )

    prebolus_minutes = 0.0

    if (
        first_relative_minutes
        < 0
    ):
        prebolus_minutes = abs(
            first_relative_minutes
        )

    analyzed_doses = []

    ratio_parts = []

    for index, dose in enumerate(
        ordered_doses,
        start=1
    ):
        relative_minutes = (
            _minutes_between(
                meal.eaten_at,
                dose.administered_at
            )
        )

        percentage = None

        if total_units > 0:
            percentage = (
                dose.units
                / total_units
                * 100
            )

        fraction_label = (
            _fraction_label(
                units=dose.units,
                total_units=total_units
            )
        )

        ratio_parts.append(
            fraction_label
        )

        analyzed_doses.append({
            "part":
                index,

            "dose_id":
                dose.id,

            "units":
                dose.units,

            "administered_at":
                dose.administered_at,

            "relative_to_meal_minutes":
                _round_optional(
                    relative_minutes
                ),

            "percentage_of_total":
                _round_optional(
                    percentage
                ),

            "fraction_of_total":
                fraction_label
        })

    is_split = (
        dose_count > 1
    )

    if is_split:
        strategy = "SPLIT"

        split_ratio = (
            " + ".join(
                ratio_parts
            )
        )

    else:
        strategy = "SINGLE"

        split_ratio = None

    return {
        "meal_id":
            meal.id,

        "eaten_at":
            meal.eaten_at,

        "carbohydrates_g":
            meal.carbohydrates_g,

        "strategy":
            strategy,

        "dose_count":
            dose_count,

        "total_bolus_units":
            total_units,

        "prebolus_minutes":
            _round_optional(
                prebolus_minutes
            ),

        "first_dose_relative_minutes":
            _round_optional(
                first_relative_minutes
            ),

        "split":
            is_split,

        "split_ratio":
            split_ratio,

        "doses":
            analyzed_doses
    }


def analyze_meal_bolus(
    db: Session,
    meal_id: uuid.UUID,
    as_of: datetime | None = None
):
    meal = db.get(
        Meal,
        meal_id
    )

    if meal is None:
        return None

    statement = (
        select(
            InsulinDose
        )
        .where(
            InsulinDose.meal_id
            == meal_id,

            InsulinDose.insulin_type
            == "NOVORAPID"
        )
    )

    if as_of is not None:
        statement = (
            statement.where(
                InsulinDose.administered_at
                <= as_of
            )
        )

    statement = (
        statement.order_by(
            InsulinDose.administered_at
        )
    )

    doses = list(
        db.scalars(
            statement
        ).all()
    )

    return (
        build_meal_bolus_analysis(
            meal=meal,
            doses=doses,
            as_of=as_of
        )
    )