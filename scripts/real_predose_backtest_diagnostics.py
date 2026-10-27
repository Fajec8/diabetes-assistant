from __future__ import annotations

import uuid
from datetime import timedelta
from math import floor
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.user import User
from app.services.history_search import (
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

from scripts.real_predose_backtest import (
    CLARITY_SOURCE,
    EVALUATION_DAYS,
    EVALUATION_END_GAP_HOURS,
    HISTORY_DAYS,
    MIN_CONTEXT_COVERAGE,
    REFERENCE_SAFETY_HOURS,
    USER_ID,
    build_clean_outcome,
    build_predose_situation,
    prepare_real_cache,
    select_diverse_top_k,
)


def round_to_half(
    value: float,
) -> float:
    return round(
        floor(
            value / 0.5 + 0.5
        )
        * 0.5,
        2,
    )


def dose_group(
    value: float,
) -> str:
    if value <= 2.0:
        return "0-2 U"

    if value <= 4.0:
        return "2.5-4 U"

    if value <= 6.0:
        return "4.5-6 U"

    return ">6 U"


def support_group(
    count: int,
) -> str:
    if count <= 3:
        return "2-3"

    if count <= 5:
        return "4-5"

    return "6+"


def glucose_group(
    value: float | None,
) -> str:
    if value is None:
        return "MISSING"

    if value < 6.0:
        return "<6"

    if value <= 10.0:
        return "6-10"

    return ">10"


def trend_group(
    value: float | None,
) -> str:
    if value is None:
        return "MISSING"

    if value > 0.5:
        return "RISING"

    if value < -0.5:
        return "FALLING"

    return "STABLE"


def quality_group(
    quality: float | None,
) -> str:
    if quality is None:
        return "NO_DATA"

    if quality >= 75:
        return "GOOD+"

    if quality >= 60:
        return "ACCEPTABLE"

    return "POOR"


def calculate_metrics(
    rows: list[dict],
    prediction_key: str,
) -> dict | None:
    usable = [
        row
        for row in rows
        if row.get(
            prediction_key
        ) is not None
    ]

    if not usable:
        return None

    errors = [
        abs(
            row[
                prediction_key
            ]
            - row[
                "actual_units"
            ]
        )
        for row in usable
    ]

    signed_errors = [
        row[
            prediction_key
        ]
        - row[
            "actual_units"
        ]
        for row in usable
    ]

    exact = sum(
        error == 0
        for error in errors
    )

    within_half = sum(
        error <= 0.5
        for error in errors
    )

    within_one = sum(
        error <= 1.0
        for error in errors
    )

    return {
        "n":
            len(
                usable
            ),

        "mae":
            round(
                sum(
                    errors
                )
                / len(
                    errors
                ),
                2,
            ),

        "median_error":
            round(
                median(
                    errors
                ),
                2,
            ),

        "signed_error":
            round(
                sum(
                    signed_errors
                )
                / len(
                    signed_errors
                ),
                2,
            ),

        "exact":
            round(
                exact
                / len(
                    errors
                )
                * 100.0,
                1,
            ),

        "within_half":
            round(
                within_half
                / len(
                    errors
                )
                * 100.0,
                1,
            ),

        "within_one":
            round(
                within_one
                / len(
                    errors
                )
                * 100.0,
                1,
            ),
    }


def print_metrics(
    label: str,
    metrics: dict | None,
):
    if metrics is None:
        print(
            f"{label:<30} NO DATA"
        )
        return

    print(
        f"{label:<30}"
        f" n={metrics['n']:<3}"
        f" MAE={metrics['mae']:<5} U"
        f" median={metrics['median_error']:<4} U"
        f" bias={metrics['signed_error']:<5} U"
        f" ±0.5={metrics['within_half']:>5}%"
        f" ±1.0={metrics['within_one']:>5}%"
    )


def print_group_diagnostics(
    rows: list[dict],
    title: str,
    group_key: str,
):
    print()
    print("=" * 110)
    print(title)
    print("-" * 110)

    groups = {}

    for row in rows:
        label = row[
            group_key
        ]

        groups.setdefault(
            label,
            [],
        ).append(
            row
        )

    for label in sorted(
        groups.keys()
    ):
        metrics = (
            calculate_metrics(
                groups[
                    label
                ],
                "model_estimate",
            )
        )

        print_metrics(
            str(
                label
            ),
            metrics,
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
        print("=" * 110)
        print(
            "REAL PRE-DOSE BACKTEST DIAGNOSTICS"
        )
        print("=" * 110)

        print(
            "Evaluation:",
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
            "Building snapshots..."
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

                    "quality_confidence":
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
        skipped = 0

        for target in targets:
            target_situation = (
                target[
                    "situation"
                ]
            )

            current_glucose = (
                target_situation[
                    "glucose"
                ][
                    "current"
                ]
            )

            if current_glucose is None:
                skipped += 1
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

            if not top_matches:
                continue

            evidence_cases = []

            usable_evidence_scores = []

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
                                "quality_confidence"
                            ],
                    )
                )

                evidence_score = (
                    evidence[
                        "evidence_score"
                    ]
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
                            evidence_score,
                    }
                )

                if (
                    evidence_score
                    is not None
                    and evidence_score >= 40
                ):
                    usable_evidence_scores.append(
                        evidence_score
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

            top1_estimate = (
                float(
                    top_matches[
                        0
                    ][
                        "dose"
                    ].units
                )
            )

            top_doses = [
                float(
                    match[
                        "dose"
                    ].units
                )
                for match
                in top_matches
            ]

            top10_median = (
                round_to_half(
                    median(
                        top_doses
                    )
                )
            )

            historical_doses = [
                float(
                    reference[
                        "dose"
                    ].units
                )
                for reference
                in comparisons
            ]

            history_median = None

            if historical_doses:
                history_median = (
                    round_to_half(
                        median(
                            historical_doses
                        )
                    )
                )

            delta_30 = (
                target_situation[
                    "glucose"
                ][
                    "delta_30m"
                ]
            )

            strongest_evidence = None

            if usable_evidence_scores:
                strongest_evidence = max(
                    usable_evidence_scores
                )

            row = {
                "timestamp":
                    target[
                        "decision_t0"
                    ],

                "actual_units":
                    actual_units,

                "model_estimate":
                    estimate[
                        "estimated_units"
                    ],

                "top1_estimate":
                    top1_estimate,

                "top10_median":
                    top10_median,

                "history_median":
                    history_median,

                "support_count":
                    estimate[
                        "support_count"
                    ],

                "dose_group":
                    dose_group(
                        actual_units
                    ),

                "support_group":
                    support_group(
                        estimate[
                            "support_count"
                        ]
                    )
                    if (
                        estimate[
                            "support_count"
                        ]
                        >= 2
                    )
                    else "<2",

                "meal_link":
                    (
                        "MEAL_LINKED"
                        if (
                            target[
                                "dose"
                            ].meal_id
                            is not None
                        )
                        else "UNLINKED"
                    ),

                "glucose_group":
                    glucose_group(
                        current_glucose
                    ),

                "trend_group":
                    trend_group(
                        delta_30
                    ),

                "target_quality_group":
                    quality_group(
                        target[
                            "quality_score"
                        ]
                    ),

                "target_quality":
                    target[
                        "quality_score"
                    ],

                "target_quality_confidence":
                    target[
                        "quality_confidence"
                    ],

                "strongest_evidence":
                    strongest_evidence,
            }

            results.append(
                row
            )

        estimated_rows = [
            row
            for row in results
            if row[
                "model_estimate"
            ]
            is not None
        ]

        print()
        print("=" * 110)
        print(
            "BASIC COUNTS"
        )
        print("-" * 110)

        print(
            "Targets processed:",
            len(
                results
            ),
        )

        print(
            "Skipped no glucose:",
            skipped,
        )

        print(
            "Evidence estimates:",
            len(
                estimated_rows
            ),
        )

        print(
            "Abstained:",
            len(
                results
            )
            - len(
                estimated_rows
            ),
        )

        print()
        print("=" * 110)
        print(
            "FAIR COMPARISON - SAME CASES "
            "WHERE EVIDENCE MODEL PRODUCED AN ESTIMATE"
        )
        print("-" * 110)

        print_metrics(
            "Evidence model",
            calculate_metrics(
                estimated_rows,
                "model_estimate",
            ),
        )

        print_metrics(
            "Top-1 similar dose",
            calculate_metrics(
                estimated_rows,
                "top1_estimate",
            ),
        )

        print_metrics(
            "Median TOP-10 doses",
            calculate_metrics(
                estimated_rows,
                "top10_median",
            ),
        )

        print_metrics(
            "90-day dose median",
            calculate_metrics(
                estimated_rows,
                "history_median",
            ),
        )

        print()
        print("=" * 110)
        print(
            "BASELINES ON ALL PROCESSED TARGETS"
        )
        print("-" * 110)

        print_metrics(
            "Top-1 similar dose",
            calculate_metrics(
                results,
                "top1_estimate",
            ),
        )

        print_metrics(
            "Median TOP-10 doses",
            calculate_metrics(
                results,
                "top10_median",
            ),
        )

        print_metrics(
            "90-day dose median",
            calculate_metrics(
                results,
                "history_median",
            ),
        )

        print_group_diagnostics(
            estimated_rows,
            "ERROR BY ACTUAL DOSE",
            "dose_group",
        )

        print_group_diagnostics(
            estimated_rows,
            "ERROR BY SUPPORT COUNT",
            "support_group",
        )

        print_group_diagnostics(
            estimated_rows,
            "ERROR BY MEAL LINK",
            "meal_link",
        )

        print_group_diagnostics(
            estimated_rows,
            "ERROR BY STARTING GLUCOSE",
            "glucose_group",
        )

        print_group_diagnostics(
            estimated_rows,
            "ERROR BY 30-MIN GLUCOSE TREND",
            "trend_group",
        )

        print_group_diagnostics(
            estimated_rows,
            "ERROR BY ACTUAL OUTCOME QUALITY",
            "target_quality_group",
        )

        high_confidence_targets = [
            row
            for row in estimated_rows
            if (
                row[
                    "target_quality_confidence"
                ]
                is not None

                and row[
                    "target_quality_confidence"
                ]
                >= 80
            )
        ]

        print()
        print("=" * 110)
        print(
            "HIGH-CONFIDENCE ACTUAL OUTCOMES ONLY"
        )
        print("-" * 110)

        print_metrics(
            "Evidence model",
            calculate_metrics(
                high_confidence_targets,
                "model_estimate",
            ),
        )

        print()
        print(
            "Interpretation note:"
        )

        print(
            "- This backtest measures similarity "
            "to historically recorded actions."
        )

        print(
            "- A difference from the historical dose "
            "is NOT automatically a bad clinical outcome."
        )

        print(
            "- Poor historical outcomes are therefore "
            "shown separately above."
        )

        print()
        print(
            "RESEARCH / RETROSPECTIVE ANALYSIS ONLY."
        )

        print(
            "No current insulin dose is calculated."
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 110)

    finally:
        db.close()


if __name__ == "__main__":
    main()