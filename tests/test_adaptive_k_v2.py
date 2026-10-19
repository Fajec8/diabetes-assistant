from app.services.adaptive_k import (
    choose_adaptive_k_v2,
)


def _candidate(
    ranking_score,
    data_coverage=100.0
):
    return {
        "ranking_score":
            ranking_score,

        "data_coverage":
            data_coverage
    }


def test_adaptive_k_v2_defaults_to_k10():
    candidates = [
        _candidate(
            100.0
            - index * 0.25
        )
        for index in range(
            20
        )
    ]

    result = (
        choose_adaptive_k_v2(
            candidates
        )
    )

    assert (
        result[
            "selected_k"
        ]
        == 10
    )

    assert (
        result[
            "reason"
        ]
        == "DEFAULT_K10"
    )


def test_adaptive_k_v2_shrinks_to_k5():
    candidates = [
        _candidate(99.0),
        _candidate(98.8),
        _candidate(98.6),
        _candidate(98.4),
        _candidate(98.2),

        _candidate(94.0),
        _candidate(93.8),
        _candidate(93.6),
        _candidate(93.4),
        _candidate(93.2),

        _candidate(90.0),
        _candidate(89.8),
        _candidate(89.6),
        _candidate(89.4),
        _candidate(89.2),
        _candidate(89.0),
        _candidate(88.8),
        _candidate(88.6),
        _candidate(88.4),
        _candidate(88.2)
    ]

    result = (
        choose_adaptive_k_v2(
            candidates
        )
    )

    assert (
        result[
            "selected_k"
        ]
        == 5
    )

    assert (
        result[
            "reason"
        ]
        == "STRONG_DROP_AFTER_K5"
    )


def test_adaptive_k_v2_shrinks_to_k3():
    candidates = [
        _candidate(99.0),
        _candidate(98.9),
        _candidate(98.8),

        _candidate(94.0),
        _candidate(93.8),

        _candidate(88.0),
        _candidate(87.8),
        _candidate(87.6),
        _candidate(87.4),
        _candidate(87.2),

        _candidate(85.0),
        _candidate(84.8),
        _candidate(84.6),
        _candidate(84.4),
        _candidate(84.2),
        _candidate(84.0),
        _candidate(83.8),
        _candidate(83.6),
        _candidate(83.4),
        _candidate(83.2)
    ]

    result = (
        choose_adaptive_k_v2(
            candidates
        )
    )

    assert (
        result[
            "selected_k"
        ]
        == 3
    )

    assert (
        result[
            "reason"
        ]
        == "STRONG_DROP_AFTER_K3"
    )


def test_adaptive_k_v2_expands_to_k20():
    candidates = [
        _candidate(
            99.0
            - index * 0.03
        )
        for index in range(
            20
        )
    ]

    result = (
        choose_adaptive_k_v2(
            candidates
        )
    )

    assert (
        result[
            "selected_k"
        ]
        == 20
    )

    assert (
        result[
            "reason"
        ]
        == "FLAT_RANKING_TO_K20"
    )


def test_adaptive_k_v2_low_coverage_blocks_shrink():
    candidates = [
        _candidate(
            ranking_score=99.0,
            data_coverage=90.0
        ),
        _candidate(
            ranking_score=98.9,
            data_coverage=90.0
        ),
        _candidate(
            ranking_score=98.8,
            data_coverage=90.0
        ),

        _candidate(
            ranking_score=94.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=93.8,
            data_coverage=100.0
        ),

        _candidate(
            ranking_score=88.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=87.8,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=87.6,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=87.4,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=87.2,
            data_coverage=100.0
        ),

        _candidate(
            ranking_score=80.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=79.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=78.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=77.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=76.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=75.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=74.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=73.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=72.0,
            data_coverage=100.0
        ),
        _candidate(
            ranking_score=71.0,
            data_coverage=100.0
        )
    ]

    result = (
        choose_adaptive_k_v2(
            candidates
        )
    )

    assert (
        result[
            "selected_k"
        ]
        == 10
    )

    assert (
        result[
            "reason"
        ]
        == "DEFAULT_K10"
    )


def test_adaptive_k_v2_does_not_expand_without_20_candidates():
    candidates = [
        _candidate(
            99.0
            - index * 0.03
        )
        for index in range(
            15
        )
    ]

    result = (
        choose_adaptive_k_v2(
            candidates
        )
    )

    assert (
        result[
            "selected_k"
        ]
        == 10
    )


def test_adaptive_k_v2_uses_k5_with_limited_history():
    candidates = [
        _candidate(99.0),
        _candidate(98.9),
        _candidate(98.8),
        _candidate(98.7),
        _candidate(98.6),
        _candidate(98.5)
    ]

    result = (
        choose_adaptive_k_v2(
            candidates
        )
    )

    assert (
        result[
            "selected_k"
        ]
        == 5
    )

    assert (
        result[
            "reason"
        ]
        == "LIMITED_HISTORY_K5"
    )


def test_adaptive_k_v2_uses_k3_with_very_limited_history():
    candidates = [
        _candidate(99.0),
        _candidate(98.9),
        _candidate(98.8),
        _candidate(98.7)
    ]

    result = (
        choose_adaptive_k_v2(
            candidates
        )
    )

    assert (
        result[
            "selected_k"
        ]
        == 3
    )

    assert (
        result[
            "reason"
        ]
        == "LIMITED_HISTORY_K3"
    )


def test_adaptive_k_v2_requires_at_least_three_candidates():
    candidates = [
        _candidate(99.0),
        _candidate(98.9)
    ]

    result = (
        choose_adaptive_k_v2(
            candidates
        )
    )

    assert (
        result[
            "selected_k"
        ]
        is None
    )

    assert (
        result[
            "reason"
        ]
        == "INSUFFICIENT_HISTORY"
    )