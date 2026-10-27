from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models.activity import Activity
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.meal import Meal
from app.services.outcome_quality import (
    evaluate_outcome_quality,
)


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

CLARITY_SOURCE = "DEXCOM_CLARITY"
CLARITY_NOTE = "Imported from Dexcom Clarity CSV"

NOVORAPID = "NOVORAPID"

HORIZONS = [
    30,
    60,
    90,
    120,
    180,
]

GLUCOSE_TOLERANCE = timedelta(
    minutes=10
)

CANDIDATES = [
    (
        "2026-08-30T15:30:01+02:00",
        77.0,
    ),
    (
        "2026-10-06T14:15:09+02:00",
        76.8,
    ),
    (
        "2026-10-16T14:00:04+02:00",
        76.5,
    ),
    (
        "2026-10-15T13:30:05+02:00",
        75.3,
    ),
    (
        "2026-08-17T13:30:55+02:00",
        75.1,
    ),
    (
        "2026-08-02T15:15:02+02:00",
        70.9,
    ),
    (
        "2026-08-04T12:45:08+02:00",
        70.9,
    ),
    (
        "2026-10-05T13:00:05+02:00",
        70.6,
    ),
    (
        "2026-10-07T12:15:12+02:00",
        70.6,
    ),
    (
        "2026-10-10T13:15:05+02:00",
        70.3,
    ),
]


