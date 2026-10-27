from __future__ import annotations

import uuid
from datetime import timedelta
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import (
    func,
    select,
)

from app.database import SessionLocal

from app.models.activity import Activity
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.meal import Meal
from app.models.user import User

from app.services.predose_shadow_engine import (
    estimate_unlinked_shadow_action,
)

from scripts.real_predose_backtest import (
    CLARITY_NOTE,
    CLARITY_SOURCE,
    build_predose_situation,
    prepare_real_cache,
)


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

NOVORAPID = "NOVORAPID"
TRESIBA = "TRESIBA"

REPLAY_DAYS = 30
HISTORY_DAYS = 90

MAX_CASES = 15

# Pro první V1 replay chceme opravdu
# correction-like situace bez blízkého jídla.
NO_MEAL_BEFORE_MINUTES = 120
NO_MEAL_AFTER_MINUTES = 30

RECENT_NOVORAPID_HOURS = 6
ACTIVITY_INPUT_HOURS = 72


def derive_trend(
    delta_15m,
):
    if delta_15m is None:
        return None

    delta_15m = float(
        delta_15m
    )

    if delta_15m >= 0.5:
        return "RISING"

    if delta_15m <= -0.5:
        return "FALLING"

    return "STABLE"


def has_nearby_meal(
    meals,
    decision_t0,
):
    window_start = (
        decision_t0
        - timedelta(
            minutes=
                NO_MEAL_BEFORE_MINUTES
        )
    )

    window_end = (
        decision_t0
        + timedelta(
            minutes=
                NO_MEAL_AFTER_MINUTES
        )
    )

    return any(
        meal.eaten_at
        >= window_start
        and meal.eaten_at
        <= window_end

        for meal
        in meals
    )


def build_replay_input_snapshot(
    db,
    target_dose,
    decision_t0,
    target_situation,
):
    recent_start = (
        decision_t0
        - timedelta(
            hours=
                RECENT_NOVORAPID_HOURS
        )
    )

    previous_novorapid = (
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
                >= recent_start,

                InsulinDose.administered_at
                <= decision_t0,
            )
            .order_by(
                InsulinDose.administered_at
            )
        )
        .scalars()
        .all()
    )

    # Dávka, kterou replayujeme,
    # nesmí být ve vstupu.
    assert all(
        dose.id
        != target_dose.id

        for dose
        in previous_novorapid
    )

    recent_novorapid = [
        {
            "units":
                float(
                    dose.units
                ),

            "administered_at":
                dose.administered_at
                .isoformat(),
        }

        for dose
        in previous_novorapid
    ]

    last_tresiba = db.scalar(
        select(
            InsulinDose
        )
        .where(
            InsulinDose.user_id
            == USER_ID,

            InsulinDose.source
            == CLARITY_SOURCE,

            InsulinDose.insulin_type
            == TRESIBA,

            InsulinDose.administered_at
            <= decision_t0,
        )
        .order_by(
            InsulinDose.administered_at.desc()
        )
        .limit(1)
    )

    if last_tresiba is None:
        tresiba = None

    else:
        tresiba = {
            "units":
                float(
                    last_tresiba.units
                ),

            "administered_at":
                last_tresiba
                .administered_at
                .isoformat(),
        }

    activity_start = (
        decision_t0
        - timedelta(
            hours=
                ACTIVITY_INPUT_HOURS
        )
    )

    activity_rows = (
        db.execute(
            select(
                Activity
            )
            .where(
                Activity.user_id
                == USER_ID,

                Activity.note
                == CLARITY_NOTE,

                Activity.started_at
                >= activity_start,

                Activity.ended_at
                <= decision_t0,
            )
            .order_by(
                Activity.started_at
            )
        )
        .scalars()
        .all()
    )

    activities = []

    for activity in activity_rows:
        duration_minutes = round(
            (
                activity.ended_at
                - activity.started_at
            ).total_seconds()
            / 60.0
        )

        activities.append(
            {
                "activity_type":
                    activity.activity_type,

                "intensity":
                    activity.intensity,

                "duration_minutes":
                    duration_minutes,

                "started_at":
                    activity.started_at
                    .isoformat(),

                "ended_at":
                    activity.ended_at
                    .isoformat(),
            }
        )

    glucose = (
        target_situation[
            "glucose"
        ]
    )

    snapshot = {
        "schema_version":
            "1.0",

        "decision_at":
            decision_t0.isoformat(),

        "glucose": {
            "current":
                glucose[
                    "current"
                ],

            "delta_15m":
                glucose[
                    "delta_15m"
                ],

            "delta_30m":
                glucose[
                    "delta_30m"
                ],

            "delta_60m":
                glucose[
                    "delta_60m"
                ],

            "trend":
                derive_trend(
                    glucose[
                        "delta_15m"
                    ]
                ),
        },

        # Shadow V1 nyní testujeme
        # pouze jako situaci bez
        # plánovaného jídla.
        "planned_meal":
            None,

        "recent_novorapid":
            recent_novorapid,

        "tresiba":
            tresiba,

        "activities":
            activities,

        "note":
            (
                "Historical replay - "
                "hidden actual dose"
            ),
    }

    return snapshot


