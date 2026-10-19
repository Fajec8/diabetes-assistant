from collections import Counter
from datetime import timedelta
from math import ceil, floor

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.services.batch_evaluation import (
    evaluate_batch,
)
from scripts.seed_validation_sets import (
    DATASETS,
    HOLDOUT_DAYS,
    TOTAL_DAYS,
    WARMUP_DAYS,
    _build_day_parameters,
)


TEST_USER_EMAIL = (
    "test@example.com"
)

K_VALUES = [
    3,
    5,
    10,
    20
]


# ---------------------------------------------------------
# ADAPTIVE K V2 - PARAMETER SEARCH
#
# Princip:
#
# - default = K10
# - na mensi K jdeme pouze pokud je
#   dalsi skupina kandidatu vyrazne horsi
# - na K20 jdeme pouze pokud dalsich
#   10 kandidatu zustava velmi podobnych
# - nizsi coverage NEVYNUCUJE K20
#
# Toto je pouze development/tuning skript.
# ---------------------------------------------------------

SHRINK_TO_5_THRESHOLDS = [
    1.5,
    2.0,
    2.5,
    3.0,
    3.5,
    4.0,
    4.5
]

SHRINK_TO_3_THRESHOLDS = [
    1.5,
    2.0,
    2.5,
    3.0,
    3.5,
    4.0,
    4.5
]

EXPAND_TO_20_THRESHOLDS = [
    0.25,
    0.50,
    0.75,
    1.00,
    1.25,
    1.50
]

SHRINK_COVERAGE_MIN_VALUES = [
    95.0,
    98.0,
    99.0,
    100.0
]


def _format_number(
    value
):
    if value is None:
        return "-"

    return f"{value:.3f}"


def _format_percent(
    value
):
    if value is None:
        return "-"

    return f"{value:.1f}%"


def _mean(
    values
):
    available = [
        value
        for value in values
        if value is not None
    ]

    if not available:
        return None

    return (
        sum(available)
        / len(available)
    )


def _rounded_mean(
    values
):
    value = (
        _mean(
            values
        )
    )

    if value is None:
        return None

    return round(
        value,
        3
    )


def _median(
    values
):
    available = sorted(
        value
        for value in values
        if value is not None
    )

    if not available:
        return None

    count = len(
        available
    )

    middle = (
        count // 2
    )

    if (
        count % 2
        == 1
    ):
        result = (
            available[
                middle
            ]
        )

    else:
        result = (
            (
                available[
                    middle - 1
                ]
                + available[
                    middle
                ]
            )
            / 2
        )

    return round(
        result,
        3
    )


def _percentile(
    values,
    percentile
):
    available = sorted(
        value
        for value in values
        if value is not None
    )

    if not available:
        return None

    if (
        len(available)
        == 1
    ):
        return round(
            available[0],
            3
        )

    position = (
        (
            len(available)
            - 1
        )
        * percentile
        / 100
    )

    lower_index = floor(
        position
    )

    upper_index = ceil(
        position
    )

    if (
        lower_index
        == upper_index
    ):
        result = (
            available[
                lower_index
            ]
        )

    else:
        fraction = (
            position
            - lower_index
        )

        result = (
            available[
                lower_index
            ]
            + (
                available[
                    upper_index
                ]
                - available[
                    lower_index
                ]
            )
            * fraction
        )

    return round(
        result,
        3
    )


def _statistics(
    values
):
    available = [
        value
        for value in values
        if value is not None
    ]

    if not available:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p90": None,
            "p95": None,
            "maximum": None
        }

    return {
        "count":
            len(
                available
            ),

        "mean":
            _rounded_mean(
                available
            ),

        "median":
            _median(
                available
            ),

        "p90":
            _percentile(
                available,
                90
            ),

        "p95":
            _percentile(
                available,
                95
            ),

        "maximum":
            round(
                max(
                    available
                ),
                3
            )
    }


