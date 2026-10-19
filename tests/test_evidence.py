from app.services.evidence import (
    build_evidence,
)


def test_high_quality_evidence():
    items = [
        {
            "similarity_score": 99.0,
            "ranking_score": 98.0,
            "data_coverage": 100.0
        },
        {
            "similarity_score": 97.0,
            "ranking_score": 96.0,
            "data_coverage": 98.0
        },
        {
            "similarity_score": 96.0,
            "ranking_score": 95.0,
            "data_coverage": 100.0
        },
        {
            "similarity_score": 95.0,
            "ranking_score": 94.0,
            "data_coverage": 99.0
        },
        {
            "similarity_score": 94.0,
            "ranking_score": 93.0,
            "data_coverage": 100.0
        },
        {
            "similarity_score": 93.0,
            "ranking_score": 92.0,
            "data_coverage": 100.0
        },
        {
            "similarity_score": 92.0,
            "ranking_score": 91.0,
            "data_coverage": 97.0
        },
        {
            "similarity_score": 91.0,
            "ranking_score": 90.0,
            "data_coverage": 96.0
        }
    ]

    evidence = build_evidence(
        items
    )

    assert (
        evidence["sample_size"]
        == 8
    )

    assert (
        evidence["quality"]
        == "HIGH"
    )

    assert (
        evidence["average_ranking_score"]
        == 93.62
    )

    assert (
        evidence["minimum_ranking_score"]
        == 90.0
    )


def test_medium_quality_evidence():
    items = [
        {
            "similarity_score": 85.0,
            "ranking_score": 84.0,
            "data_coverage": 85.0
        },
        {
            "similarity_score": 84.0,
            "ranking_score": 83.0,
            "data_coverage": 84.0
        },
        {
            "similarity_score": 83.0,
            "ranking_score": 82.0,
            "data_coverage": 83.0
        },
        {
            "similarity_score": 82.0,
            "ranking_score": 81.0,
            "data_coverage": 82.0
        },
        {
            "similarity_score": 81.0,
            "ranking_score": 80.0,
            "data_coverage": 81.0
        }
    ]

    evidence = build_evidence(
        items
    )

    assert (
        evidence["sample_size"]
        == 5
    )

    assert (
        evidence["quality"]
        == "MEDIUM"
    )


def test_no_data_evidence():
    evidence = build_evidence(
        []
    )

    assert (
        evidence["sample_size"]
        == 0
    )

    assert (
        evidence["average_similarity_score"]
        is None
    )

    assert (
        evidence["average_ranking_score"]
        is None
    )

    assert (
        evidence["minimum_ranking_score"]
        is None
    )

    assert (
        evidence["average_data_coverage"]
        is None
    )

    assert (
        evidence["quality"]
        == "NO_DATA"
    )