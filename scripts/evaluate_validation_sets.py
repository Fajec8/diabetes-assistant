from collections import Counter
from datetime import timedelta
from math import ceil, floor, sqrt

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.services.batch_evaluation import (
    aggregate_batch_results,
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
    20,
    30
]

ADAPTIVE_K_VALUES = [
    3,
    5,
    10,
    20
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


def _available_values(
    values
):
    return [
        value
        for value in values
        if value is not None
    ]


def _mean(
    values
):
    available = (
        _available_values(
            values
        )
    )

    if not available:
        return None

    return round(
        sum(available)
        / len(available),
        3
    )


def _median(
    values
):
    available = sorted(
        _available_values(
            values
        )
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


def _standard_deviation(
    values
):
    available = (
        _available_values(
            values
        )
    )

    if not available:
        return None

    mean_value = (
        sum(available)
        / len(available)
    )

    variance = (
        sum(
            (
                value
                - mean_value
            ) ** 2
            for value
            in available
        )
        / len(available)
    )

    return round(
        sqrt(
            variance
        ),
        3
    )


def _percentile(
    values,
    percentile
):
    available = sorted(
        _available_values(
            values
        )
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


def _maximum(
    values
):
    available = (
        _available_values(
            values
        )
    )

    if not available:
        return None

    return round(
        max(
            available
        ),
        3
    )


def _statistics(
    values
):
    return {
        "mean":
            _mean(
                values
            ),

        "median":
            _median(
                values
            ),

        "standard_deviation":
            _standard_deviation(
                values
            ),

        "p90":
            _percentile(
                values,
                90
            ),

        "p95":
            _percentile(
                values,
                95
            ),

        "maximum":
            _maximum(
                values
            )
    }


def _format_k_values(
    values
):
    if not values:
        return "-"

    return "/".join(
        str(value)
        for value
        in values
    )


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


def _find_aggregate_k(
    aggregate_results,
    k
):
    for item in aggregate_results:
        if (
            item.get(
                "k"
            )
            == k
        ):
            return item

    return None


def _best_k_values(
    results,
    value_getter
):
    available = []

    for item in results:
        value = (
            value_getter(
                item
            )
        )

        if value is None:
            continue

        available.append(
            (
                item["k"],
                value
            )
        )

    if not available:
        return []

    best_value = min(
        value
        for _,
        value
        in available
    )

    return [
        k
        for k,
        value
        in available
        if value == best_value
    ]


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


def _fixed_errors(
    evaluation
):
    errors = {}

    for k in ADAPTIVE_K_VALUES:
        result = (
            _find_k_result(
                evaluation,
                k
            )
        )

        if result is None:
            continue

        error = (
            result.get(
                "mae_median"
            )
        )

        if error is None:
            continue

        errors[
            k
        ] = error

    return errors


def _best_fixed_information(
    evaluation
):
    errors = (
        _fixed_errors(
            evaluation
        )
    )

    if not errors:
        return None

    best_error = min(
        errors.values()
    )

    best_k_values = [
        k
        for k,
        error
        in errors.items()
        if error == best_error
    ]

    # Pro confusion matrix potrebujeme
    # presne jeden sloupec.
    #
    # Pri remize zvolime nejmensi K,
    # protoze jde o jednodussi variantu
    # se stejnou chybou.
    canonical_best_k = min(
        best_k_values
    )

    return {
        "errors":
            errors,

        "best_error":
            best_error,

        "best_k_values":
            best_k_values,

        "canonical_best_k":
            canonical_best_k
    }


def _ranking_only_selected_k(
    adaptive
):
    if adaptive is None:
        return None

    selection = (
        adaptive.get(
            "selection",
            {}
        )
    )

    selected_k = 3

    for step in selection.get(
        "expansion_steps",
        []
    ):
        if not step.get(
            "accepted"
        ):
            break

        selected_k = (
            step[
                "to_k"
            ]
        )

    return selected_k


def _build_adaptive_summary(
    evaluations
):
    adaptive_maes = []

    selected_k_counter = Counter()

    coverage_override_counter = Counter()

    expansion_attempts = Counter()
    expansion_accepts = Counter()
    expansion_rejections = Counter()

    valid_count = 0

    for evaluation in evaluations:
        adaptive = (
            evaluation.get(
                "adaptive"
            )
        )

        if adaptive is None:
            continue

        valid_count += 1

        selected_k = (
            adaptive.get(
                "selected_k"
            )
        )

        selected_k_counter[
            selected_k
        ] += 1

        adaptive_maes.append(
            adaptive.get(
                "mae_median"
            )
        )

        selection = (
            adaptive.get(
                "selection",
                {}
            )
        )

        coverage_override = (
            selection.get(
                "coverage_override"
            )
        )

        if coverage_override:
            reason = (
                coverage_override.get(
                    "reason",
                    "UNKNOWN"
                )
            )

            coverage_override_counter[
                reason
            ] += 1

        for step in selection.get(
            "expansion_steps",
            []
        ):
            step_name = (
                f"{step['from_k']}"
                f"->{step['to_k']}"
            )

            expansion_attempts[
                step_name
            ] += 1

            if step.get(
                "accepted"
            ):
                expansion_accepts[
                    step_name
                ] += 1

            else:
                expansion_rejections[
                    step_name
                ] += 1

    return {
        "count":
            valid_count,

        "statistics":
            _statistics(
                adaptive_maes
            ),

        "selected_k":
            selected_k_counter,

        "coverage_overrides":
            coverage_override_counter,

        "expansion_attempts":
            expansion_attempts,

        "expansion_accepts":
            expansion_accepts,

        "expansion_rejections":
            expansion_rejections
    }


def _compare_adaptive_with_fixed(
    evaluations,
    fixed_k
):
    adaptive_wins = 0
    ties = 0
    fixed_wins = 0

    differences = []

    comparison_count = 0

    for evaluation in evaluations:
        adaptive = (
            evaluation.get(
                "adaptive"
            )
        )

        fixed = (
            _find_k_result(
                evaluation,
                fixed_k
            )
        )

        if (
            adaptive is None
            or fixed is None
        ):
            continue

        adaptive_mae = (
            adaptive.get(
                "mae_median"
            )
        )

        fixed_mae = (
            fixed.get(
                "mae_median"
            )
        )

        if (
            adaptive_mae is None
            or fixed_mae is None
        ):
            continue

        comparison_count += 1

        difference = (
            adaptive_mae
            - fixed_mae
        )

        differences.append(
            difference
        )

        if (
            adaptive_mae
            < fixed_mae
        ):
            adaptive_wins += 1

        elif (
            adaptive_mae
            > fixed_mae
        ):
            fixed_wins += 1

        else:
            ties += 1

    non_worse_count = (
        adaptive_wins
        + ties
    )

    non_worse_percent = None

    if comparison_count:
        non_worse_percent = round(
            non_worse_count
            / comparison_count
            * 100,
            1
        )

    return {
        "count":
            comparison_count,

        "adaptive_wins":
            adaptive_wins,

        "ties":
            ties,

        "fixed_wins":
            fixed_wins,

        "non_worse_percent":
            non_worse_percent,

        "average_mae_difference":
            _mean(
                differences
            )
    }


def _build_selected_k_diagnostics(
    evaluations
):
    diagnostics = {}

    for k in ADAPTIVE_K_VALUES:
        diagnostics[
            k
        ] = {
            "count":
                0,

            "errors":
                [],

            "regrets":
                [],

            "optimal_count":
                0,

            "canonical_best":
                Counter()
        }

    for evaluation in evaluations:
        adaptive = (
            evaluation.get(
                "adaptive"
            )
        )

        if adaptive is None:
            continue

        selected_k = (
            adaptive.get(
                "selected_k"
            )
        )

        adaptive_error = (
            adaptive.get(
                "mae_median"
            )
        )

        best_info = (
            _best_fixed_information(
                evaluation
            )
        )

        if (
            selected_k
            not in diagnostics
            or adaptive_error is None
            or best_info is None
        ):
            continue

        group = (
            diagnostics[
                selected_k
            ]
        )

        group[
            "count"
        ] += 1

        group[
            "errors"
        ].append(
            adaptive_error
        )

        regret = round(
            adaptive_error
            - best_info[
                "best_error"
            ],
            3
        )

        group[
            "regrets"
        ].append(
            regret
        )

        if (
            selected_k
            in best_info[
                "best_k_values"
            ]
        ):
            group[
                "optimal_count"
            ] += 1

        group[
            "canonical_best"
        ][
            best_info[
                "canonical_best_k"
            ]
        ] += 1

    return diagnostics


def _build_overall_regret_summary(
    evaluations
):
    regrets = []

    optimal_count = 0
    count = 0

    oracle_errors = []
    adaptive_errors = []

    for evaluation in evaluations:
        adaptive = (
            evaluation.get(
                "adaptive"
            )
        )

        if adaptive is None:
            continue

        adaptive_error = (
            adaptive.get(
                "mae_median"
            )
        )

        best_info = (
            _best_fixed_information(
                evaluation
            )
        )

        if (
            adaptive_error is None
            or best_info is None
        ):
            continue

        count += 1

        adaptive_errors.append(
            adaptive_error
        )

        oracle_errors.append(
            best_info[
                "best_error"
            ]
        )

        regret = round(
            adaptive_error
            - best_info[
                "best_error"
            ],
            3
        )

        regrets.append(
            regret
        )

        if (
            adaptive.get(
                "selected_k"
            )
            in best_info[
                "best_k_values"
            ]
        ):
            optimal_count += 1

    optimal_percent = None

    if count:
        optimal_percent = round(
            optimal_count
            / count
            * 100,
            1
        )

    return {
        "count":
            count,

        "optimal_count":
            optimal_count,

        "optimal_percent":
            optimal_percent,

        "adaptive_mean":
            _mean(
                adaptive_errors
            ),

        "oracle_mean":
            _mean(
                oracle_errors
            ),

        "regret_statistics":
            _statistics(
                regrets
            )
    }


def _build_coverage_override_diagnostics(
    evaluations
):
    groups = {
        "NO_OVERRIDE": {
            "count": 0,
            "adaptive_errors": [],
            "ranking_only_errors": [],
            "k10_errors": [],
            "regrets": [],
            "override_better": 0,
            "override_ties": 0,
            "override_worse": 0,
            "transitions": Counter()
        },

        "MEDIUM_TOP3_COVERAGE": {
            "count": 0,
            "adaptive_errors": [],
            "ranking_only_errors": [],
            "k10_errors": [],
            "regrets": [],
            "override_better": 0,
            "override_ties": 0,
            "override_worse": 0,
            "transitions": Counter()
        },

        "LOW_TOP3_COVERAGE": {
            "count": 0,
            "adaptive_errors": [],
            "ranking_only_errors": [],
            "k10_errors": [],
            "regrets": [],
            "override_better": 0,
            "override_ties": 0,
            "override_worse": 0,
            "transitions": Counter()
        }
    }

    for evaluation in evaluations:
        adaptive = (
            evaluation.get(
                "adaptive"
            )
        )

        if adaptive is None:
            continue

        selection = (
            adaptive.get(
                "selection",
                {}
            )
        )

        override = (
            selection.get(
                "coverage_override"
            )
        )

        if override:
            group_name = (
                override.get(
                    "reason",
                    "NO_OVERRIDE"
                )
            )

        else:
            group_name = (
                "NO_OVERRIDE"
            )

        if (
            group_name
            not in groups
        ):
            continue

        group = (
            groups[
                group_name
            ]
        )

        adaptive_k = (
            adaptive.get(
                "selected_k"
            )
        )

        adaptive_error = (
            adaptive.get(
                "mae_median"
            )
        )

        ranking_only_k = (
            _ranking_only_selected_k(
                adaptive
            )
        )

        ranking_only_result = (
            _find_k_result(
                evaluation,
                ranking_only_k
            )
            if ranking_only_k
            is not None
            else None
        )

        k10_result = (
            _find_k_result(
                evaluation,
                10
            )
        )

        best_info = (
            _best_fixed_information(
                evaluation
            )
        )

        if (
            adaptive_error is None
            or best_info is None
        ):
            continue

        group[
            "count"
        ] += 1

        group[
            "adaptive_errors"
        ].append(
            adaptive_error
        )

        regret = round(
            adaptive_error
            - best_info[
                "best_error"
            ],
            3
        )

        group[
            "regrets"
        ].append(
            regret
        )

        if (
            ranking_only_result
            is not None
        ):
            ranking_only_error = (
                ranking_only_result.get(
                    "mae_median"
                )
            )

            group[
                "ranking_only_errors"
            ].append(
                ranking_only_error
            )

            if (
                ranking_only_error
                is not None
            ):
                if (
                    adaptive_error
                    < ranking_only_error
                ):
                    group[
                        "override_better"
                    ] += 1

                elif (
                    adaptive_error
                    > ranking_only_error
                ):
                    group[
                        "override_worse"
                    ] += 1

                else:
                    group[
                        "override_ties"
                    ] += 1

        if k10_result is not None:
            group[
                "k10_errors"
            ].append(
                k10_result.get(
                    "mae_median"
                )
            )

        if (
            ranking_only_k
            is not None
            and adaptive_k
            is not None
        ):
            transition = (
                f"K{ranking_only_k}"
                f"->K{adaptive_k}"
            )

            group[
                "transitions"
            ][
                transition
            ] += 1

    return groups


def _print_fixed_result(
    aggregate_results
):
    print()

    print(
        f"{'K':<6}"
        f"{'AVG':<10}"
        f"{'MEDIAN':<10}"
        f"{'STD':<10}"
        f"{'P90':<10}"
        f"{'P95':<10}"
        f"{'MAX':<10}"
        f"{'WINS':<8}"
        f"{'AVG RANK':<12}"
    )

    print(
        "-" * 104
    )

    for item in aggregate_results:
        stats = (
            item[
                "median_method"
            ]
        )

        print(
            f"{item['k']:<6}"
            f"{_format_number(stats['mean_mae']):<10}"
            f"{_format_number(stats['median_mae']):<10}"
            f"{_format_number(stats['standard_deviation']):<10}"
            f"{_format_number(stats['p90']):<10}"
            f"{_format_number(stats['p95']):<10}"
            f"{_format_number(stats['maximum']):<10}"
            f"{stats['win_count']:<8}"
            f"{_format_number(item['average_ranking_score']):<12}"
        )


def _print_adaptive_result(
    adaptive_summary,
    comparison
):
    stats = (
        adaptive_summary[
            "statistics"
        ]
    )

    print()
    print(
        "ADAPTIVE K V1"
    )

    print(
        "-" * 104
    )

    print(
        f"{'COUNT':<8}"
        f"{'AVG':<10}"
        f"{'MEDIAN':<10}"
        f"{'STD':<10}"
        f"{'P90':<10}"
        f"{'P95':<10}"
        f"{'MAX':<10}"
    )

    print(
        f"{adaptive_summary['count']:<8}"
        f"{_format_number(stats['mean']):<10}"
        f"{_format_number(stats['median']):<10}"
        f"{_format_number(stats['standard_deviation']):<10}"
        f"{_format_number(stats['p90']):<10}"
        f"{_format_number(stats['p95']):<10}"
        f"{_format_number(stats['maximum']):<10}"
    )

    print()

    print(
        "Vyber K:"
    )

    for k in ADAPTIVE_K_VALUES:
        count = (
            adaptive_summary[
                "selected_k"
            ].get(
                k,
                0
            )
        )

        percent = None

        if (
            adaptive_summary[
                "count"
            ]
            > 0
        ):
            percent = (
                count
                / adaptive_summary[
                    "count"
                ]
                * 100
            )

        print(
            f"  K={k:<2} "
            f"{count:<4} "
            f"({_format_percent(percent)})"
        )

    print()

    print(
        "Adaptive vs fixed K=10:"
    )

    print(
        "  adaptive vyhry:",
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
        "  fixed K10 vyhry:",
        comparison[
            "fixed_wins"
        ]
    )

    print(
        "  adaptive neni horsi:",
        _format_percent(
            comparison[
                "non_worse_percent"
            ]
        )
    )

    print(
        "  prumerny rozdil MAE "
        "(adaptive - K10):",
        _format_number(
            comparison[
                "average_mae_difference"
            ]
        )
    )


def _print_adaptive_diagnostics(
    adaptive_summary
):
    print()
    print(
        "Adaptive diagnostika:"
    )

    print(
        "  Coverage overrides:"
    )

    if (
        adaptive_summary[
            "coverage_overrides"
        ]
    ):
        for (
            reason,
            count
        ) in adaptive_summary[
            "coverage_overrides"
        ].items():
            print(
                f"    {reason}: "
                f"{count}"
            )

    else:
        print(
            "    zadne"
        )

    print()

    print(
        "  Ranking expansion:"
    )

    for step in [
        "3->5",
        "5->10",
        "10->20"
    ]:
        attempts = (
            adaptive_summary[
                "expansion_attempts"
            ].get(
                step,
                0
            )
        )

        accepts = (
            adaptive_summary[
                "expansion_accepts"
            ].get(
                step,
                0
            )
        )

        rejects = (
            adaptive_summary[
                "expansion_rejections"
            ].get(
                step,
                0
            )
        )

        print(
            f"    {step}: "
            f"pokusy={attempts}, "
            f"prijato={accepts}, "
            f"odmitnuto={rejects}"
        )


def _print_selected_k_diagnostics(
    evaluations
):
    diagnostics = (
        _build_selected_k_diagnostics(
            evaluations
        )
    )

    print()
    print(
        "=" * 112
    )

    print(
        "DIAGNOSTIKA PODLE ADAPTIVE VYBRANEHO K"
    )

    print(
        "=" * 112
    )

    print(
        f"{'SELECTED':<12}"
        f"{'COUNT':<8}"
        f"{'AVG MAE':<12}"
        f"{'AVG REGRET':<14}"
        f"{'P95 REGRET':<14}"
        f"{'OPTIMAL':<10}"
        f"{'OPTIMAL %':<12}"
    )

    print(
        "-" * 112
    )

    for k in ADAPTIVE_K_VALUES:
        group = (
            diagnostics[
                k
            ]
        )

        count = (
            group[
                "count"
            ]
        )

        optimal_percent = None

        if count:
            optimal_percent = (
                group[
                    "optimal_count"
                ]
                / count
                * 100
            )

        error_stats = (
            _statistics(
                group[
                    "errors"
                ]
            )
        )

        regret_stats = (
            _statistics(
                group[
                    "regrets"
                ]
            )
        )

        print(
            f"{('K=' + str(k)):<12}"
            f"{count:<8}"
            f"{_format_number(error_stats['mean']):<12}"
            f"{_format_number(regret_stats['mean']):<14}"
            f"{_format_number(regret_stats['p95']):<14}"
            f"{group['optimal_count']:<10}"
            f"{_format_percent(optimal_percent):<12}"
        )


def _print_selection_matrix(
    evaluations
):
    diagnostics = (
        _build_selected_k_diagnostics(
            evaluations
        )
    )

    print()
    print(
        "=" * 92
    )

    print(
        "SELECTED K VS SKUTECNE NEJLEPSI K"
    )

    print(
        "=" * 92
    )

    print(
        "Pri remize nejlepsiho MAE "
        "se pro tuto matici pouzije "
        "nejmensi K."
    )

    print()

    print(
        f"{'SELECTED':<14}"
        f"{'BEST K3':<12}"
        f"{'BEST K5':<12}"
        f"{'BEST K10':<12}"
        f"{'BEST K20':<12}"
        f"{'TOTAL':<10}"
    )

    print(
        "-" * 92
    )

    for selected_k in ADAPTIVE_K_VALUES:
        group = (
            diagnostics[
                selected_k
            ]
        )

        matrix = (
            group[
                "canonical_best"
            ]
        )

        print(
            f"{('K=' + str(selected_k)):<14}"
            f"{matrix.get(3, 0):<12}"
            f"{matrix.get(5, 0):<12}"
            f"{matrix.get(10, 0):<12}"
            f"{matrix.get(20, 0):<12}"
            f"{group['count']:<10}"
        )


def _print_overall_regret(
    evaluations
):
    summary = (
        _build_overall_regret_summary(
            evaluations
        )
    )

    stats = (
        summary[
            "regret_statistics"
        ]
    )

    print()
    print(
        "=" * 104
    )

    print(
        "ADAPTIVE REGRET ANALYZA"
    )

    print(
        "=" * 104
    )

    print(
        "Oracle zde znamena nejlepsi "
        "z K=3/5/10/20 pro danou "
        "konkretni situaci."
    )

    print(
        "Oracle slouzi pouze pro "
        "zpetnou diagnostiku."
    )

    print()

    print(
        "Situaci:",
        summary[
            "count"
        ]
    )

    print(
        "Adaptive vybralo jedno z "
        "optimalnich K:",
        summary[
            "optimal_count"
        ],
        f"({_format_percent(summary['optimal_percent'])})"
    )

    print(
        "Adaptive prumerne MAE:",
        _format_number(
            summary[
                "adaptive_mean"
            ]
        )
    )

    print(
        "Oracle prumerne MAE:",
        _format_number(
            summary[
                "oracle_mean"
            ]
        )
    )

    print()

    print(
        f"{'REGRET AVG':<14}"
        f"{'MEDIAN':<12}"
        f"{'P90':<12}"
        f"{'P95':<12}"
        f"{'MAX':<12}"
    )

    print(
        "-" * 62
    )

    print(
        f"{_format_number(stats['mean']):<14}"
        f"{_format_number(stats['median']):<12}"
        f"{_format_number(stats['p90']):<12}"
        f"{_format_number(stats['p95']):<12}"
        f"{_format_number(stats['maximum']):<12}"
    )


def _print_coverage_diagnostics(
    evaluations
):
    groups = (
        _build_coverage_override_diagnostics(
            evaluations
        )
    )

    print()
    print(
        "=" * 124
    )

    print(
        "COVERAGE OVERRIDE DIAGNOSTIKA"
    )

    print(
        "=" * 124
    )

    print(
        f"{'GROUP':<26}"
        f"{'COUNT':<8}"
        f"{'ADAPT AVG':<12}"
        f"{'RANK-ONLY':<12}"
        f"{'K10 AVG':<12}"
        f"{'AVG REGRET':<14}"
        f"{'OVR +':<8}"
        f"{'TIE':<8}"
        f"{'OVR -':<8}"
    )

    print(
        "-" * 124
    )

    for group_name in [
        "NO_OVERRIDE",
        "MEDIUM_TOP3_COVERAGE",
        "LOW_TOP3_COVERAGE"
    ]:
        group = (
            groups[
                group_name
            ]
        )

        adaptive_avg = (
            _mean(
                group[
                    "adaptive_errors"
                ]
            )
        )

        ranking_only_avg = (
            _mean(
                group[
                    "ranking_only_errors"
                ]
            )
        )

        k10_avg = (
            _mean(
                group[
                    "k10_errors"
                ]
            )
        )

        regret_avg = (
            _mean(
                group[
                    "regrets"
                ]
            )
        )

        print(
            f"{group_name:<26}"
            f"{group['count']:<8}"
            f"{_format_number(adaptive_avg):<12}"
            f"{_format_number(ranking_only_avg):<12}"
            f"{_format_number(k10_avg):<12}"
            f"{_format_number(regret_avg):<14}"
            f"{group['override_better']:<8}"
            f"{group['override_ties']:<8}"
            f"{group['override_worse']:<8}"
        )

    print()
    print(
        "OVR + = coverage override zlepsil MAE"
    )

    print(
        "TIE   = coverage override nic nezmenil"
    )

    print(
        "OVR - = coverage override zhorsil MAE"
    )

    print()
    print(
        "Prechody z ranking-only K "
        "na finalni adaptive K:"
    )

    for group_name in [
        "MEDIUM_TOP3_COVERAGE",
        "LOW_TOP3_COVERAGE"
    ]:
        print()
        print(
            f"  {group_name}:"
        )

        transitions = (
            groups[
                group_name
            ][
                "transitions"
            ]
        )

        if not transitions:
            print(
                "    zadne"
            )

        else:
            for (
                transition,
                count
            ) in sorted(
                transitions.items()
            ):
                print(
                    f"    "
                    f"{transition}: "
                    f"{count}"
                )


def _print_dataset_result(
    dataset_name,
    result
):
    aggregate = (
        result[
            "aggregate"
        ]
    )

    aggregate_results = (
        aggregate[
            "results"
        ]
    )

    print()
    print(
        "=" * 104
    )

    print(
        dataset_name
    )

    print(
        "=" * 104
    )

    print(
        "Pozadovanych:",
        result[
            "requested_evaluation_count"
        ]
    )

    print(
        "Pouzitych:",
        result[
            "evaluated_count"
        ]
    )

    print(
        "Preskocenych:",
        result[
            "skipped_count"
        ]
    )

    _print_fixed_result(
        aggregate_results
    )

    best_average = (
        _best_k_values(
            aggregate_results,
            lambda item:
                item[
                    "median_method"
                ][
                    "mean_mae"
                ]
        )
    )

    print()

    print(
        "Nejlepsi fixed K podle AVG:",
        _format_k_values(
            best_average
        )
    )

    adaptive_summary = (
        _build_adaptive_summary(
            result[
                "evaluations"
            ]
        )
    )

    comparison = (
        _compare_adaptive_with_fixed(
            evaluations=
                result[
                    "evaluations"
                ],

            fixed_k=10
        )
    )

    _print_adaptive_result(
        adaptive_summary=
            adaptive_summary,

        comparison=
            comparison
    )

    return {
        "name":
            dataset_name,

        "aggregate_results":
            aggregate_results,

        "best_average":
            best_average,

        "adaptive_summary":
            adaptive_summary,

        "comparison":
            comparison
    }


def _print_cross_dataset_table(
    dataset_summaries,
    overall_results,
    overall_adaptive_summary
):
    print()
    print(
        "=" * 120
    )

    print(
        "POROVNANI NAPRIC DATASETY - "
        "PRUMERNE MEDIAN MAE"
    )

    print(
        "=" * 120
    )

    header = (
        f"{'METHOD':<14}"
    )

    for summary in dataset_summaries:
        header += (
            f"{summary['name']:<18}"
        )

    header += (
        f"{'OVERALL':<12}"
    )

    print(
        header
    )

    print(
        "-" * 120
    )

    for k in K_VALUES:
        line = (
            f"{('K=' + str(k)):<14}"
        )

        for summary in dataset_summaries:
            item = (
                _find_aggregate_k(
                    summary[
                        "aggregate_results"
                    ],
                    k
                )
            )

            value = None

            if item is not None:
                value = (
                    item[
                        "median_method"
                    ][
                        "mean_mae"
                    ]
                )

            line += (
                f"{_format_number(value):<18}"
            )

        overall_item = (
            _find_aggregate_k(
                overall_results,
                k
            )
        )

        overall_value = None

        if overall_item is not None:
            overall_value = (
                overall_item[
                    "median_method"
                ][
                    "mean_mae"
                ]
            )

        line += (
            f"{_format_number(overall_value):<12}"
        )

        print(
            line
        )

    adaptive_line = (
        f"{'ADAPTIVE':<14}"
    )

    for summary in dataset_summaries:
        adaptive_value = (
            summary[
                "adaptive_summary"
            ][
                "statistics"
            ][
                "mean"
            ]
        )

        adaptive_line += (
            f"{_format_number(adaptive_value):<18}"
        )

    adaptive_line += (
        f"{_format_number(overall_adaptive_summary['statistics']['mean']):<12}"
    )

    print(
        adaptive_line
    )


def _print_overall_fixed_result(
    aggregate
):
    results = (
        aggregate[
            "results"
        ]
    )

    print()
    print(
        "=" * 104
    )

    print(
        "CELKOVA FIXED K VALIDACE - "
        "240 DEVELOPMENT-V2 SITUACI"
    )

    print(
        "=" * 104
    )

    print(
        "Celkem situaci:",
        aggregate[
            "comparable_evaluation_count"
        ]
    )

    _print_fixed_result(
        results
    )

    best_average = (
        _best_k_values(
            results,
            lambda item:
                item[
                    "median_method"
                ][
                    "mean_mae"
                ]
        )
    )

    print()

    print(
        "Nejlepsi fixed K podle AVG:",
        _format_k_values(
            best_average
        )
    )


def _print_overall_adaptive(
    evaluations
):
    adaptive_summary = (
        _build_adaptive_summary(
            evaluations
        )
    )

    comparison = (
        _compare_adaptive_with_fixed(
            evaluations=
                evaluations,

            fixed_k=10
        )
    )

    print()
    print(
        "=" * 104
    )

    print(
        "CELKOVE ADAPTIVE K V1 - "
        "240 DEVELOPMENT-V2 SITUACI"
    )

    print(
        "=" * 104
    )

    _print_adaptive_result(
        adaptive_summary=
            adaptive_summary,

        comparison=
            comparison
    )

    _print_adaptive_diagnostics(
        adaptive_summary
    )

    return (
        adaptive_summary,
        comparison
    )


def _print_dataset_adaptive_comparison(
    dataset_summaries
):
    print()
    print(
        "=" * 118
    )

    print(
        "ADAPTIVE K V1 VS FIXED K10 "
        "PODLE DATASETU"
    )

    print(
        "=" * 118
    )

    print(
        f"{'DATASET':<20}"
        f"{'ADAPT AVG':<12}"
        f"{'K10 AVG':<12}"
        f"{'DELTA':<12}"
        f"{'A WINS':<10}"
        f"{'TIES':<8}"
        f"{'K10 WINS':<12}"
        f"{'NON-WORSE':<12}"
    )

    print(
        "-" * 118
    )

    for summary in dataset_summaries:
        adaptive_avg = (
            summary[
                "adaptive_summary"
            ][
                "statistics"
            ][
                "mean"
            ]
        )

        k10_item = (
            _find_aggregate_k(
                summary[
                    "aggregate_results"
                ],
                10
            )
        )

        k10_avg = None

        if k10_item is not None:
            k10_avg = (
                k10_item[
                    "median_method"
                ][
                    "mean_mae"
                ]
            )

        delta = None

        if (
            adaptive_avg is not None
            and k10_avg is not None
        ):
            delta = round(
                adaptive_avg
                - k10_avg,
                3
            )

        comparison = (
            summary[
                "comparison"
            ]
        )

        print(
            f"{summary['name']:<20}"
            f"{_format_number(adaptive_avg):<12}"
            f"{_format_number(k10_avg):<12}"
            f"{_format_number(delta):<12}"
            f"{comparison['adaptive_wins']:<10}"
            f"{comparison['ties']:<8}"
            f"{comparison['fixed_wins']:<12}"
            f"{_format_percent(comparison['non_worse_percent']):<12}"
        )


def _print_overall_horizon_table(
    aggregate
):
    results = (
        aggregate[
            "results"
        ]
    )

    print()
    print(
        "=" * 90
    )

    print(
        "OVERALL MAE PODLE HORIZONTU - "
        "FIXED K"
    )

    print(
        "=" * 90
    )

    print(
        f"{'K':<8}"
        f"{'30m':<14}"
        f"{'60m':<14}"
        f"{'90m':<14}"
        f"{'120m':<14}"
        f"{'180m':<14}"
    )

    print(
        "-" * 90
    )

    for item in results:
        horizons = (
            item[
                "horizons"
            ]
        )

        print(
            f"{item['k']:<8}"
            f"{_format_number(horizons['30m']['median_prediction']['mean']):<14}"
            f"{_format_number(horizons['60m']['median_prediction']['mean']):<14}"
            f"{_format_number(horizons['90m']['median_prediction']['mean']):<14}"
            f"{_format_number(horizons['120m']['median_prediction']['mean']):<14}"
            f"{_format_number(horizons['180m']['median_prediction']['mean']):<14}"
        )


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
            "MULTI-DATASET VALIDATION + "
            "ADAPTIVE K V1 DIAGNOSTICS"
        )

        print(
            "=" * 104
        )

        print(
            "Fixed K:",
            K_VALUES
        )

        print(
            "Adaptive mozne K:",
            ADAPTIVE_K_VALUES
        )

        print(
            "Pocet datasetu:",
            len(
                DATASETS
            )
        )

        print(
            "Holdout situaci na dataset:",
            HOLDOUT_DAYS
        )

        print(
            "Celkem development-v2 situaci:",
            len(
                DATASETS
            )
            * HOLDOUT_DAYS
        )

        all_evaluations = []

        dataset_summaries = []

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

            summary = (
                _print_dataset_result(
                    dataset_name=
                        dataset[
                            "name"
                        ],

                    result=
                        result
                )
            )

            dataset_summaries.append(
                summary
            )

            all_evaluations.extend(
                result[
                    "evaluations"
                ]
            )

            if (
                result[
                    "skipped"
                ]
            ):
                print()
                print(
                    "Preskocene situace:"
                )

                for skipped in result[
                    "skipped"
                ]:
                    print(
                        " ",
                        skipped
                    )

        overall = (
            aggregate_batch_results(
                evaluations=
                    all_evaluations,

                k_values=
                    K_VALUES
            )
        )

        overall_adaptive_summary = (
            _build_adaptive_summary(
                all_evaluations
            )
        )

        _print_cross_dataset_table(
            dataset_summaries=
                dataset_summaries,

            overall_results=
                overall[
                    "results"
                ],

            overall_adaptive_summary=
                overall_adaptive_summary
        )

        _print_overall_fixed_result(
            overall
        )

        _print_overall_adaptive(
            all_evaluations
        )

        _print_dataset_adaptive_comparison(
            dataset_summaries
        )

        _print_selected_k_diagnostics(
            all_evaluations
        )

        _print_selection_matrix(
            all_evaluations
        )

        _print_overall_regret(
            all_evaluations
        )

        _print_coverage_diagnostics(
            all_evaluations
        )

        _print_overall_horizon_table(
            overall
        )

        print()
        print(
            "=" * 104
        )

        print(
            "CO TED HLEDAME"
        )

        print(
            "=" * 104
        )

        print(
            "1. Jestli adaptive zastavuje "
            "prilis brzo na K3/K5."
        )

        print(
            "2. Jestli adaptive naopak "
            "prilis casto roztahuje K10 na K20."
        )

        print(
            "3. Jestli coverage override "
            "realne zlepsuje vysledky."
        )

        print(
            "4. Jak velky je regret proti "
            "nejlepsimu K dostupnemu zpetne."
        )

        print()

        print(
            "Thresholdy ani finalni pravidlo "
            "zatim nemenime."
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()