from __future__ import annotations

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


EVIDENCE_THRESHOLDS = [
    0.0,
    20.0,
    30.0,
    40.0,
    50.0,
    60.0,
]

MIN_SUPPORT_VALUES = [
    2,
    3,
    4,
    5,
    6,
]

TOP_K_MEDIANS = [
    3,
    5,
    10,
]

MIN_RESULTS_FOR_RANKING = 20
MIN_PRACTICAL_ESTIMATE_RATE = 40.0

TOP_RESULTS_TO_SHOW = 15


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


def weighted_mean(
    cases: list[dict],
) -> float | None:
    total_weight = sum(
        case["evidence_score"]
        for case in cases
    )

    if total_weight <= 0:
        return None

    value = sum(
        case["dose_units"]
        * case["evidence_score"]
        for case in cases
    ) / total_weight

    return round_to_half(
        value
    )


def weighted_median(
    cases: list[dict],
) -> float | None:
    if not cases:
        return None

    ordered = sorted(
        cases,
        key=lambda case:
            case["dose_units"],
    )

    total_weight = sum(
        case["evidence_score"]
        for case in ordered
    )

    if total_weight <= 0:
        return None

    threshold = (
        total_weight / 2.0
    )

    cumulative = 0.0

    for case in ordered:
        cumulative += (
            case["evidence_score"]
        )

        if cumulative >= threshold:
            return round_to_half(
                case["dose_units"]
            )

    return round_to_half(
        ordered[-1][
            "dose_units"
        ]
    )


def ordinary_top_k_median(
    matches: list[dict],
    k: int,
) -> float | None:
    if len(matches) < k:
        return None

    doses = [
        match["dose_units"]
        for match in matches[:k]
    ]

    return round_to_half(
        median(
            doses
        )
    )


def build_configurations():
    configs = []

    for threshold in EVIDENCE_THRESHOLDS:
        for support in MIN_SUPPORT_VALUES:
            configs.append(
                {
                    "type":
                        "EVIDENCE_MEDIAN",

                    "threshold":
                        threshold,

                    "support":
                        support,

                    "label":
                        (
                            f"E-MED "
                            f"ev>={threshold:g} "
                            f"sup>={support}"
                        ),
                }
            )

            configs.append(
                {
                    "type":
                        "EVIDENCE_MEAN",

                    "threshold":
                        threshold,

                    "support":
                        support,

                    "label":
                        (
                            f"E-MEAN "
                            f"ev>={threshold:g} "
                            f"sup>={support}"
                        ),
                }
            )

    for k in TOP_K_MEDIANS:
        configs.append(
            {
                "type":
                    "TOPK_MEDIAN",

                "k":
                    k,

                "label":
                    f"TOP-{k} MEDIAN",
            }
        )

    return configs


def estimate_case(
    case: dict,
    config: dict,
) -> float | None:
    if (
        config["type"]
        == "TOPK_MEDIAN"
    ):
        return ordinary_top_k_median(
            case["matches"],
            config["k"],
        )

    usable = [
        match
        for match in case[
            "matches"
        ]
        if (
            match[
                "evidence_score"
            ]
            is not None

            and match[
                "evidence_score"
            ]
            >= config[
                "threshold"
            ]
        )
    ]

    if (
        len(
            usable
        )
        < config[
            "support"
        ]
    ):
        return None

    if (
        config["type"]
        == "EVIDENCE_MEDIAN"
    ):
        return weighted_median(
            usable
        )

    if (
        config["type"]
        == "EVIDENCE_MEAN"
    ):
        return weighted_mean(
            usable
        )

    raise ValueError(
        "Unknown estimator type"
    )


