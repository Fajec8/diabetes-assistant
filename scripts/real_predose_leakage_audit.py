from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
)
from zoneinfo import ZoneInfo

from sqlalchemy import (
    func,
    select,
)

from app.database import SessionLocal
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.user import User

from scripts.real_predose_backtest import (
    CLARITY_SOURCE,
    USER_ID,
    build_predose_situation,
    prepare_real_cache,
)


NOVORAPID = "NOVORAPID"

AUDIT_DAYS = 90
SAFETY_HOURS = 6

FLOAT_TOLERANCE = 0.01
MAX_FAILURES_TO_PRINT = 30


def same_float(
    actual,
    expected,
) -> bool:
    if (
        actual is None
        and expected is None
    ):
        return True

    if (
        actual is None
        or expected is None
    ):
        return False

    return (
        abs(
            float(actual)
            - float(expected)
        )
        <= FLOAT_TOLERANCE
    )


def add_check(
    stats,
    failures,
    case_label,
    check_name,
    passed,
    actual=None,
    expected=None,
):
    stats["checks"] += 1

    if passed:
        stats["passed"] += 1
        return

    stats["failed"] += 1

    failures.append(
        {
            "case":
                case_label,

            "check":
                check_name,

            "actual":
                actual,

            "expected":
                expected,
        }
    )


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
            ).where(
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

        audit_end = (
            latest_real_time
            - timedelta(
                hours=SAFETY_HOURS
            )
        )

        audit_start = (
            audit_end
            - timedelta(
                days=AUDIT_DAYS
            )
        )

        preload_start = (
            audit_start
            - timedelta(
                hours=2
            )
        )

        cache = prepare_real_cache(
            db,
            latest_real_time,
            preload_start,
        )

        meal_by_id = {
            meal.id: meal
            for meal
            in cache.meals
        }

        doses = (
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
                    >= audit_start,

                    InsulinDose.administered_at
                    <= audit_end,
                )
                .order_by(
                    InsulinDose.administered_at
                )
            )
            .scalars()
            .all()
        )

        unlinked_doses = [
            dose
            for dose in doses
            if dose.meal_id is None
        ]

        linked_count = (
            len(doses)
            - len(unlinked_doses)
        )

        stats = {
            "cases": 0,
            "checks": 0,
            "passed": 0,
            "failed": 0,
        }

        failures = []

        print()
        print("=" * 100)
        print(
            "SHADOW V1 PRE-DOSE LEAKAGE AUDIT"
        )
        print("=" * 100)

        print(
            "Audit window:",
            audit_start
            .astimezone(
                timezone
            )
            .isoformat(),
            "->",
            audit_end
            .astimezone(
                timezone
            )
            .isoformat(),
        )

        print(
            "All real NovoRapid doses:",
            len(doses),
        )

        print(
            "UNLINKED doses audited:",
            len(unlinked_doses),
        )

        print(
            "MEAL_LINKED excluded:",
            linked_count,
        )

        for dose in unlinked_doses:
            stats["cases"] += 1

            (
                decision_t0,
                situation,
            ) = build_predose_situation(
                cache=cache,
                dose=dose,
                timezone=timezone,
                meal_by_id=meal_by_id,
            )

            case_label = (
                dose.administered_at
                .astimezone(
                    timezone
                )
                .isoformat()
            )

            # -------------------------------------------------
            # 1. Decision point MUST be before hidden dose.
            # -------------------------------------------------

            add_check(
                stats,
                failures,
                case_label,
                "decision_before_hidden_dose",
                decision_t0
                < dose.administered_at,
                actual=decision_t0,
                expected=(
                    f"< {dose.administered_at}"
                ),
            )

            # -------------------------------------------------
            # 2. Situation timestamp must equal decision_t0.
            # -------------------------------------------------

            situation_time = (
                datetime.fromisoformat(
                    situation[
                        "timestamp"
                    ]
                )
            )

            add_check(
                stats,
                failures,
                case_label,
                "situation_timestamp",
                situation_time
                == decision_t0,
                actual=situation_time,
                expected=decision_t0,
            )

            # -------------------------------------------------
            # 3. Hidden dose itself must NOT be visible.
            # -------------------------------------------------

            visible_doses = [
                item
                for item
                in cache.novorapid_doses
                if (
                    item.administered_at
                    <= decision_t0
                )
            ]

            hidden_visible = any(
                item.id == dose.id
                for item in visible_doses
            )

            add_check(
                stats,
                failures,
                case_label,
                "hidden_dose_not_visible",
                not hidden_visible,
                actual=hidden_visible,
                expected=False,
            )

            # -------------------------------------------------
            # 4. Current glucose must be latest glucose <= t0.
            # -------------------------------------------------

            expected_glucose = (
                cache._latest_glucose(
                    decision_t0
                )
            )

            expected_glucose_value = (
                float(
                    expected_glucose.value_mmol_l
                )
                if expected_glucose
                else None
            )

            actual_glucose_value = (
                situation[
                    "glucose"
                ][
                    "current"
                ]
            )

            add_check(
                stats,
                failures,
                case_label,
                "current_glucose",
                same_float(
                    actual_glucose_value,
                    expected_glucose_value,
                ),
                actual=
                    actual_glucose_value,
                expected=
                    expected_glucose_value,
            )

            # -------------------------------------------------
            # 5. Glucose deltas must use only historical data.
            # -------------------------------------------------

            for minutes in (
                15,
                30,
                60,
            ):
                expected_delta = (
                    cache._glucose_delta(
                        decision_t0,
                        minutes,
                    )
                )

                actual_delta = (
                    situation[
                        "glucose"
                    ][
                        f"delta_{minutes}m"
                    ]
                )

                add_check(
                    stats,
                    failures,
                    case_label,
                    (
                        f"glucose_delta_"
                        f"{minutes}m"
                    ),
                    same_float(
                        actual_delta,
                        expected_delta,
                    ),
                    actual=
                        actual_delta,
                    expected=
                        expected_delta,
                )

            # -------------------------------------------------
            # 6. Previous NovoRapid must really be PRE-dose.
            # -------------------------------------------------

            expected_last_bolus = (
                cache._last_novorapid(
                    decision_t0
                )
            )

            actual_last_units = (
                situation[
                    "novorapid"
                ][
                    "last_bolus_units"
                ]
            )

            expected_last_units = (
                float(
                    expected_last_bolus.units
                )
                if expected_last_bolus
                else None
            )

            add_check(
                stats,
                failures,
                case_label,
                "last_bolus_units",
                same_float(
                    actual_last_units,
                    expected_last_units,
                ),
                actual=
                    actual_last_units,
                expected=
                    expected_last_units,
            )

            if expected_last_bolus:
                expected_minutes = round(
                    (
                        decision_t0
                        - expected_last_bolus
                        .administered_at
                    ).total_seconds()
                    / 60
                )

            else:
                expected_minutes = None

            actual_minutes = (
                situation[
                    "novorapid"
                ][
                    "minutes_since_last_bolus"
                ]
            )

            add_check(
                stats,
                failures,
                case_label,
                "minutes_since_last_bolus",
                actual_minutes
                == expected_minutes,
                actual=
                    actual_minutes,
                expected=
                    expected_minutes,
            )

            # -------------------------------------------------
            # 7. NovoRapid totals must exclude hidden dose.
            # -------------------------------------------------

            for hours in (
                2,
                4,
                6,
            ):
                expected_units = (
                    cache._sum_novorapid(
                        decision_t0,
                        hours,
                    )
                )

                actual_units = (
                    situation[
                        "novorapid"
                    ][
                        f"units_last_{hours}h"
                    ]
                )

                add_check(
                    stats,
                    failures,
                    case_label,
                    (
                        f"novorapid_"
                        f"{hours}h"
                    ),
                    same_float(
                        actual_units,
                        expected_units,
                    ),
                    actual=
                        actual_units,
                    expected=
                        expected_units,
                )

            # -------------------------------------------------
            # 8. Active insulin estimate must be pre-dose only.
            # -------------------------------------------------

            expected_active = (
                cache._estimate_active_novorapid(
                    decision_t0
                )
            )

            actual_active = (
                situation[
                    "novorapid"
                ][
                    "estimated_active_units"
                ]
            )

            add_check(
                stats,
                failures,
                case_label,
                "estimated_active_novorapid",
                same_float(
                    actual_active,
                    expected_active,
                ),
                actual=
                    actual_active,
                expected=
                    expected_active,
            )

            # -------------------------------------------------
            # 9. Last meal must not come from the future.
            # -------------------------------------------------

            expected_meal = (
                cache._last_meal(
                    decision_t0
                )
            )

            actual_meal_id = (
                situation[
                    "meal"
                ][
                    "last_meal_id"
                ]
            )

            expected_meal_id = (
                expected_meal.id
                if expected_meal
                else None
            )

            add_check(
                stats,
                failures,
                case_label,
                "last_meal_id",
                actual_meal_id
                == expected_meal_id,
                actual=
                    actual_meal_id,
                expected=
                    expected_meal_id,
            )

            if expected_meal:
                meal_not_future = (
                    expected_meal.eaten_at
                    <= decision_t0
                )

            else:
                meal_not_future = True

            add_check(
                stats,
                failures,
                case_label,
                "meal_not_from_future",
                meal_not_future,
                actual=(
                    expected_meal.eaten_at
                    if expected_meal
                    else None
                ),
                expected=(
                    f"<= {decision_t0}"
                ),
            )

            # -------------------------------------------------
            # 10. Last completed activity must not be future.
            # -------------------------------------------------

            expected_activity = (
                cache._last_activity(
                    decision_t0
                )
            )

            if expected_activity:
                activity_not_future = (
                    expected_activity.ended_at
                    <= decision_t0
                )

            else:
                activity_not_future = True

            add_check(
                stats,
                failures,
                case_label,
                "activity_not_from_future",
                activity_not_future,
                actual=(
                    expected_activity.ended_at
                    if expected_activity
                    else None
                ),
                expected=(
                    f"<= {decision_t0}"
                ),
            )

        print()
        print("=" * 100)
        print(
            "AUDIT SUMMARY"
        )
        print("-" * 100)

        print(
            "Cases audited:",
            stats[
                "cases"
            ],
        )

        print(
            "Checks performed:",
            stats[
                "checks"
            ],
        )

        print(
            "Passed:",
            stats[
                "passed"
            ],
        )

        print(
            "Failed:",
            stats[
                "failed"
            ],
        )

        if failures:
            print()
            print(
                "FAILURES "
                f"(showing max "
                f"{MAX_FAILURES_TO_PRINT})"
            )
            print("-" * 100)

            for failure in failures[
                :MAX_FAILURES_TO_PRINT
            ]:
                print(
                    failure[
                        "case"
                    ]
                )

                print(
                    "   ",
                    failure[
                        "check"
                    ],
                )

                print(
                    "    actual:  ",
                    failure[
                        "actual"
                    ],
                )

                print(
                    "    expected:",
                    failure[
                        "expected"
                    ],
                )

        print()
        print("=" * 100)

        if stats["failed"] == 0:
            print(
                "RESULT: PASS"
            )

            print(
                "No pre-dose leakage detected "
                "in audited Shadow V1 "
                "UNLINKED situations."
            )

        else:
            print(
                "RESULT: FAIL"
            )

            print(
                "Shadow V1 must NOT be enabled "
                "until these failures are fixed."
            )

        print()
        print(
            "MEAL_LINKED cases remain "
            "ABSTAIN in Shadow V1."
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 100)

    finally:
        db.close()


if __name__ == "__main__":
    main()