def _find_k_result(
    evaluation,
    k
):
    for item in evaluation.get(
        "results",
        []
    ):
        if (
            item.get(
                "k_requested"
            )
            == k
        ):
            return item

    return None


def _build_exact_holdout_times(
    dataset
):
    evaluation_times = []

    previous_activity_minutes = 0

    for day_index in range(
        TOTAL_DAYS
    ):
        parameters = (
            _build_day_parameters(
                dataset=
                    dataset,

                day_index=
                    day_index,

                previous_activity_minutes=
                    previous_activity_minutes
            )
        )

        base_t0 = (
            dataset[
                "start"
            ]
            + timedelta(
                days=
                    day_index
            )
        )

        t0 = (
            base_t0
            + timedelta(
                minutes=
                    parameters[
                        "time_offset"
                    ]
            )
        )

        if (
            day_index
            >= WARMUP_DAYS
        ):
            evaluation_times.append(
                t0
            )

        if (
            parameters[
                "has_activity"
            ]
        ):
            previous_activity_minutes = (
                parameters[
                    "activity_duration"
                ]
            )

        else:
            previous_activity_minutes = 0

    return evaluation_times


def _added_group_average(
    lower_k,
    lower_average,
    upper_k,
    upper_average
):
    if (
        lower_average is None
        or upper_average is None
    ):
        return None

    added_count = (
        upper_k
        - lower_k
    )

    if (
        added_count
        <= 0
    ):
        return None

    total_upper = (
        upper_average
        * upper_k
    )

    total_lower = (
        lower_average
        * lower_k
    )

    return (
        (
            total_upper
            - total_lower
        )
        / added_count
    )


def _ranking_drop(
    evaluation,
    lower_k,
    upper_k
):
    lower_result = (
        _find_k_result(
            evaluation,
            lower_k
        )
    )

    upper_result = (
        _find_k_result(
            evaluation,
            upper_k
        )
    )

    if (
        lower_result is None
        or upper_result is None
    ):
        return None

    lower_average = (
        lower_result.get(
            "average_ranking_score"
        )
    )

    upper_average = (
        upper_result.get(
            "average_ranking_score"
        )
    )

    added_average = (
        _added_group_average(
            lower_k=
                lower_k,

            lower_average=
                lower_average,

            upper_k=
                upper_k,

            upper_average=
                upper_average
        )
    )

    if (
        lower_average is None
        or added_average is None
    ):
        return None

    return (
        lower_average
        - added_average
    )


def _top3_coverage(
    evaluation
):
    result = (
        _find_k_result(
            evaluation,
            3
        )
    )

    if result is None:
        return None

    return result.get(
        "average_data_coverage"
    )


def _select_k_v2(
    evaluation,
    parameters
):
    drop_3_to_5 = (
        _ranking_drop(
            evaluation=
                evaluation,

            lower_k=3,
            upper_k=5
        )
    )

    drop_5_to_10 = (
        _ranking_drop(
            evaluation=
                evaluation,

            lower_k=5,
            upper_k=10
        )
    )

    drop_10_to_20 = (
        _ranking_drop(
            evaluation=
                evaluation,

            lower_k=10,
            upper_k=20
        )
    )

    coverage = (
        _top3_coverage(
            evaluation
        )
    )

    selected_k = 10
    reason = "DEFAULT_K10"

    # -----------------------------------------------------
    # Mensi K dovolime pouze pri dostatecne
    # kvalitnich datech.
    #
    # To je opacny princip oproti v1:
    # horsi coverage nas uz neposila automaticky
    # k velkemu K.
    # -----------------------------------------------------

    can_shrink = (
        coverage is not None
        and coverage
        >= parameters[
            "shrink_coverage_min"
        ]
    )

    if (
        can_shrink
        and drop_5_to_10
        is not None
        and drop_5_to_10
        >= parameters[
            "shrink_to_5_threshold"
        ]
    ):
        selected_k = 5
        reason = "STRONG_DROP_AFTER_K5"

        if (
            drop_3_to_5
            is not None
            and drop_3_to_5
            >= parameters[
                "shrink_to_3_threshold"
            ]
        ):
            selected_k = 3
            reason = "STRONG_DROP_AFTER_K3"

    # -----------------------------------------------------
    # K20 pouzijeme pouze pokud jsme zustali
    # na defaultnim K10 a kandidati 11-20
    # maji velmi podobnou ranking kvalitu.
    # -----------------------------------------------------

    if (
        selected_k
        == 10
        and drop_10_to_20
        is not None
        and drop_10_to_20
        <= parameters[
            "expand_to_20_threshold"
        ]
    ):
        selected_k = 20
        reason = "FLAT_RANKING_TO_K20"

    return {
        "selected_k":
            selected_k,

        "reason":
            reason,

        "top3_coverage":
            coverage,

        "drop_3_to_5":
            drop_3_to_5,

        "drop_5_to_10":
            drop_5_to_10,

        "drop_10_to_20":
            drop_10_to_20
    }