def main():
    db = SessionLocal()

    try:
        user = db.get(
            User,
            USER_ID,
        )

        if user is None:
            raise RuntimeError(
                "User not found"
            )

        timezone = ZoneInfo(
            user.timezone
        )

        latest_real_time = db.scalar(
            select(
                func.max(
                    GlucoseReading.measured_at
                )
            )
            .where(
                GlucoseReading.user_id
                == USER_ID,

                GlucoseReading.source
                == CLARITY_SOURCE,
            )
        )

        if latest_real_time is None:
            raise RuntimeError(
                "No Clarity glucose found"
            )

        replay_end = latest_real_time

        replay_start = (
            replay_end
            - timedelta(
                days=
                    REPLAY_DAYS
            )
        )

        preload_start = (
            replay_start
            - timedelta(
                days=
                    HISTORY_DAYS,
                hours=2,
            )
        )

        cache = prepare_real_cache(
            db,
            latest_real_time,
            preload_start,
        )

        meal_by_id = {
            meal.id:
                meal

            for meal
            in cache.meals
        }

        real_meals = (
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
                    >= (
                        replay_start
                        - timedelta(
                            minutes=
                                NO_MEAL_BEFORE_MINUTES
                        )
                    ),

                    Meal.eaten_at
                    <= (
                        replay_end
                        + timedelta(
                            minutes=
                                NO_MEAL_AFTER_MINUTES
                        )
                    ),
                )
                .order_by(
                    Meal.eaten_at
                )
            )
            .scalars()
            .all()
        )

        target_doses = (
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

                    InsulinDose.meal_id
                    .is_(None),

                    InsulinDose.administered_at
                    >= replay_start,

                    InsulinDose.administered_at
                    <= replay_end,
                )
                .order_by(
                    InsulinDose
                    .administered_at
                    .desc()
                )
            )
            .scalars()
            .all()
        )

        all_unlinked_count = len(
            target_doses
        )

        strict_targets = []

        for dose in target_doses:
            decision_t0 = (
                dose.administered_at
                - timedelta(
                    seconds=1
                )
            )

            if has_nearby_meal(
                real_meals,
                decision_t0,
            ):
                continue

            strict_targets.append(
                dose
            )

        selected_targets = (
            strict_targets[
                :MAX_CASES
            ]
        )

        print()
        print("=" * 110)
        print(
            "SHADOW V1 HISTORICAL REPLAY"
        )
        print("=" * 110)

        print(
            "Replay window:",
            replay_start
            .astimezone(
                timezone
            )
            .isoformat(),
            "->",
            replay_end
            .astimezone(
                timezone
            )
            .isoformat(),
        )

        print(
            "All UNLINKED targets:",
            all_unlinked_count,
        )

        print(
            "Strict no-meal targets:",
            len(
                strict_targets
            ),
        )

        print(
            "Cases selected:",
            len(
                selected_targets
            ),
        )

        print(
            "No-meal filter:",
            f"-{NO_MEAL_BEFORE_MINUTES} min",
            f"/ +{NO_MEAL_AFTER_MINUTES} min",
        )

        print()

        results = []

        for index, dose in enumerate(
            selected_targets,
            start=1,
        ):
            (
                decision_t0,
                target_situation,
            ) = build_predose_situation(
                cache=cache,
                dose=dose,
                timezone=timezone,
                meal_by_id=meal_by_id,
            )

            if (
                target_situation[
                    "glucose"
                ][
                    "current"
                ]
                is None
            ):
                print(
                    f"{index:2}.",
                    dose.administered_at
                    .astimezone(
                        timezone
                    )
                    .isoformat(),
                    "| SKIP - no glucose",
                )

                continue

            snapshot = (
                build_replay_input_snapshot(
                    db=db,
                    target_dose=dose,
                    decision_t0=
                        decision_t0,
                    target_situation=
                        target_situation,
                )
            )

            result = (
                estimate_unlinked_shadow_action(
                    db=db,
                    user_id=USER_ID,
                    input_snapshot=
                        snapshot,
                )
            )

            actual_units = float(
                dose.units
            )

            estimated_units = (
                result[
                    "estimated_units"
                ]
            )

            if (
                estimated_units
                is None
            ):
                absolute_error = None

            else:
                absolute_error = round(
                    abs(
                        float(
                            estimated_units
                        )
                        - actual_units
                    ),
                    2,
                )

            row = {
                "decision_at":
                    decision_t0,

                "actual_units":
                    actual_units,

                "estimated_units":
                    estimated_units,

                "absolute_error":
                    absolute_error,

                "status":
                    result[
                        "status"
                    ],

                "support_count":
                    result[
                        "support_count"
                    ],

                "strongest_evidence":
                    result[
                        "strongest_evidence"
                    ],

                "average_evidence":
                    result[
                        "average_evidence"
                    ],

                "abstain_reason":
                    result[
                        "abstain_reason"
                    ],
            }

            results.append(
                row
            )

            print(
                f"{index:2}.",
                decision_t0
                .astimezone(
                    timezone
                )
                .isoformat(),
                "| actual=",
                actual_units,
                "U",
                "| status=",
                result[
                    "status"
                ],
                "| estimate=",
                (
                    estimated_units
                    if estimated_units
                    is not None
                    else "-"
                ),
                "| support=",
                result[
                    "support_count"
                ],
                "| strongest=",
                result[
                    "strongest_evidence"
                ],
                "| error=",
                (
                    absolute_error
                    if absolute_error
                    is not None
                    else "-"
                ),
            )

        estimated = [
            row
            for row
            in results
            if (
                row[
                    "estimated_units"
                ]
                is not None
            )
        ]

        abstained = [
            row
            for row
            in results
            if (
                row[
                    "estimated_units"
                ]
                is None
            )
        ]

        print()
        print("=" * 110)
        print(
            "REPLAY SUMMARY"
        )
        print("-" * 110)

        print(
            "Processed:",
            len(
                results
            ),
        )

        print(
            "Estimated:",
            len(
                estimated
            ),
        )

        print(
            "Abstained:",
            len(
                abstained
            ),
        )

        if results:
            print(
                "Estimate rate:",
                round(
                    len(
                        estimated
                    )
                    / len(
                        results
                    )
                    * 100.0,
                    1,
                ),
                "%",
            )

        if estimated:
            errors = [
                row[
                    "absolute_error"
                ]
                for row
                in estimated
            ]

            mae = round(
                sum(
                    errors
                )
                / len(
                    errors
                ),
                2,
            )

            median_error = round(
                median(
                    errors
                ),
                2,
            )

            within_half = sum(
                error <= 0.5
                for error
                in errors
            )

            within_one = sum(
                error <= 1.0
                for error
                in errors
            )

            print()
            print(
                "MAE:",
                mae,
                "U",
            )

            print(
                "Median absolute error:",
                median_error,
                "U",
            )

            print(
                "Within +/-0.5 U:",
                within_half,
                "/",
                len(
                    errors
                ),
                "=",
                round(
                    within_half
                    / len(
                        errors
                    )
                    * 100.0,
                    1,
                ),
                "%",
            )

            print(
                "Within +/-1.0 U:",
                within_one,
                "/",
                len(
                    errors
                ),
                "=",
                round(
                    within_one
                    / len(
                        errors
                    )
                    * 100.0,
                    1,
                ),
                "%",
            )

        if abstained:
            print()
            print(
                "ABSTAIN reasons:"
            )

            reasons = {}

            for row in abstained:
                reason = (
                    row[
                        "abstain_reason"
                    ]
                    or "UNKNOWN"
                )

                reasons[
                    reason
                ] = (
                    reasons.get(
                        reason,
                        0,
                    )
                    + 1
                )

            for (
                reason,
                count,
            ) in sorted(
                reasons.items()
            ):
                print(
                    "-",
                    reason,
                    ":",
                    count,
                )

        print()
        print(
            "IMPORTANT:"
        )

        print(
            "- The historical target dose "
            "was hidden from the Shadow input."
        )

        print(
            "- Only information available "
            "before decision_t0 was used."
        )

        print(
            "- planned_meal was deliberately "
            "NULL in this replay."
        )

        print(
            "- This tests the NEW manual-input "
            "Shadow V1 path, not the old "
            "retrospective builder path."
        )

        print()
        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 110)

    finally:
        db.close()


if __name__ == "__main__":
    main()