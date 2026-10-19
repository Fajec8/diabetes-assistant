from app.services.batch_evaluation import (
    aggregate_batch_results,
)


K_VALUES = [
    3,
    5,
    10
]


def _evaluation(
    timestamp,
    k3_median,
    k3_weighted,
    k5_median,
    k5_weighted,
    k10_median,
    k10_weighted,
    k10_found=10
):
    return {
        "evaluation_timestamp":
            timestamp,

        "actual_outcome": {
            "outcome_coverage":
                100.0
        },

        "results": [
            {
                "k_requested": 3,
                "k_found": 3,
                "mae_median":
                    k3_median,
                "mae_weighted_mean":
                    k3_weighted,
                "average_ranking_score":
                    98.0
            },
            {
                "k_requested": 5,
                "k_found": 5,
                "mae_median":
                    k5_median,
                "mae_weighted_mean":
                    k5_weighted,
                "average_ranking_score":
                    96.0
            },
            {
                "k_requested": 10,
                "k_found":
                    k10_found,
                "mae_median":
                    k10_median,
                "mae_weighted_mean":
                    k10_weighted,
                "average_ranking_score":
                    94.0
            }
        ]
    }


def test_batch_aggregation():
    evaluations = [
        _evaluation(
            timestamp=
                "2026-10-01T13:30:00+02:00",

            k3_median=0.2,
            k3_weighted=0.3,

            k5_median=0.4,
            k5_weighted=0.5,

            k10_median=0.6,
            k10_weighted=0.7
        ),

        _evaluation(
            timestamp=
                "2026-10-02T13:30:00+02:00",

            k3_median=0.4,
            k3_weighted=0.1,

            k5_median=0.6,
            k5_weighted=0.3,

            k10_median=0.8,
            k10_weighted=0.9
        )
    ]

    result = (
        aggregate_batch_results(
            evaluations,
            k_values=K_VALUES
        )
    )

    assert (
        result[
            "comparable_evaluation_count"
        ]
        == 2
    )

    assert (
        result["results"][0][
            "average_mae_median"
        ]
        == 0.3
    )

    assert (
        result["results"][0][
            "average_mae_weighted_mean"
        ]
        == 0.2
    )

    assert (
        result["results"][1][
            "average_mae_median"
        ]
        == 0.5
    )

    assert (
        result["results"][2][
            "average_mae_median"
        ]
        == 0.7
    )

    assert (
        result["best_k_median"]
        == 3
    )

    assert (
        result[
            "best_k_weighted_mean"
        ]
        == 3
    )


def test_incomplete_k_is_not_comparable():
    complete = _evaluation(
        timestamp=
            "2026-10-01T13:30:00+02:00",

        k3_median=0.2,
        k3_weighted=0.2,

        k5_median=0.3,
        k5_weighted=0.3,

        k10_median=0.4,
        k10_weighted=0.4
    )

    incomplete = _evaluation(
        timestamp=
            "2026-10-02T13:30:00+02:00",

        k3_median=0.1,
        k3_weighted=0.1,

        k5_median=0.1,
        k5_weighted=0.1,

        k10_median=0.1,
        k10_weighted=0.1,

        k10_found=8
    )

    result = (
        aggregate_batch_results(
            [
                complete,
                incomplete
            ],
            k_values=K_VALUES
        )
    )

    assert (
        result[
            "comparable_evaluation_count"
        ]
        == 1
    )

    assert (
        result["results"][0][
            "evaluation_count"
        ]
        == 1
    )