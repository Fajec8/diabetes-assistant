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
from app.services.outcome_summary import (
    summarize_outcomes,
)


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

CLARITY_SOURCE = "DEXCOM_CLARITY"
CLARITY_NOTE = "Imported from Dexcom Clarity CSV"

HORIZONS = [
    30,
    60,
    90,
    120,
    180,
]

TOLERANCE = timedelta(
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
                >= target - TOLERANCE,
                GlucoseReading.measured_at
                <= target + TOLERANCE,
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


def main():
    db = SessionLocal()

    try:
        items = []

        print()
        print("=" * 92)
        print(
            "REAL CLEAN OUTCOME SUMMARY "
            "+ QUALITY + CONFIDENCE"
        )
        print("=" * 92)

        for (
            index,
            (
                raw_t0,
                ranking,
            ),
        ) in enumerate(
            CANDIDATES,
            start=1,
        ):
            t0 = datetime.fromisoformat(
                raw_t0
            )

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

            valid_horizons = []

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

                if delta is not None:
                    valid_horizons.append(
                        minutes
                    )

            quality = (
                evaluate_outcome_quality(
                    outcome
                )
            )

            items.append(
                {
                    "ranking_score":
                        ranking,
                    "outcome":
                        outcome,
                    "quality":
                        quality,
                }
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
                f"{ranking}"
                f" | first action="
                f"{action_text}"
            )

            print(
                f"    quality="
                f"{quality['quality_score']}"
                f" | {quality['status']}"
                f" | confidence="
                f"{quality['confidence']}%"
                f" | "
                f"{quality['confidence_level']}"
            )

            print(
                f"    valid="
                f"{quality['available_horizons']}"
            )

            print(
                f"    baseline="
                f"{baseline}"
                f" | latest="
                f"{quality['latest_glucose']}"
                f" @ "
                f"{quality['latest_horizon_minutes']}"
                f" min"
                f" | distance from 8="
                f"{quality['distance_from_target']}"
            )

            print(
                f"    low="
                f"{quality['low_detected']}"
                f" | high="
                f"{quality['high_detected']}"
            )

        summary = (
            summarize_outcomes(
                items
            )
        )

        print()
        print("=" * 92)
        print(
            "CLEAN OUTCOME SUMMARY"
        )
        print("-" * 92)

        for minutes in HORIZONS:
            row = summary[
                f"delta_{minutes}m"
            ]

            print(
                f"{minutes:3} min"
                f" | n={row['count']}"
                f" | median={row['median']}"
                f" | weighted="
                f"{row['weighted_mean']}"
                f" | down="
                f"{row['direction']['decreased']}"
                f" stable="
                f"{row['direction']['stable']}"
                f" up="
                f"{row['direction']['increased']}"
            )

        quality_values = []

        confidence_counts = {
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "NO_DATA": 0,
        }

        high_confidence_quality = []

        for item in items:
            quality = item[
                "quality"
            ]

            score = quality[
                "quality_score"
            ]

            level = quality[
                "confidence_level"
            ]

            confidence_counts[
                level
            ] += 1

            if score is not None:
                quality_values.append(
                    score
                )

            if (
                score is not None
                and level == "HIGH"
            ):
                high_confidence_quality.append(
                    score
                )

        print()
        print("=" * 92)
        print(
            "QUALITY + CONFIDENCE SUMMARY"
        )
        print("-" * 92)

        if quality_values:
            print(
                "All evaluated:",
                len(
                    quality_values
                ),
            )

            print(
                "Average quality:",
                round(
                    sum(
                        quality_values
                    )
                    / len(
                        quality_values
                    ),
                    2,
                ),
            )

            print(
                "Best quality:",
                max(
                    quality_values
                ),
            )

            print(
                "Worst quality:",
                min(
                    quality_values
                ),
            )

        print()
        print(
            "Confidence HIGH:",
            confidence_counts[
                "HIGH"
            ],
        )

        print(
            "Confidence MEDIUM:",
            confidence_counts[
                "MEDIUM"
            ],
        )

        print(
            "Confidence LOW:",
            confidence_counts[
                "LOW"
            ],
        )

        print(
            "Confidence NO_DATA:",
            confidence_counts[
                "NO_DATA"
            ],
        )

        if high_confidence_quality:
            print()
            print(
                "HIGH-confidence "
                "average quality:",
                round(
                    sum(
                        high_confidence_quality
                    )
                    / len(
                        high_confidence_quality
                    ),
                    2,
                ),
            )

            print(
                "HIGH-confidence "
                "cases:",
                len(
                    high_confidence_quality
                ),
            )

        print()
        print(
            "Target glucose: "
            "8.0 mmol/l"
        )

        print(
            "Target range: "
            "4.0–10.0 mmol/l"
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 92)

    finally:
        db.close()


if __name__ == "__main__":
    main()