def calculate_metrics(
    cases: list[dict],
    config: dict,
) -> dict:
    predictions = []

    for case in cases:
        estimate = estimate_case(
            case,
            config,
        )

        if estimate is None:
            continue

        actual = case[
            "actual_units"
        ]

        predictions.append(
            {
                "estimate":
                    estimate,

                "actual":
                    actual,

                "absolute_error":
                    abs(
                        estimate
                        - actual
                    ),

                "signed_error":
                    estimate
                    - actual,
            }
        )

    total_cases = len(
        cases
    )

    n = len(
        predictions
    )

    if n == 0:
        return {
            "n": 0,
            "estimate_rate": 0.0,
            "mae": None,
            "median_error": None,
            "bias": None,
            "exact": None,
            "within_half": None,
            "within_one": None,
        }

    errors = [
        item[
            "absolute_error"
        ]
        for item in predictions
    ]

    signed_errors = [
        item[
            "signed_error"
        ]
        for item in predictions
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
            n,

        "estimate_rate":
            round(
                n
                / total_cases
                * 100.0,
                1,
            ),

        "mae":
            round(
                sum(
                    errors
                )
                / n,
                2,
            ),

        "median_error":
            round(
                median(
                    errors
                ),
                2,
            ),

        "bias":
            round(
                sum(
                    signed_errors
                )
                / n,
                2,
            ),

        "exact":
            round(
                exact
                / n
                * 100.0,
                1,
            ),

        "within_half":
            round(
                within_half
                / n
                * 100.0,
                1,
            ),

        "within_one":
            round(
                within_one
                / n
                * 100.0,
                1,
            ),
    }


def evaluate_scope(
    cases: list[dict],
    configurations: list[dict],
):
    rows = []

    for config in configurations:
        metrics = calculate_metrics(
            cases,
            config,
        )

        rows.append(
            {
                "config":
                    config,

                **metrics,
            }
        )

    return rows


def print_result(
    position: int,
    row: dict,
):
    print(
        f"{position:2}. "
        f"{row['config']['label']:<25}"
        f" | n={row['n']:<3}"
        f" | rate={row['estimate_rate']:>5}%"
        f" | MAE={row['mae']:<4} U"
        f" | median={row['median_error']:<4} U"
        f" | bias={row['bias']:<5} U"
        f" | ±0.5={row['within_half']:>5}%"
        f" | ±1.0={row['within_one']:>5}%"
    )