def _selected_error(
    evaluation,
    selected_k
):
    result = (
        _find_k_result(
            evaluation,
            selected_k
        )
    )

    if result is None:
        return None

    return result.get(
        "mae_median"
    )


def _k10_error(
    evaluation
):
    return (
        _selected_error(
            evaluation=
                evaluation,

            selected_k=10
        )
    )


def _evaluate_parameters(
    evaluations,
    parameters
):
    errors = []

    selections = Counter()

    reasons = Counter()

    for evaluation in evaluations:
        selection = (
            _select_k_v2(
                evaluation=
                    evaluation,

                parameters=
                    parameters
            )
        )

        selected_k = (
            selection[
                "selected_k"
            ]
        )

        error = (
            _selected_error(
                evaluation=
                    evaluation,

                selected_k=
                    selected_k
            )
        )

        if error is None:
            continue

        errors.append(
            error
        )

        selections[
            selected_k
        ] += 1

        reasons[
            selection[
                "reason"
            ]
        ] += 1

    statistics = (
        _statistics(
            errors
        )
    )

    return {
        "statistics":
            statistics,

        "selections":
            selections,

        "reasons":
            reasons
    }


def _parameter_grid():
    for shrink_to_5 in (
        SHRINK_TO_5_THRESHOLDS
    ):
        for shrink_to_3 in (
            SHRINK_TO_3_THRESHOLDS
        ):
            for expand_to_20 in (
                EXPAND_TO_20_THRESHOLDS
            ):
                for coverage_min in (
                    SHRINK_COVERAGE_MIN_VALUES
                ):
                    yield {
                        "shrink_to_5_threshold":
                            shrink_to_5,

                        "shrink_to_3_threshold":
                            shrink_to_3,

                        "expand_to_20_threshold":
                            expand_to_20,

                        "shrink_coverage_min":
                            coverage_min
                    }


def _parameter_score(
    result
):
    stats = (
        result[
            "statistics"
        ]
    )

    mean_value = (
        stats[
            "mean"
        ]
    )

    p95_value = (
        stats[
            "p95"
        ]
    )

    maximum = (
        stats[
            "maximum"
        ]
    )

    if mean_value is None:
        return (
            float("inf"),
            float("inf"),
            float("inf")
        )

    return (
        mean_value,

        p95_value
        if p95_value is not None
        else float("inf"),

        maximum
        if maximum is not None
        else float("inf")
    )


def _tune_parameters(
    evaluations
):
    best_parameters = None
    best_result = None
    best_score = None

    for parameters in (
        _parameter_grid()
    ):
        result = (
            _evaluate_parameters(
                evaluations=
                    evaluations,

                parameters=
                    parameters
            )
        )

        score = (
            _parameter_score(
                result
            )
        )

        if (
            best_score is None
            or score
            < best_score
        ):
            best_score = (
                score
            )

            best_parameters = (
                parameters
            )

            best_result = (
                result
            )

    return {
        "parameters":
            best_parameters,

        "result":
            best_result
    }


