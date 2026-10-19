from math import floor, ceil, sqrt

from app.services.evaluation import (
    evaluate_k_values,
)
from app.services.situation_outcome import (
    build_situation_outcome,
)


DEFAULT_BATCH_K_VALUES = [
    3,
    5,
    10,
    20,
    30
]

HORIZONS = [
    30,
    60,
    90,
    120,
    180
]


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


def _is_comparable(
    evaluation,
    k_values
):
    actual_outcome = (
        evaluation.get(
            "actual_outcome",
            {}
        )
    )

    if (
        actual_outcome.get(
            "outcome_coverage"
        )
        != 100.0
    ):
        return False

    for k in k_values:
        result = (
            _find_k_result(
                evaluation,
                k
            )
        )

        if result is None:
            return False

        if (
            result.get(
                "k_found"
            )
            < k
        ):
            return False

    return True


def _count_wins(
    evaluations,
    k_values,
    target_k,
    metric_name
):
    wins = 0

    for evaluation in evaluations:
        values = []

        for k in k_values:
            result = (
                _find_k_result(
                    evaluation,
                    k
                )
            )

            if result is None:
                continue

            value = (
                result.get(
                    metric_name
                )
            )

            if value is None:
                continue

            values.append(
                (
                    k,
                    value
                )
            )

        if not values:
            continue

        best_value = min(
            value
            for _,
            value
            in values
        )

        target_result = (
            _find_k_result(
                evaluation,
                target_k
            )
        )

        if target_result is None:
            continue

        target_value = (
            target_result.get(
                metric_name
            )
        )

        if (
            target_value
            is not None
            and target_value
            == best_value
        ):
            wins += 1

    return wins


def _build_horizon_statistics(
    k_results
):
    horizons = {}

    for minutes in HORIZONS:
        horizon_key = (
            f"{minutes}m"
        )

        median_errors = []

        weighted_errors = []

        for item in k_results:
            horizon_result = (
                item
                .get(
                    "horizons",
                    {}
                )
                .get(
                    horizon_key,
                    {}
                )
            )

            median_errors.append(
                horizon_result.get(
                    "absolute_error_median"
                )
            )

            weighted_errors.append(
                horizon_result.get(
                    "absolute_error_weighted_mean"
                )
            )

        horizons[
            horizon_key
        ] = {
            "median_prediction":
                _statistics(
                    median_errors
                ),

            "weighted_mean_prediction":
                _statistics(
                    weighted_errors
                )
        }

    return horizons


