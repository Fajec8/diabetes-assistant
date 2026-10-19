from app.services.history_search import (
    calculate_ranking_score,
    select_diverse_candidates,
)


def test_candidates_from_same_episode_are_removed():
    candidates = [
        {
            "timestamp":
                "2026-10-01T13:30:00+02:00",
            "similarity_score": 99.0,
            "data_coverage": 100.0,
            "ranking_score": 99.0
        },
        {
            "timestamp":
                "2026-10-01T13:45:00+02:00",
            "similarity_score": 98.0,
            "data_coverage": 100.0,
            "ranking_score": 98.0
        },
        {
            "timestamp":
                "2026-10-01T14:15:00+02:00",
            "similarity_score": 97.0,
            "data_coverage": 100.0,
            "ranking_score": 97.0
        },
        {
            "timestamp":
                "2026-10-01T18:00:00+02:00",
            "similarity_score": 90.0,
            "data_coverage": 100.0,
            "ranking_score": 90.0
        },
        {
            "timestamp":
                "2026-10-02T13:30:00+02:00",
            "similarity_score": 95.0,
            "data_coverage": 100.0,
            "ranking_score": 95.0
        }
    ]

    result = (
        select_diverse_candidates(
            candidates,
            limit=10
        )
    )

    timestamps = [
        item["timestamp"]
        for item in result
    ]

    assert (
        "2026-10-01T13:30:00+02:00"
        in timestamps
    )

    assert (
        "2026-10-01T13:45:00+02:00"
        not in timestamps
    )

    assert (
        "2026-10-01T14:15:00+02:00"
        not in timestamps
    )

    assert (
        "2026-10-01T18:00:00+02:00"
        in timestamps
    )

    assert (
        "2026-10-02T13:30:00+02:00"
        in timestamps
    )


def test_low_coverage_reduces_ranking_score():
    complete = (
        calculate_ranking_score(
            similarity_score=99.9,
            data_coverage=100.0
        )
    )

    sparse = (
        calculate_ranking_score(
            similarity_score=100.0,
            data_coverage=83.0
        )
    )

    assert complete == 99.9
    assert sparse == 91.1

    assert (
        complete
        > sparse
    )