def _fixed_k10_statistics(
    evaluations
):
    errors = [
        _k10_error(
            evaluation
        )
        for evaluation
        in evaluations
    ]

    return (
        _statistics(
            errors
        )
    )


def _compare_v2_with_k10(
    evaluations,
    parameters
):
    adaptive_wins = 0
    ties = 0
    k10_wins = 0

    differences = []

    for evaluation in evaluations:
        selection = (
            _select_k_v2(
                evaluation=
                    evaluation,

                parameters=
                    parameters
            )
        )

        adaptive_error = (
            _selected_error(
                evaluation=
                    evaluation,

                selected_k=
                    selection[
                        "selected_k"
                    ]
            )
        )

        fixed_error = (
            _k10_error(
                evaluation
            )
        )

        if (
            adaptive_error is None
            or fixed_error is None
        ):
            continue

        difference = (
            adaptive_error
            - fixed_error
        )

        differences.append(
            difference
        )

        if (
            adaptive_error
            < fixed_error
        ):
            adaptive_wins += 1

        elif (
            adaptive_error
            > fixed_error
        ):
            k10_wins += 1

        else:
            ties += 1

    count = (
        adaptive_wins
        + ties
        + k10_wins
    )

    non_worse = (
        adaptive_wins
        + ties
    )

    non_worse_percent = None

    if count:
        non_worse_percent = round(
            non_worse
            / count
            * 100,
            1
        )

    return {
        "count":
            count,

        "adaptive_wins":
            adaptive_wins,

        "ties":
            ties,

        "k10_wins":
            k10_wins,

        "non_worse_percent":
            non_worse_percent,

        "average_difference":
            _rounded_mean(
                differences
            )
    }


def _load_development_sets(
    db,
    user
):
    datasets = {}

    for dataset in DATASETS:
        evaluation_times = (
            _build_exact_holdout_times(
                dataset
            )
        )

        result = (
            evaluate_batch(
                db=db,
                user_id=user.id,
                evaluation_times=
                    evaluation_times,

                k_values=
                    K_VALUES
            )
        )

        datasets[
            dataset[
                "name"
            ]
        ] = (
            result[
                "evaluations"
            ]
        )

    return datasets


def _print_parameters(
    parameters
):
    print(
        "  shrink K10 -> K5:",
        parameters[
            "shrink_to_5_threshold"
        ]
    )

    print(
        "  shrink K5 -> K3:",
        parameters[
            "shrink_to_3_threshold"
        ]
    )

    print(
        "  expand K10 -> K20:",
        parameters[
            "expand_to_20_threshold"
        ]
    )

    print(
        "  min coverage pro shrink:",
        parameters[
            "shrink_coverage_min"
        ]
    )


def _print_selection_distribution(
    selections,
    count
):
    for k in K_VALUES:
        selected_count = (
            selections.get(
                k,
                0
            )
        )

        percent = None

        if count:
            percent = (
                selected_count
                / count
                * 100
            )

        print(
            f"    K={k:<2} "
            f"{selected_count:<4} "
            f"({_format_percent(percent)})"
        )


