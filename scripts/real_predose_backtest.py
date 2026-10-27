from __future__ import annotations

import uuid
from bisect import (
    bisect_left,
    bisect_right,
)
from copy import deepcopy
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

from app.services.history_search import (
    _HistorySituationCache,
    calculate_ranking_score,
)

from app.services.outcome_evidence import (
    evaluate_evidence_strength,
)

from app.services.outcome_quality import (
    evaluate_outcome_quality,
)

from app.services.research_action_estimation import (
    estimate_research_action,
)

from app.services.similarity import (
    compare_situations,
)


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

CLARITY_SOURCE = "DEXCOM_CLARITY"
CLARITY_NOTE = "Imported from Dexcom Clarity CSV"

NOVORAPID = "NOVORAPID"

EVALUATION_DAYS = 30
HISTORY_DAYS = 90

EVALUATION_END_GAP_HOURS = 24
REFERENCE_SAFETY_HOURS = 6

TOP_K = 10
MIN_SEPARATION_HOURS = 4

MIN_CONTEXT_COVERAGE = 70.0

LINKED_MEAL_LOOKAHEAD_MINUTES = 30

HORIZONS = [
    30,
    60,
    90,
    120,
    180,
]

GLUCOSE_TOLERANCE_MINUTES = 10

EXAMPLES_TO_SHOW = 12


def prepare_real_cache(
    db,
    latest_real_time,
    preload_start,
):
    cache = _HistorySituationCache(
        db=db,
        user_id=USER_ID,
        search_t0=latest_real_time,
    )

    cache.glucose_readings = (
        db.execute(
            select(
                GlucoseReading
            )
            .where(
                GlucoseReading.user_id
                == USER_ID,

                GlucoseReading.source
                == CLARITY_SOURCE,

                GlucoseReading.measured_at
                >= preload_start,

                GlucoseReading.measured_at
                <= latest_real_time,
            )
            .order_by(
                GlucoseReading.measured_at
            )
        )
        .scalars()
        .all()
    )

    cache.glucose_times = [
        row.measured_at
        for row
        in cache.glucose_readings
    ]

    cache.meals = [
        meal
        for meal in cache.meals
        if meal.note
        == CLARITY_NOTE
    ]

    cache.meal_times = [
        meal.eaten_at
        for meal
        in cache.meals
    ]

    cache.meal_carbs_prefix = (
        cache._build_prefix(
            cache.meals,
            "carbohydrates_g",
        )
    )

    cache.novorapid_doses = [
        dose
        for dose
        in cache.novorapid_doses
        if dose.source
        == CLARITY_SOURCE
    ]

    cache.tresiba_doses = [
        dose
        for dose
        in cache.tresiba_doses
        if dose.source
        == CLARITY_SOURCE
    ]

    cache.novorapid_times = [
        dose.administered_at
        for dose
        in cache.novorapid_doses
    ]

    cache.tresiba_times = [
        dose.administered_at
        for dose
        in cache.tresiba_doses
    ]

    cache.novorapid_units_prefix = (
        cache._build_prefix(
            cache.novorapid_doses,
            "units",
        )
    )

    cache.novorapid_doses_by_meal = {}

    for dose in cache.novorapid_doses:
        if dose.meal_id is None:
            continue

        cache.novorapid_doses_by_meal.setdefault(
            dose.meal_id,
            [],
        ).append(
            dose
        )

    cache.activities = (
        db.execute(
            select(
                Activity
            )
            .where(
                Activity.user_id
                == USER_ID,

                Activity.note
                == CLARITY_NOTE,

                Activity.ended_at
                >= (
                    preload_start
                    - timedelta(
                        hours=48
                    )
                ),

                Activity.started_at
                <= latest_real_time,
            )
            .order_by(
                Activity.ended_at
            )
        )
        .scalars()
        .all()
    )

    cache.activity_end_times = [
        activity.ended_at
        for activity
        in cache.activities
    ]

    return cache


