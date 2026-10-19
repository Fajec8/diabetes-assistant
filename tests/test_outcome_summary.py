from app.services.outcome_summary import (
    summarize_outcomes,
)


def test_outcome_summary():
    items = [
        {
            "ranking_score": 100,
            "outcome": {
                "delta_30m": -1.0,
                "delta_60m": -1.0,
                "delta_90m": -1.0
            }
        },
        {
            "ranking_score": 90,
            "outcome": {
                "delta_30m": -0.5,
                "delta_60m": -0.5,
                "delta_90m": -0.5
            }
        },
        {
            "ranking_score": 80,
            "outcome": {
                "delta_30m": 0.0,
                "delta_60m": 0.0,
                "delta_90m": 0.0
            }
        },
        {
            "ranking_score": 70,
            "outcome": {
                "delta_30m": 0.5,
                "delta_60m": 0.5,
                "delta_90m": 0.5
            }
        },
        {
            "ranking_score": 60,
            "outcome": {
                "delta_30m": 1.0,
                "delta_60m": 1.0,
                "delta_90m": 1.0
            }
        }
    ]

    summary = summarize_outcomes(
        items
    )

    assert (
        summary["stable_threshold"]
        == 0.2
    )

    delta_30 = (
        summary["delta_30m"]
    )

    assert (
        delta_30["count"]
        == 5
    )

    assert (
        delta_30["median"]
        == 0.0
    )

    assert (
        delta_30["weighted_mean"]
        == -0.12
    )

    assert (
        delta_30["q1"]
        == -0.5
    )

    assert (
        delta_30["q3"]
        == 0.5
    )

    assert (
        delta_30["direction"]["decreased"]
        == 2
    )

    assert (
        delta_30["direction"]["stable"]
        == 1
    )

    assert (
        delta_30["direction"]["increased"]
        == 2
    )

    assert (
        summary["delta_60m"]["median"]
        == 0.0
    )

    assert (
        summary["delta_90m"]["median"]
        == 0.0
    )


def test_summary_ignores_missing_values():
    items = [
        {
            "ranking_score": 100,
            "outcome": {
                "delta_30m": -0.1,
                "delta_60m": None,
                "delta_90m": None
            }
        },
        {
            "ranking_score": 50,
            "outcome": {
                "delta_30m": 0.1,
                "delta_60m": None,
                "delta_90m": None
            }
        }
    ]

    summary = summarize_outcomes(
        items
    )

    delta_30 = (
        summary["delta_30m"]
    )

    assert (
        delta_30["count"]
        == 2
    )

    assert (
        delta_30["median"]
        == 0.0
    )

    assert (
        delta_30["weighted_mean"]
        == -0.03
    )

    assert (
        delta_30["direction"]["stable"]
        == 2
    )

    assert (
        summary["delta_60m"]["count"]
        == 0
    )

    assert (
        summary["delta_60m"]["median"]
        is None
    )

    assert (
        summary["delta_60m"]["weighted_mean"]
        is None
    )

    assert (
        summary["delta_90m"]["count"]
        == 0
    )

    assert (
        summary["delta_90m"]["median"]
        is None
    )


def test_direction_threshold():
    items = [
        {
            "ranking_score": 100,
            "outcome": {
                "delta_30m": -0.2,
                "delta_60m": -0.2,
                "delta_90m": -0.2
            }
        },
        {
            "ranking_score": 100,
            "outcome": {
                "delta_30m": 0.2,
                "delta_60m": 0.2,
                "delta_90m": 0.2
            }
        },
        {
            "ranking_score": 100,
            "outcome": {
                "delta_30m": -0.21,
                "delta_60m": -0.21,
                "delta_90m": -0.21
            }
        },
        {
            "ranking_score": 100,
            "outcome": {
                "delta_30m": 0.21,
                "delta_60m": 0.21,
                "delta_90m": 0.21
            }
        }
    ]

    summary = summarize_outcomes(
        items
    )

    direction = (
        summary[
            "delta_30m"
        ][
            "direction"
        ]
    )

    assert (
        direction["decreased"]
        == 1
    )

    assert (
        direction["stable"]
        == 2
    )

    assert (
        direction["increased"]
        == 1
    )