def _print_fold_result(
    held_out_name,
    tuning,
    holdout_evaluations
):
    parameters = (
        tuning[
            "parameters"
        ]
    )

    train_stats = (
        tuning[
            "result"
        ][
            "statistics"
        ]
    )

    holdout_result = (
        _evaluate_parameters(
            evaluations=
                holdout_evaluations,

            parameters=
                parameters
        )
    )

    holdout_stats = (
        holdout_result[
            "statistics"
        ]
    )

    k10_stats = (
        _fixed_k10_statistics(
            holdout_evaluations
        )
    )

    comparison = (
        _compare_v2_with_k10(
            evaluations=
                holdout_evaluations,

            parameters=
                parameters
        )
    )

    print()
    print(
        "=" * 108
    )

    print(
        "HELD-OUT DATASET:",
        held_out_name
    )

    print(
        "=" * 108
    )

    print(
        "Parametry vybrane pouze "
        "na ostatnich 3 datasetech:"
    )

    _print_parameters(
        parameters
    )

    print()

    print(
        "TRAIN AVG:",
        _format_number(
            train_stats[
                "mean"
            ]
        )
    )

    print()

    print(
        f"{'METHOD':<18}"
        f"{'AVG':<10}"
        f"{'MEDIAN':<10}"
        f"{'P90':<10}"
        f"{'P95':<10}"
        f"{'MAX':<10}"
    )

    print(
        "-" * 68
    )

    print(
        f"{'ADAPTIVE V2':<18}"
        f"{_format_number(holdout_stats['mean']):<10}"
        f"{_format_number(holdout_stats['median']):<10}"
        f"{_format_number(holdout_stats['p90']):<10}"
        f"{_format_number(holdout_stats['p95']):<10}"
        f"{_format_number(holdout_stats['maximum']):<10}"
    )

    print(
        f"{'FIXED K10':<18}"
        f"{_format_number(k10_stats['mean']):<10}"
        f"{_format_number(k10_stats['median']):<10}"
        f"{_format_number(k10_stats['p90']):<10}"
        f"{_format_number(k10_stats['p95']):<10}"
        f"{_format_number(k10_stats['maximum']):<10}"
    )

    print()

    print(
        "Vyber K na held-out datasetu:"
    )

    _print_selection_distribution(
        selections=
            holdout_result[
                "selections"
            ],

        count=
            holdout_stats[
                "count"
            ]
    )

    print()

    print(
        "Adaptive V2 vs K10:"
    )

    print(
        "  V2 vyhry:",
        comparison[
            "adaptive_wins"
        ]
    )

    print(
        "  remizy:",
        comparison[
            "ties"
        ]
    )

    print(
        "  K10 vyhry:",
        comparison[
            "k10_wins"
        ]
    )

    print(
        "  V2 neni horsi:",
        _format_percent(
            comparison[
                "non_worse_percent"
            ]
        )
    )

    print(
        "  prumerny rozdil "
        "(V2 - K10):",
        _format_number(
            comparison[
                "average_difference"
            ]
        )
    )

    return {
        "name":
            held_out_name,

        "parameters":
            parameters,

        "adaptive_errors":
            [
                _selected_error(
                    evaluation=
                        evaluation,

                    selected_k=
                        _select_k_v2(
                            evaluation=
                                evaluation,

                            parameters=
                                parameters
                        )[
                            "selected_k"
                        ]
                )
                for evaluation
                in holdout_evaluations
            ],

        "k10_errors":
            [
                _k10_error(
                    evaluation
                )
                for evaluation
                in holdout_evaluations
            ],

        "selections":
            holdout_result[
                "selections"
            ]
    }