def aggregate_batch_results(
    evaluations,
    k_values=None
):
    if k_values is None:
        k_values = (
            DEFAULT_BATCH_K_VALUES
        )

    k_values = list(
        k_values
    )

    comparable = [
        evaluation
        for evaluation
        in evaluations
        if (
            _is_comparable(
                evaluation,
                k_values
            )
        )
    ]

    aggregate_results = []

    for k in k_values:
        k_results = [
            _find_k_result(
                evaluation,
                k
            )
            for evaluation
            in comparable
        ]

        k_results = [
            item
            for item
            in k_results
            if item is not None
        ]

        median_maes = [
            item.get(
                "mae_median"
            )
            for item
            in k_results
        ]

        weighted_maes = [
            item.get(
                "mae_weighted_mean"
            )
            for item
            in k_results
        ]

        ranking_scores = [
            item.get(
                "average_ranking_score"
            )
            for item
            in k_results
        ]

        median_stats = (
            _statistics(
                median_maes
            )
        )

        weighted_stats = (
            _statistics(
                weighted_maes
            )
        )

        median_wins = (
            _count_wins(
                evaluations=
                    comparable,

                k_values=
                    k_values,

                target_k=
                    k,

                metric_name=
                    "mae_median"
            )
        )

        weighted_wins = (
            _count_wins(
                evaluations=
                    comparable,

                k_values=
                    k_values,

                target_k=
                    k,

                metric_name=
                    "mae_weighted_mean"
            )
        )

        evaluation_count = len(
            k_results
        )

        median_win_rate = None
        weighted_win_rate = None

        if (
            evaluation_count
            > 0
        ):
            median_win_rate = round(
                median_wins
                / evaluation_count
                * 100,
                1
            )

            weighted_win_rate = round(
                weighted_wins
                / evaluation_count
                * 100,
                1
            )

        aggregate_results.append({
            "k":
                k,

            "evaluation_count":
                evaluation_count,

            # Puvodni hodnoty nechavame,
            # aby zustala zachovana
            # zpetna kompatibilita.
            "average_mae_median":
                median_stats[
                    "mean"
                ],

            "average_mae_weighted_mean":
                weighted_stats[
                    "mean"
                ],

            "average_ranking_score":
                _mean(
                    ranking_scores
                ),

            # Rozsirene statistiky
            # pro predikci zalozenou
            # na medianu.
            "median_method": {
                "mean_mae":
                    median_stats[
                        "mean"
                    ],

                "median_mae":
                    median_stats[
                        "median"
                    ],

                "standard_deviation":
                    median_stats[
                        "standard_deviation"
                    ],

                "p90":
                    median_stats[
                        "p90"
                    ],

                "p95":
                    median_stats[
                        "p95"
                    ],

                "maximum":
                    median_stats[
                        "maximum"
                    ],

                # Pri shode muze byt
                # jedna evaluace zapocitana
                # jako vyhra vice hodnot K.
                "win_count":
                    median_wins,

                "win_rate_percent":
                    median_win_rate
            },

            # Stejne statistiky pro
            # weighted mean.
            "weighted_mean_method": {
                "mean_mae":
                    weighted_stats[
                        "mean"
                    ],

                "median_mae":
                    weighted_stats[
                        "median"
                    ],

                "standard_deviation":
                    weighted_stats[
                        "standard_deviation"
                    ],

                "p90":
                    weighted_stats[
                        "p90"
                    ],

                "p95":
                    weighted_stats[
                        "p95"
                    ],

                "maximum":
                    weighted_stats[
                        "maximum"
                    ],

                "win_count":
                    weighted_wins,

                "win_rate_percent":
                    weighted_win_rate
            },

            # Chyby rozdelene podle
            # predikcniho horizontu.
            "horizons":
                _build_horizon_statistics(
                    k_results
                )
        })

    usable_median = [
        item
        for item
        in aggregate_results
        if (
            item[
                "average_mae_median"
            ]
            is not None
        )
    ]

    usable_weighted = [
        item
        for item
        in aggregate_results
        if (
            item[
                "average_mae_weighted_mean"
            ]
            is not None
        )
    ]

    best_k_median = None
    best_k_weighted = None

    if usable_median:
        best_k_median = min(
            usable_median,
            key=lambda item:
                item[
                    "average_mae_median"
                ]
        )[
            "k"
        ]

    if usable_weighted:
        best_k_weighted = min(
            usable_weighted,
            key=lambda item:
                item[
                    "average_mae_weighted_mean"
                ]
        )[
            "k"
        ]

    return {
        "comparable_evaluation_count":
            len(
                comparable
            ),

        "results":
            aggregate_results,

        "best_k_median":
            best_k_median,

        "best_k_weighted_mean":
            best_k_weighted
    }


def evaluate_batch(
    db,
    user_id,
    evaluation_times,
    k_values=None
):
    if k_values is None:
        k_values = (
            DEFAULT_BATCH_K_VALUES
        )

    k_values = list(
        k_values
    )

    evaluations = []
    skipped = []

    for t0 in evaluation_times:
        actual_outcome = (
            build_situation_outcome(
                db=db,
                user_id=user_id,
                t0=t0
            )
        )

        if (
            actual_outcome.get(
                "outcome_coverage"
            )
            != 100.0
        ):
            skipped.append({
                "timestamp":
                    t0.isoformat(),

                "reason":
                    "INCOMPLETE_OUTCOME"
            })

            continue

        evaluation = (
            evaluate_k_values(
                db=db,
                user_id=user_id,
                t0=t0,
                k_values=k_values
            )
        )

        insufficient_k = []

        for k in k_values:
            result = (
                _find_k_result(
                    evaluation,
                    k
                )
            )

            if (
                result is None
                or result.get(
                    "k_found",
                    0
                )
                < k
            ):
                insufficient_k.append(
                    k
                )

        if insufficient_k:
            skipped.append({
                "timestamp":
                    t0.isoformat(),

                "reason":
                    "INSUFFICIENT_HISTORY",

                "insufficient_k":
                    insufficient_k
            })

            continue

        evaluations.append(
            evaluation
        )

    aggregate = (
        aggregate_batch_results(
            evaluations,
            k_values=k_values
        )
    )

    return {
        "requested_evaluation_count":
            len(
                evaluation_times
            ),

        "evaluated_count":
            len(
                evaluations
            ),

        "skipped_count":
            len(
                skipped
            ),

        "k_values":
            k_values,

        "aggregate":
            aggregate,

        "skipped":
            skipped,

        "evaluations":
            evaluations
    }