def nearest_glucose(
    db,
    target,
):
    rows = (
        db.execute(
            select(
                GlucoseReading
            ).where(
                GlucoseReading.user_id
                == USER_ID,
                GlucoseReading.source
                == CLARITY_SOURCE,
                GlucoseReading.measured_at
                >= target - GLUCOSE_TOLERANCE,
                GlucoseReading.measured_at
                <= target + GLUCOSE_TOLERANCE,
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return None

    row = min(
        rows,
        key=lambda item: abs(
            (
                item.measured_at
                - target
            ).total_seconds()
        ),
    )

    return float(
        row.value_mmol_l
    )


def get_last_meal(
    db,
    t0,
):
    return (
        db.execute(
            select(
                Meal
            )
            .where(
                Meal.user_id
                == USER_ID,
                Meal.note
                == CLARITY_NOTE,
                Meal.eaten_at
                <= t0,
            )
            .order_by(
                Meal.eaten_at.desc()
            )
            .limit(1)
        )
        .scalars()
        .first()
    )


def get_recent_novorapid(
    db,
    t0,
    hours=6,
):
    start = (
        t0
        - timedelta(
            hours=hours
        )
    )

    return (
        db.execute(
            select(
                InsulinDose
            )
            .where(
                InsulinDose.user_id
                == USER_ID,
                InsulinDose.source
                == CLARITY_SOURCE,
                InsulinDose.insulin_type
                == NOVORAPID,
                InsulinDose.administered_at
                >= start,
                InsulinDose.administered_at
                <= t0,
            )
            .order_by(
                InsulinDose.administered_at
            )
        )
        .scalars()
        .all()
    )


def sum_units_since(
    doses,
    t0,
    hours,
):
    start = (
        t0
        - timedelta(
            hours=hours
        )
    )

    return round(
        sum(
            float(
                dose.units
            )
            for dose in doses
            if (
                dose.administered_at
                >= start
            )
        ),
        2,
    )


def estimate_active_novorapid(
    doses,
    t0,
):
    total = 0.0

    for dose in doses:
        age_minutes = (
            t0
            - dose.administered_at
        ).total_seconds() / 60.0

        if (
            age_minutes < 0
            or age_minutes >= 240
        ):
            continue

        remaining_fraction = (
            1.0
            - age_minutes / 240.0
        )

        total += (
            float(
                dose.units
            )
            * remaining_fraction
        )

    return round(
        total,
        2,
    )


def first_future_action_minutes(
    db,
    t0,
):
    end = (
        t0
        + timedelta(
            minutes=180
        )
    )

    times = []

    insulin = (
        db.execute(
            select(
                InsulinDose
            ).where(
                InsulinDose.user_id
                == USER_ID,
                InsulinDose.source
                == CLARITY_SOURCE,
                InsulinDose.administered_at
                > t0,
                InsulinDose.administered_at
                <= end,
            )
        )
        .scalars()
        .all()
    )

    for item in insulin:
        times.append(
            item.administered_at
        )

    meals = (
        db.execute(
            select(
                Meal
            ).where(
                Meal.user_id
                == USER_ID,
                Meal.note
                == CLARITY_NOTE,
                Meal.eaten_at
                > t0,
                Meal.eaten_at
                <= end,
            )
        )
        .scalars()
        .all()
    )

    for item in meals:
        times.append(
            item.eaten_at
        )

    activities = (
        db.execute(
            select(
                Activity
            ).where(
                Activity.user_id
                == USER_ID,
                Activity.note
                == CLARITY_NOTE,
                Activity.started_at
                > t0,
                Activity.started_at
                <= end,
            )
        )
        .scalars()
        .all()
    )

    for item in activities:
        times.append(
            item.started_at
        )

    if not times:
        return None

    first = min(
        times
    )

    return (
        first - t0
    ).total_seconds() / 60.0


def build_clean_outcome(
    db,
    t0,
):
    baseline = nearest_glucose(
        db,
        t0,
    )

    first_action = (
        first_future_action_minutes(
            db,
            t0,
        )
    )

    outcome = {
        "baseline_glucose":
            baseline
    }

    for minutes in HORIZONS:
        contaminated = (
            first_action is not None
            and first_action <= minutes
        )

        if contaminated:
            value = None
            delta = None

        else:
            value = nearest_glucose(
                db,
                t0
                + timedelta(
                    minutes=minutes
                ),
            )

            if (
                baseline is not None
                and value is not None
            ):
                delta = round(
                    value - baseline,
                    2,
                )
            else:
                delta = None

        outcome[
            f"glucose_{minutes}m"
        ] = value

        outcome[
            f"delta_{minutes}m"
        ] = delta

    return (
        outcome,
        first_action,
    )


def main():
    db = SessionLocal()

    try:
        print()
        print("=" * 100)
        print(
            "REAL DOSE + OUTCOME PROBE"
        )
        print("=" * 100)

        usable = []

        for (
            index,
            (
                raw_t0,
                similarity_rank,
            ),
        ) in enumerate(
            CANDIDATES,
            start=1,
        ):
            t0 = datetime.fromisoformat(
                raw_t0
            )

            meal = get_last_meal(
                db,
                t0,
            )

            doses = get_recent_novorapid(
                db,
                t0,
            )

            last_dose = (
                doses[-1]
                if doses
                else None
            )

            if last_dose is not None:
                last_units = float(
                    last_dose.units
                )

                minutes_since_bolus = round(
                    (
                        t0
                        - last_dose.administered_at
                    ).total_seconds()
                    / 60.0
                )

            else:
                last_units = None
                minutes_since_bolus = None

            units_2h = sum_units_since(
                doses,
                t0,
                2,
            )

            units_4h = sum_units_since(
                doses,
                t0,
                4,
            )

            units_6h = sum_units_since(
                doses,
                t0,
                6,
            )

            active_units = (
                estimate_active_novorapid(
                    doses,
                    t0,
                )
            )

            if meal is not None:
                meal_carbs = float(
                    meal.carbohydrates_g
                )

                meal_minutes = round(
                    (
                        t0
                        - meal.eaten_at
                    ).total_seconds()
                    / 60.0
                )

                meal_description = (
                    meal.description
                    or "-"
                )

            else:
                meal_carbs = None
                meal_minutes = None
                meal_description = "-"

            (
                outcome,
                first_action,
            ) = build_clean_outcome(
                db,
                t0,
            )

            quality = (
                evaluate_outcome_quality(
                    outcome
                )
            )

            if first_action is None:
                action_text = "none"
            else:
                action_text = (
                    f"+{round(first_action)} min"
                )

            print()
            print(
                f"{index:2}. "
                f"{raw_t0}"
            )

            print(
                f"    similarity rank="
                f"{similarity_rank}"
            )

            print(
                f"    meal="
                f"{meal_carbs} g"
                f" | {meal_minutes} min ago"
                f" | {meal_description}"
            )

            print(
                f"    last NovoRapid="
                f"{last_units} U"
                f" | {minutes_since_bolus} min ago"
            )

            print(
                f"    NovoRapid total:"
                f" 2h={units_2h} U"
                f" | 4h={units_4h} U"
                f" | 6h={units_6h} U"
            )

            print(
                f"    estimated active NovoRapid="
                f"{active_units} U"
                f" (linear 4h research estimate)"
            )

            print(
                f"    quality="
                f"{quality['quality_score']}"
                f" | {quality['status']}"
                f" | confidence="
                f"{quality['confidence']}%"
                f" | {quality['confidence_level']}"
            )

            print(
                f"    latest clean glucose="
                f"{quality['latest_glucose']}"
                f" @ "
                f"{quality['latest_horizon_minutes']} min"
                f" | first future action="
                f"{action_text}"
            )

            if (
                quality["quality_score"]
                is not None
                and quality["confidence_level"]
                in (
                    "HIGH",
                    "MEDIUM",
                )
            ):
                usable.append(
                    {
                        "index":
                            index,

                        "similarity_rank":
                            similarity_rank,

                        "last_units":
                            last_units,

                        "minutes_since_bolus":
                            minutes_since_bolus,

                        "active_units":
                            active_units,

                        "meal_carbs":
                            meal_carbs,

                        "quality":
                            quality[
                                "quality_score"
                            ],

                        "confidence":
                            quality[
                                "confidence"
                            ],
                    }
                )

        print()
        print("=" * 100)
        print(
            "USABLE EVIDENCE "
            "(MEDIUM/HIGH CONFIDENCE)"
        )
        print("-" * 100)

        for item in usable:
            print(
                f"#{item['index']:2}"
                f" | similarity="
                f"{item['similarity_rank']}"
                f" | bolus="
                f"{item['last_units']} U"
                f" ({item['minutes_since_bolus']} min ago)"
                f" | active≈"
                f"{item['active_units']} U"
                f" | carbs="
                f"{item['meal_carbs']} g"
                f" | quality="
                f"{item['quality']}"
                f" | confidence="
                f"{item['confidence']}%"
            )

        print()
        print(
            "Usable cases:",
            len(
                usable
            ),
        )

        print(
            "Excluded LOW-confidence cases:",
            len(
                CANDIDATES
            )
            - len(
                usable
            ),
        )

        print()
        print(
            "NOTE: This is research/shadow analysis only."
        )

        print(
            "No insulin dose is being recommended."
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 100)

    finally:
        db.close()


if __name__ == "__main__":
    main()