def main():
    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(
                User.email
                == TEST_USER_EMAIL
            )
        )

        if user is None:
            print(
                "Testovaci uzivatel "
                "nebyl nalezen."
            )
            return

        print()
        print(
            "ADAPTIVE K V2 - "
            "LEAVE-ONE-DATASET-OUT TUNING"
        )

        print(
            "=" * 108
        )

        print(
            "Development datasety:",
            len(
                DATASETS
            )
        )

        print(
            "Situaci na dataset:",
            HOLDOUT_DAYS
        )

        print(
            "Celkem situaci:",
            len(
                DATASETS
            )
            * HOLDOUT_DAYS
        )

        print()

        print(
            "V2 pouziva K10 jako default."
        )

        print(
            "Coverage uz nevynucuje K20."
        )

        print(
            "Parametry se v kazdem foldu "
            "ladi pouze na ostatnich "
            "3 datasetech."
        )

        development_sets = (
            _load_development_sets(
                db=db,
                user=user
            )
        )

        fold_results = []

        for held_out_name in (
            development_sets.keys()
        ):
            train_evaluations = []

            for (
                dataset_name,
                evaluations
            ) in development_sets.items():
                if (
                    dataset_name
                    == held_out_name
                ):
                    continue

                train_evaluations.extend(
                    evaluations
                )

            tuning = (
                _tune_parameters(
                    train_evaluations
                )
            )

            fold_result = (
                _print_fold_result(
                    held_out_name=
                        held_out_name,

                    tuning=
                        tuning,

                    holdout_evaluations=
                        development_sets[
                            held_out_name
                        ]
                )
            )

            fold_results.append(
                fold_result
            )

        all_cv_adaptive_errors = []
        all_cv_k10_errors = []

        overall_selections = Counter()

        for result in fold_results:
            all_cv_adaptive_errors.extend(
                result[
                    "adaptive_errors"
                ]
            )

            all_cv_k10_errors.extend(
                result[
                    "k10_errors"
                ]
            )

            overall_selections.update(
                result[
                    "selections"
                ]
            )

        cv_adaptive_stats = (
            _statistics(
                all_cv_adaptive_errors
            )
        )

        cv_k10_stats = (
            _statistics(
                all_cv_k10_errors
            )
        )

        print()
        print(
            "=" * 108
        )

        print(
            "CROSS-VALIDATED VYSLEDEK "
            "NAPRIC 4 DATASETY"
        )

        print(
            "=" * 108
        )

        print(
            f"{'METHOD':<18}"
            f"{'AVG':<10}"
            f"{'MEDIAN':<10}"
            f"{'P90':<10}"
            f"{'P95':<10}"
            f"{'MAX':<10}"
        )

        print(
            "-" * 68
        )

        print(
            f"{'ADAPTIVE V2':<18}"
            f"{_format_number(cv_adaptive_stats['mean']):<10}"
            f"{_format_number(cv_adaptive_stats['median']):<10}"
            f"{_format_number(cv_adaptive_stats['p90']):<10}"
            f"{_format_number(cv_adaptive_stats['p95']):<10}"
            f"{_format_number(cv_adaptive_stats['maximum']):<10}"
        )

        print(
            f"{'FIXED K10':<18}"
            f"{_format_number(cv_k10_stats['mean']):<10}"
            f"{_format_number(cv_k10_stats['median']):<10}"
            f"{_format_number(cv_k10_stats['p90']):<10}"
            f"{_format_number(cv_k10_stats['p95']):<10}"
            f"{_format_number(cv_k10_stats['maximum']):<10}"
        )

        print()

        print(
            "Cross-validated vyber K:"
        )

        _print_selection_distribution(
            selections=
                overall_selections,

            count=
                cv_adaptive_stats[
                    "count"
                ]
        )

        all_evaluations = []

        for evaluations in (
            development_sets.values()
        ):
            all_evaluations.extend(
                evaluations
            )

        final_tuning = (
            _tune_parameters(
                all_evaluations
            )
        )

        final_parameters = (
            final_tuning[
                "parameters"
            ]
        )

        final_result = (
            final_tuning[
                "result"
            ]
        )

        print()
        print(
            "=" * 108
        )

        print(
            "FINALNI KANDIDAT PARAMETRU "
            "ADAPTIVE K V2"
        )

        print(
            "=" * 108
        )

        print(
            "Tyto parametry jsou naladene "
            "na vsech 240 development-v2 "
            "situacich."
        )

        print(
            "Pokud je prijmeme, dalsi krok "
            "uz musi byt novy nezavisly "
            "final holdout."
        )

        print()

        _print_parameters(
            final_parameters
        )

        print()

        print(
            "Development-v2 AVG:",
            _format_number(
                final_result[
                    "statistics"
                ][
                    "mean"
                ]
            )
        )

        print(
            "Development-v2 P95:",
            _format_number(
                final_result[
                    "statistics"
                ][
                    "p95"
                ]
            )
        )

        print()

        print(
            "Vyber K:"
        )

        _print_selection_distribution(
            selections=
                final_result[
                    "selections"
                ],

            count=
                final_result[
                    "statistics"
                ][
                    "count"
                ]
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()