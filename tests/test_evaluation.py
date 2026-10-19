from app.services.evaluation import (
    calculate_prediction_metrics,
)


def test_calculate_prediction_metrics():
    actual_outcome = {
        "delta_30m": -0.2,
        "delta_60m": -0.4,
        "delta_90m": -0.6,
        "delta_120m": -0.8,
        "delta_180m": -1.0
    }

    outcome_summary = {
        "delta_30m": {
            "median": -0.1,
            "weighted_mean": -0.2
        },

        "delta_60m": {
            "median": -0.5,
            "weighted_mean": -0.3
        },

        "delta_90m": {
            "median": -0.4,
            "weighted_mean": -0.8
        },

        "delta_120m": {
            "median": -1.0,
            "weighted_mean": -0.7
        },

        "delta_180m": {
            "median": -1.2,
            "weighted_mean": -0.9
        }
    }

    result = (
        calculate_prediction_metrics(
            actual_outcome=
                actual_outcome,

            outcome_summary=
                outcome_summary
        )
    )

    assert (
        result["mae_median"]
        == 0.16
    )

    assert (
        result["mae_weighted_mean"]
        == 0.1
    )

    assert (
        result["horizons"]["30m"][
            "actual_delta"
        ]
        == -0.2
    )

    assert (
        result["horizons"]["30m"][
            "predicted_median"
        ]
        == -0.1
    )

    assert (
        result["horizons"]["30m"][
            "absolute_error_median"
        ]
        == 0.1
    )

    assert (
        result["horizons"]["180m"][
            "actual_delta"
        ]
        == -1.0
    )

    assert (
        result["horizons"]["180m"][
            "absolute_error_weighted_mean"
        ]
        == 0.1
    )