def print_ranked_results(
    title: str,
    rows: list[dict],
    minimum_rate: float | None = None,
):
    filtered = [
        row
        for row in rows
        if (
            row["mae"]
            is not None

            and row["n"]
            >= MIN_RESULTS_FOR_RANKING
        )
    ]

    if minimum_rate is not None:
        filtered = [
            row
            for row in filtered
            if (
                row[
                    "estimate_rate"
                ]
                >= minimum_rate
            )
        ]

    filtered.sort(
        key=lambda row: (
            row["mae"],
            row["median_error"],
            -row["estimate_rate"],
            abs(
                row["bias"]
            ),
        )
    )

    print()
    print("=" * 125)
    print(title)
    print("-" * 125)

    if not filtered:
        print(
            "No configurations matched "
            "the requested constraints."
        )
        return

    for position, row in enumerate(
        filtered[
            :TOP_RESULTS_TO_SHOW
        ],
        start=1,
    ):
        print_result(
            position,
            row,
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
        print("=" * 125)
        print(
            "REAL PRE-DOSE THRESHOLD + "
            "ESTIMATOR SWEEP"
        )
        print("=" * 125)

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

        cases = []
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

            if not top_matches:
                continue

            matches = []

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

                matches.append(
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

                        "context_rank":
                            match[
                                "context_rank"
                            ],
                    }
                )

            cases.append(
                {
                    "actual_units":
                        float(
                            target[
                                "dose"
                            ].units
                        ),

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

                    "matches":
                        matches,
                }
            )

        configurations = (
            build_configurations()
        )

        all_cases = cases

        meal_cases = [
            case
            for case in cases
            if (
                case[
                    "meal_link"
                ]
                == "MEAL_LINKED"
            )
        ]

        unlinked_cases = [
            case
            for case in cases
            if (
                case[
                    "meal_link"
                ]
                == "UNLINKED"
            )
        ]

        print()
        print(
            "Usable targets:",
            len(
                all_cases
            ),
        )

        print(
            "Skipped - no glucose:",
            skipped_no_glucose,
        )

        print(
            "Meal-linked:",
            len(
                meal_cases
            ),
        )

        print(
            "Unlinked:",
            len(
                unlinked_cases
            ),
        )

        print(
            "Configurations tested:",
            len(
                configurations
            ),
        )

        all_results = evaluate_scope(
            all_cases,
            configurations,
        )

        meal_results = evaluate_scope(
            meal_cases,
            configurations,
        )

        unlinked_results = (
            evaluate_scope(
                unlinked_cases,
                configurations,
            )
        )

        print_ranked_results(
            "ALL - BEST RAW MAE "
            "(minimum 20 estimates)",
            all_results,
        )

        print_ranked_results(
            (
                "ALL - PRACTICAL CANDIDATES "
                f"(estimate rate >= "
                f"{MIN_PRACTICAL_ESTIMATE_RATE:g}%)"
            ),
            all_results,
            minimum_rate=
                MIN_PRACTICAL_ESTIMATE_RATE,
        )

        print_ranked_results(
            "MEAL_LINKED - BEST RAW MAE",
            meal_results,
        )

        print_ranked_results(
            (
                "MEAL_LINKED - PRACTICAL "
                f"(estimate rate >= "
                f"{MIN_PRACTICAL_ESTIMATE_RATE:g}%)"
            ),
            meal_results,
            minimum_rate=
                MIN_PRACTICAL_ESTIMATE_RATE,
        )

        print_ranked_results(
            "UNLINKED - BEST RAW MAE",
            unlinked_results,
        )

        print_ranked_results(
            (
                "UNLINKED - PRACTICAL "
                f"(estimate rate >= "
                f"{MIN_PRACTICAL_ESTIMATE_RATE:g}%)"
            ),
            unlinked_results,
            minimum_rate=
                MIN_PRACTICAL_ESTIMATE_RATE,
        )

        current_config = {
            "type":
                "EVIDENCE_MEDIAN",

            "threshold":
                40.0,

            "support":
                2,

            "label":
                "CURRENT ev>=40 sup>=2",
        }

        print()
        print("=" * 125)
        print(
            "CURRENT CONFIGURATION"
        )
        print("-" * 125)

        current_all = (
            calculate_metrics(
                all_cases,
                current_config,
            )
        )

        current_meal = (
            calculate_metrics(
                meal_cases,
                current_config,
            )
        )

        current_unlinked = (
            calculate_metrics(
                unlinked_cases,
                current_config,
            )
        )

        print(
            "ALL"
        )

        print_result(
            1,
            {
                "config":
                    current_config,
                **current_all,
            },
        )

        print()
        print(
            "MEAL_LINKED"
        )

        print_result(
            1,
            {
                "config":
                    current_config,
                **current_meal,
            },
        )

        print()
        print(
            "UNLINKED"
        )

        print_result(
            1,
            {
                "config":
                    current_config,
                **current_unlinked,
            },
        )

        print()
        print("=" * 125)
        print(
            "HOW TO READ THIS"
        )
        print("-" * 125)

        print(
            "Lower MAE is better."
        )

        print(
            "Higher estimate rate means "
            "fewer ABSTAIN decisions."
        )

        print(
            "For first shadow testing we prefer "
            "accuracy over coverage."
        )

        print(
            "A very low MAE based on only a few "
            "cases should NOT automatically win."
        )

        print(
            "MEAL_LINKED and UNLINKED are "
            "evaluated separately because their "
            "error profiles are very different."
        )

        print()
        print(
            "RESEARCH / RETROSPECTIVE "
            "EVALUATION ONLY."
        )

        print(
            "No current insulin dose is "
            "calculated or recommended."
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 125)

    finally:
        db.close()


if __name__ == "__main__":
    main()