def apply_linked_meal_context(
    situation,
    dose,
    meal_by_id,
    cache,
    decision_t0,
):
    if dose.meal_id is None:
        return situation

    meal = meal_by_id.get(
        dose.meal_id
    )

    if meal is None:
        return situation

    # Pokud už je jídlo v okamžiku rozhodnutí
    # v historii, cache ho již správně obsahuje.
    if meal.eaten_at <= decision_t0:
        return situation

    delay_minutes = (
        meal.eaten_at
        - dose.administered_at
    ).total_seconds() / 60.0

    # U prebolusu považujeme propojené jídlo
    # do 30 minut za kontext známý při rozhodnutí.
    if (
        delay_minutes < 0
        or delay_minutes
        > LINKED_MEAL_LOOKAHEAD_MINUTES
    ):
        return situation

    result = deepcopy(
        situation
    )

    carbs = float(
        meal.carbohydrates_g
    )

    result["meal"][
        "last_meal_carbs"
    ] = carbs

    result["meal"][
        "minutes_since_last_meal"
    ] = 0

    result["meal"][
        "carbs_last_2h"
    ] = round(
        float(
            result[
                "meal"
            ][
                "carbs_last_2h"
            ]
        )
        + carbs,
        2,
    )

    result["meal"][
        "carbs_last_4h"
    ] = round(
        float(
            result[
                "meal"
            ][
                "carbs_last_4h"
            ]
        )
        + carbs,
        2,
    )

    result["meal"][
        "last_meal_id"
    ] = meal.id

    result["meal"][
        "last_meal_description"
    ] = meal.description

    result["meal"][
        "last_meal_note"
    ] = meal.note

    result["meal"][
        "items"
    ] = cache._meal_items(
        meal
    )

    # Vyhodnocovaná dávka musí zůstat skrytá.
    result["meal"][
        "linked_bolus"
    ] = None

    return result


def build_predose_situation(
    cache,
    dose,
    timezone,
    meal_by_id,
):
    decision_t0 = (
        dose.administered_at
        - timedelta(
            seconds=1
        )
    )

    situation = (
        cache.build_situation(
            t0=decision_t0,
            timezone=timezone,
        )
    )

    situation = (
        apply_linked_meal_context(
            situation=situation,
            dose=dose,
            meal_by_id=meal_by_id,
            cache=cache,
            decision_t0=decision_t0,
        )
    )

    return (
        decision_t0,
        situation,
    )


def nearest_glucose_value(
    glucose_rows,
    glucose_times,
    target,
    past_only=False,
):
    if not glucose_rows:
        return None

    tolerance = timedelta(
        minutes=
            GLUCOSE_TOLERANCE_MINUTES
    )

    index = bisect_left(
        glucose_times,
        target,
    )

    candidates = []

    if index < len(
        glucose_rows
    ):
        candidates.append(
            glucose_rows[
                index
            ]
        )

    if index > 0:
        candidates.append(
            glucose_rows[
                index - 1
            ]
        )

    if past_only:
        candidates = [
            row
            for row in candidates
            if row.measured_at
            <= target
        ]

    if not candidates:
        return None

    row = min(
        candidates,
        key=lambda item: abs(
            (
                item.measured_at
                - target
            ).total_seconds()
        ),
    )

    if (
        abs(
            row.measured_at
            - target
        )
        > tolerance
    ):
        return None

    return float(
        row.value_mmol_l
    )


def first_future_action_minutes(
    decision_t0,
    selected_dose,
    insulin_rows,
    insulin_times,
    meal_rows,
    meal_times,
    activity_rows,
    activity_times,
):
    end = (
        decision_t0
        + timedelta(
            minutes=180
        )
    )

    possible_times = []

    insulin_index = bisect_right(
        insulin_times,
        selected_dose.administered_at,
    )

    if insulin_index < len(
        insulin_rows
    ):
        next_insulin = (
            insulin_rows[
                insulin_index
            ]
        )

        if (
            next_insulin.administered_at
            <= end
        ):
            possible_times.append(
                next_insulin.administered_at
            )

    meal_index = bisect_right(
        meal_times,
        decision_t0,
    )

    while meal_index < len(
        meal_rows
    ):
        meal = meal_rows[
            meal_index
        ]

        if meal.eaten_at > end:
            break

        if not (
            selected_dose.meal_id
            is not None
            and meal.id
            == selected_dose.meal_id
        ):
            possible_times.append(
                meal.eaten_at
            )
            break

        meal_index += 1

    activity_index = bisect_right(
        activity_times,
        decision_t0,
    )

    if activity_index < len(
        activity_rows
    ):
        activity = (
            activity_rows[
                activity_index
            ]
        )

        if (
            activity.started_at
            <= end
        ):
            possible_times.append(
                activity.started_at
            )

    if not possible_times:
        return None

    first = min(
        possible_times
    )

    return (
        first - decision_t0
    ).total_seconds() / 60.0


