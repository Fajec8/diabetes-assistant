from app.services.research_action_estimation import (
    estimate_research_action,
)


def test_abstains_without_enough_support():
    result = (
        estimate_research_action(
            [
                {
                    "dose_units": 2.0,
                    "evidence_score": 60.0,
                },
            ]
        )
    )

    assert (
        result["status"]
        == "ABSTAIN"
    )

    assert (
        result["estimated_units"]
        is None
    )

    assert (
        result["support_count"]
        == 1
    )


def test_weak_evidence_is_ignored():
    result = (
        estimate_research_action(
            [
                {
                    "dose_units": 6.0,
                    "evidence_score": 20.0,
                },
                {
                    "dose_units": 2.0,
                    "evidence_score": 60.0,
                },
                {
                    "dose_units": 2.5,
                    "evidence_score": 55.0,
                },
            ]
        )
    )

    assert (
        result["status"]
        == "ESTIMATED"
    )

    assert (
        result["support_count"]
        == 2
    )


def test_weighted_median_prefers_stronger_group():
    result = (
        estimate_research_action(
            [
                {
                    "dose_units": 2.0,
                    "evidence_score": 70.0,
                },
                {
                    "dose_units": 2.0,
                    "evidence_score": 65.0,
                },
                {
                    "dose_units": 4.0,
                    "evidence_score": 40.0,
                },
            ]
        )
    )

    assert (
        result["estimated_units"]
        == 2.0
    )

    assert (
        result["weighted_median_units"]
        == 2.0
    )


def test_weighted_mean_is_reported():
    result = (
        estimate_research_action(
            [
                {
                    "dose_units": 2.0,
                    "evidence_score": 50.0,
                },
                {
                    "dose_units": 3.0,
                    "evidence_score": 50.0,
                },
            ]
        )
    )

    assert (
        result["weighted_mean_units"]
        == 2.5
    )


def test_custom_minimum_support():
    result = (
        estimate_research_action(
            [
                {
                    "dose_units": 2.0,
                    "evidence_score": 60.0,
                },
                {
                    "dose_units": 2.5,
                    "evidence_score": 60.0,
                },
            ],
            min_support_cases=3,
        )
    )

    assert (
        result["status"]
        == "ABSTAIN"
    )