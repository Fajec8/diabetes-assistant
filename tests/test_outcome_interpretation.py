from app.services.outcome_interpretation import (
    build_outcome_interpretation,
)


def test_interpretation_detects_decreasing_pattern():
    summary = {
        "delta_90m": {
            "count": 10,
            "median": -0.3,
            "weighted_mean": -0.19,

            "direction": {
                "decreased": 5,
                "stable": 3,
                "increased": 2
            }
        }
    }

    result = (
        build_outcome_interpretation(
            summary
        )
    )

    interpretation = result["90m"]

    assert (
        interpretation["sample_size"]
        == 10
    )

    assert (
        interpretation["dominant_direction"]
        == "decreased"
    )

    assert (
        interpretation["dominant_count"]
        == 5
    )

    assert (
        interpretation[
            "dominant_share_percent"
        ]
        == 50.0
    )

    assert (
        interpretation["pattern_strength"]
        == "MODERATE"
    )

    assert (
        interpretation["median_delta"]
        == -0.3
    )

    assert (
        "5 z 10"
        in interpretation["text"]
    )


def test_interpretation_detects_mixed_pattern():
    summary = {
        "delta_90m": {
            "count": 10,
            "median": 0.0,
            "weighted_mean": 0.0,

            "direction": {
                "decreased": 4,
                "stable": 2,
                "increased": 4
            }
        }
    }

    result = (
        build_outcome_interpretation(
            summary
        )
    )

    interpretation = result["90m"]

    assert (
        interpretation["dominant_direction"]
        == "mixed"
    )

    assert (
        interpretation["pattern_strength"]
        == "MIXED"
    )

    assert (
        interpretation[
            "dominant_share_percent"
        ]
        == 40.0
    )


def test_interpretation_handles_missing_data():
    summary = {
        "delta_90m": {
            "count": 0,
            "median": None,
            "weighted_mean": None,

            "direction": {
                "decreased": 0,
                "stable": 0,
                "increased": 0
            }
        }
    }

    result = (
        build_outcome_interpretation(
            summary
        )
    )

    interpretation = result["90m"]

    assert (
        interpretation["sample_size"]
        == 0
    )

    assert (
        interpretation["dominant_direction"]
        is None
    )

    assert (
        interpretation["pattern_strength"]
        == "NO_DATA"
    )