def build_clean_outcome(
    decision_t0,
    selected_dose,
    glucose_rows,
    glucose_times,
    insulin_rows,
    insulin_times,
    meal_rows,
    meal_times,
    activity_rows,
    activity_times,
):
    baseline = (
        nearest_glucose_value(
            glucose_rows,
            glucose_times,
            decision_t0,
            past_only=True,
        )
    )

    first_action = (
        first_future_action_minutes(
            decision_t0=
                decision_t0,

            selected_dose=
                selected_dose,

            insulin_rows=
                insulin_rows,

            insulin_times=
                insulin_times,

            meal_rows=
                meal_rows,

            meal_times=
                meal_times,

            activity_rows=
                activity_rows,

            activity_times=
                activity_times,
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
            value = (
                nearest_glucose_value(
                    glucose_rows,
                    glucose_times,
                    decision_t0
                    + timedelta(
                        minutes=minutes
                    ),
                )
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

    return outcome


def select_diverse_top_k(
    candidates,
):
    ordered = sorted(
        candidates,
        key=lambda item:
            item["context_rank"],
        reverse=True,
    )

    selected = []

    minimum_separation = timedelta(
        hours=
            MIN_SEPARATION_HOURS
    )

    for candidate in ordered:
        too_close = any(
            abs(
                candidate[
                    "decision_t0"
                ]
                - selected_item[
                    "decision_t0"
                ]
            )
            < minimum_separation
            for selected_item
            in selected
        )

        if too_close:
            continue

        selected.append(
            candidate
        )

        if len(
            selected
        ) >= TOP_K:
            break

    return selected


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

        evaluation_end = (
            latest_real_time
            - timedelta(
                hours=
                    EVALUATION_END_GAP_HOURS
            )
        )

        evaluation_start = (
            evaluation_end
            - timedelta(
                days=
                    EVALUATION_DAYS
            )
        )

        preload_start = (
            evaluation_start
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
            meal.id: meal
            for meal
            in cache.meals
        }

        all_insulin = (
            db.execute(
                select(
                    InsulinDose
                )
                .where(
                    InsulinDose.user_id
                    == USER_ID,

                    InsulinDose.source
                    == CLARITY_SOURCE,

                    InsulinDose.administered_at
                    >= preload_start,

                    InsulinDose.administered_at
                    <= latest_real_time,
                )
                .order_by(
                    InsulinDose.administered_at
                )
            )
            .scalars()
            .all()
        )

        insulin_times = [
            dose.administered_at
            for dose
            in all_insulin
        ]

        all_meals = [
            meal
            for meal
            in cache.meals
            if (
                meal.eaten_at
                >= preload_start
                and meal.eaten_at
                <= latest_real_time
            )
        ]

        meal_times = [
            meal.eaten_at
            for meal
            in all_meals
        ]

        all_activities = sorted(
            cache.activities,
            key=lambda item:
                item.started_at,
        )

        activity_times = [
            activity.started_at
            for activity
            in all_activities
        ]

        rapid_doses = [
            dose
            for dose
            in cache.novorapid_doses
            if (
                dose.administered_at
                >= preload_start
                and dose.administered_at
                <= evaluation_end
            )
        ]

        snapshots = []

        print()
        print("=" * 100)
        print(
            "REAL PRE-DOSE RETROSPECTIVE BACKTEST"
        )
        print("=" * 100)

        print(
            "Evaluation window:",
            evaluation_start
            .astimezone(
                timezone
            )
            .isoformat(),
            "->",
            evaluation_end
            .astimezone(
                timezone
            )
            .isoformat(),
        )

        print(
            "Historical search:",
            HISTORY_DAYS,
            "days",
        )

        print(
            "NovoRapid records loaded:",
            len(
                rapid_doses
            ),
        )

        print()
        print(
            "Building historical "
            "pre-dose snapshots..."
        )

        for dose in rapid_doses:
            (
                decision_t0,
                situation,
            ) = build_predose_situation(
                cache=cache,
                dose=dose,
                timezone=timezone,
                meal_by_id=meal_by_id,
            )

            outcome = (
                build_clean_outcome(
                    decision_t0=
                        decision_t0,

                    selected_dose=
                        dose,

                    glucose_rows=
                        cache.glucose_readings,

                    glucose_times=
                        cache.glucose_times,

                    insulin_rows=
                        all_insulin,

                    insulin_times=
                        insulin_times,

                    meal_rows=
                        all_meals,

                    meal_times=
                        meal_times,

                    activity_rows=
                        all_activities,

                    activity_times=
                        activity_times,
                )
            )

            quality = (
                evaluate_outcome_quality(
                    outcome
                )
            )

            snapshots.append(
                {
                    "dose":
                        dose,

                    "decision_t0":
                        decision_t0,

                    "situation":
                        situation,

                    "quality_score":
                        quality[
                            "quality_score"
                        ],

                    "confidence":
                        quality[
                            "confidence"
                        ],
                }
            )

        targets = [
            snapshot
            for snapshot
            in snapshots
            if (
                snapshot[
                    "dose"
                ].administered_at
                >= evaluation_start
                and snapshot[
                    "dose"
                ].administered_at
                <= evaluation_end
            )
        ]

        print(
            "Evaluation targets:",
            len(
                targets
            ),
        )

        results = []

        skipped_no_glucose = 0

        for target in targets:
            target_situation = (
                target[
                    "situation"
                ]
            )

            if (
                target_situation[
                    "glucose"
                ][
                    "current"
                ]
                is None
            ):
                skipped_no_glucose += 1
                continue

            candidate_start = (
                target[
                    "decision_t0"
                ]
                - timedelta(
                    days=
                        HISTORY_DAYS
                )
            )

            candidate_end = (
                target[
                    "decision_t0"
                ]
                - timedelta(
                    hours=
                        REFERENCE_SAFETY_HOURS
                )
            )

            comparisons = []

            for reference in snapshots:
                if (
                    reference[
                        "decision_t0"
                    ]
                    < candidate_start
                ):
                    continue

                if (
                    reference[
                        "decision_t0"
                    ]
                    >= candidate_end
                ):
                    continue

                comparison = (
                    compare_situations(
                        target_situation,
                        reference[
                            "situation"
                        ],
                    )
                )

                similarity = float(
                    comparison[
                        "similarity_score"
                    ]
                )

                coverage = float(
                    comparison[
                        "data_coverage"
                    ]
                )

                if (
                    coverage
                    < MIN_CONTEXT_COVERAGE
                ):
                    continue

                context_rank = float(
                    calculate_ranking_score(
                        similarity,
                        coverage,
                    )
                )

                comparisons.append(
                    {
                        **reference,

                        "similarity":
                            similarity,

                        "coverage":
                            coverage,

                        "context_rank":
                            context_rank,
                    }
                )

            top_matches = (
                select_diverse_top_k(
                    comparisons
                )
            )

            evidence_cases = []

            for match in top_matches:
                evidence = (
                    evaluate_evidence_strength(
                        context_score=
                            match[
                                "context_rank"
                            ],

                        quality_score=
                            match[
                                "quality_score"
                            ],

                        confidence=
                            match[
                                "confidence"
                            ],
                    )
                )

                evidence_cases.append(
                    {
                        "dose_units":
                            float(
                                match[
                                    "dose"
                                ].units
                            ),

                        "evidence_score":
                            evidence[
                                "evidence_score"
                            ],
                    }
                )

            estimate = (
                estimate_research_action(
                    evidence_cases
                )
            )

            actual_units = float(
                target[
                    "dose"
                ].units
            )

            estimated_units = (
                estimate[
                    "estimated_units"
                ]
            )

            absolute_error = None
            signed_error = None

            if estimated_units is not None:
                absolute_error = round(
                    abs(
                        estimated_units
                        - actual_units
                    ),
                    2,
                )

                signed_error = round(
                    estimated_units
                    - actual_units,
                    2,
                )

            results.append(
                {
                    "timestamp":
                        target[
                            "dose"
                        ].administered_at,

                    "actual_units":
                        actual_units,

                    "estimated_units":
                        estimated_units,

                    "absolute_error":
                        absolute_error,

                    "signed_error":
                        signed_error,

                    "support_count":
                        estimate[
                            "support_count"
                        ],

                    "status":
                        estimate[
                            "status"
                        ],

                    "weighted_mean_units":
                        estimate[
                            "weighted_mean_units"
                        ],

                    "top_match_count":
                        len(
                            top_matches
                        ),
                }
            )

        estimated_results = [
            result
            for result
            in results
            if result[
                "estimated_units"
            ]
            is not None
        ]

        abstained_results = [
            result
            for result
            in results
            if result[
                "estimated_units"
            ]
            is None
        ]

        errors = [
            result[
                "absolute_error"
            ]
            for result
            in estimated_results
        ]

        signed_errors = [
            result[
                "signed_error"
            ]
            for result
            in estimated_results
        ]

        print()
        print("=" * 100)
        print(
            "BACKTEST SUMMARY"
        )
        print("-" * 100)

        print(
            "Targets processed:",
            len(
                results
            ),
        )

        print(
            "Skipped - no glucose:",
            skipped_no_glucose,
        )

        print(
            "Estimates produced:",
            len(
                estimated_results
            ),
        )

        print(
            "Abstained:",
            len(
                abstained_results
            ),
        )

        if results:
            estimate_rate = round(
                len(
                    estimated_results
                )
                / len(
                    results
                )
                * 100.0,
                1,
            )

            print(
                "Estimate rate:",
                estimate_rate,
                "%",
            )

        if errors:
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

            mean_signed_error = round(
                sum(
                    signed_errors
                )
                / len(
                    signed_errors
                ),
                2,
            )

            exact = sum(
                error == 0
                for error
                in errors
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
                "Mean signed error:",
                mean_signed_error,
                "U",
            )

            print()
            print(
                "Exact match:",
                exact,
                "/",
                len(
                    errors
                ),
                "=",
                round(
                    exact
                    / len(
                        errors
                    )
                    * 100.0,
                    1,
                ),
                "%",
            )

            print(
                "Within ±0.5 U:",
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
                "Within ±1.0 U:",
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

        print()
        print("=" * 100)
        print(
            "MOST RECENT RETROSPECTIVE EXAMPLES"
        )
        print("-" * 100)

        recent = sorted(
            estimated_results,
            key=lambda result:
                result[
                    "timestamp"
                ],
            reverse=True,
        )[
            :EXAMPLES_TO_SHOW
        ]

        for result in recent:
            print(
                result[
                    "timestamp"
                ]
                .astimezone(
                    timezone
                )
                .isoformat(),
                "| actual=",
                result[
                    "actual_units"
                ],
                "U",
                "| estimate=",
                result[
                    "estimated_units"
                ],
                "U",
                "| error=",
                result[
                    "absolute_error"
                ],
                "U",
                "| support=",
                result[
                    "support_count"
                ],
            )

        print()
        print(
            "Estimator:"
        )

        print(
            "- TOP 10 selected by "
            "pre-dose context similarity"
        )

        print(
            "- evidence = context × "
            "outcome quality × confidence"
        )

        print(
            "- only evidence >= 40 "
            "is used for action estimation"
        )

        print(
            "- at least 2 usable historical "
            "cases are required"
        )

        print(
            "- otherwise the model ABSTAINS"
        )

        print(
            "- primary retrospective estimator "
            "= evidence-weighted median"
        )

        print(
            "- result rounded to historical "
            "0.5 U step"
        )

        print()
        print(
            "Linked meal assumption:"
        )

        print(
            "- a meal linked to the hidden dose "
            "and occurring within 30 min after it "
            "is treated as meal context known "
            "at decision time"
        )

        print()
        print(
            "RESEARCH / RETROSPECTIVE "
            "EVALUATION ONLY."
        )

        print(
            "No current insulin dose "
            "is calculated or recommended."
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 100)

    finally:
        db.close()


if __name__ == "__main__":
    main()