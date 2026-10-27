from app.services.outcome_quality import (
    evaluate_outcome_quality,
    score_glucose_value,
)


def test_exact_target_scores_100():
    assert (
        score_glucose_value(8.0)
        == 100.0
    )


def test_target_range_scoring():
    assert (
        score_glucose_value(4.0)
        == 60.0
    )

    assert (
        score_glucose_value(5.0)
        == 70.0
    )

    assert (
        score_glucose_value(8.0)
        == 100.0
    )

    assert (
        score_glucose_value(10.0)
        == 80.0
    )


def test_low_is_penalized_more_strongly():
    assert (
        score_glucose_value(3.0)
        == 20.0
    )

    assert (
        score_glucose_value(12.0)
        == 60.0
    )


def test_perfect_outcome():
    outcome = {
        "glucose_30m": 8.0,
        "glucose_60m": 8.0,
        "glucose_90m": 8.0,
        "glucose_120m": 8.0,
        "glucose_180m": 8.0,
    }

    result = (
        evaluate_outcome_quality(
            outcome
        )
    )

    assert (
        result["quality_score"]
        == 100.0
    )

    assert (
        result["status"]
        == "EXCELLENT"
    )

    assert (
        result["confidence"]
        == 100.0
    )

    assert (
        result["confidence_level"]
        == "HIGH"
    )

    assert (
        result["latest_glucose"]
        == 8.0
    )


def test_high_glucose_can_fall_towards_target():
    outcome = {
        "glucose_30m": 11.0,
        "glucose_60m": 10.0,
        "glucose_90m": 9.0,
        "glucose_120m": 8.5,
        "glucose_180m": 8.0,
    }

    result = (
        evaluate_outcome_quality(
            outcome
        )
    )

    assert (
        result["quality_score"]
        == 92.25
    )

    assert (
        result["status"]
        == "EXCELLENT"
    )

    assert (
        result["distance_from_target"]
        == 0.0
    )

    assert (
        result["confidence"]
        == 100.0
    )


def test_low_glucose_can_rise_towards_target():
    outcome = {
        "glucose_30m": 5.0,
        "glucose_60m": 6.0,
        "glucose_90m": 7.0,
        "glucose_120m": 7.5,
        "glucose_180m": 8.0,
    }

    result = (
        evaluate_outcome_quality(
            outcome
        )
    )

    assert (
        result["quality_score"]
        == 92.25
    )

    assert (
        result["status"]
        == "EXCELLENT"
    )

    assert (
        result["confidence"]
        == 100.0
    )


def test_hypoglycemia_caps_total_score():
    outcome = {
        "glucose_30m": 8.0,
        "glucose_60m": 8.0,
        "glucose_90m": 8.0,
        "glucose_120m": 8.0,
        "glucose_180m": 3.8,
    }

    result = (
        evaluate_outcome_quality(
            outcome
        )
    )

    assert (
        result["low_detected"]
        is True
    )

    assert (
        result["quality_score"]
        == 35.0
    )

    assert (
        result["status"]
        == "POOR"
    )

    assert (
        result["confidence"]
        == 100.0
    )


def test_missing_horizons_are_allowed():
    outcome = {
        "glucose_30m": None,
        "glucose_60m": None,
        "glucose_90m": 9.0,
        "glucose_120m": 8.5,
        "glucose_180m": 8.0,
    }

    result = (
        evaluate_outcome_quality(
            outcome
        )
    )

    assert (
        result["quality_score"]
        is not None
    )

    assert (
        result[
            "latest_horizon_minutes"
        ]
        == 180
    )

    assert (
        result["confidence"]
        == 80.0
    )

    assert (
        result["confidence_level"]
        == "HIGH"
    )

    assert (
        result["available_horizons"]
        == [
            90,
            120,
            180,
        ]
    )


def test_only_30_minutes_has_low_confidence():
    outcome = {
        "glucose_30m": 8.0,
        "glucose_60m": None,
        "glucose_90m": None,
        "glucose_120m": None,
        "glucose_180m": None,
    }

    result = (
        evaluate_outcome_quality(
            outcome
        )
    )

    assert (
        result["quality_score"]
        == 100.0
    )

    assert (
        result["confidence"]
        == 5.0
    )

    assert (
        result["confidence_level"]
        == "LOW"
    )


def test_30_and_60_minutes_have_20_percent_confidence():
    outcome = {
        "glucose_30m": 8.0,
        "glucose_60m": 8.0,
        "glucose_90m": None,
        "glucose_120m": None,
        "glucose_180m": None,
    }

    result = (
        evaluate_outcome_quality(
            outcome
        )
    )

    assert (
        result["quality_score"]
        == 100.0
    )

    assert (
        result["confidence"]
        == 20.0
    )

    assert (
        result["confidence_level"]
        == "LOW"
    )


def test_first_four_horizons_have_65_percent_confidence():
    outcome = {
        "glucose_30m": 8.0,
        "glucose_60m": 8.0,
        "glucose_90m": 8.0,
        "glucose_120m": 8.0,
        "glucose_180m": None,
    }

    result = (
        evaluate_outcome_quality(
            outcome
        )
    )

    assert (
        result["confidence"]
        == 65.0
    )

    assert (
        result["confidence_level"]
        == "MEDIUM"
    )


def test_no_data():
    result = (
        evaluate_outcome_quality(
            {}
        )
    )

    assert (
        result["quality_score"]
        is None
    )

    assert (
        result["status"]
        == "NO_DATA"
    )

    assert (
        result["confidence"]
        == 0.0
    )

    assert (
        result["confidence_level"]
        == "NO_DATA"
    )