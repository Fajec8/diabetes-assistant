from datetime import datetime
from zoneinfo import ZoneInfo

import app.services.evaluation as evaluation


def test_evaluate_k_values_searches_history_only_once(
    monkeypatch
):
    search_calls = []

    summary_sizes = []
    evidence_sizes = []

    t0 = datetime(
        2026,
        10,
        2,
        13,
        30,
        tzinfo=ZoneInfo(
            "Europe/Prague"
        )
    )

    actual_outcome = {
        "delta_30m": -0.2,
        "delta_60m": -0.3,
        "delta_90m": -0.5,
        "delta_120m": -0.7,
        "delta_180m": -1.0,
        "outcome_coverage": 100.0
    }

    similar_situations = [
        {
            "test_id": i
        }
        for i in range(
            20
        )
    ]

    def fake_build_situation_outcome(
        db,
        user_id,
        t0
    ):
        return actual_outcome

    def fake_find_similar_situations(
        db,
        user_id,
        t0,
        limit
    ):
        search_calls.append(
            limit
        )

        return {
            "found":
                len(
                    similar_situations
                ),

            "similar_situations":
                similar_situations
        }

    def fake_summarize_outcomes(
        situations
    ):
        size = len(
            situations
        )

        summary_sizes.append(
            size
        )

        return {
            f"delta_{minutes}m": {
                "count":
                    size,

                "median":
                    0.0,

                "weighted_mean":
                    0.0
            }
            for minutes
            in evaluation.HORIZONS
        }

    def fake_build_evidence(
        situations
    ):
        size = len(
            situations
        )

        evidence_sizes.append(
            size
        )

        return {
            "sample_size":
                size,

            "average_similarity_score":
                95.0,

            "average_ranking_score":
                94.0,

            "minimum_ranking_score":
                90.0,

            "average_data_coverage":
                100.0,

            "quality":
                "HIGH"
        }

    monkeypatch.setattr(
        evaluation,
        "build_situation_outcome",
        fake_build_situation_outcome
    )

    monkeypatch.setattr(
        evaluation,
        "find_similar_situations",
        fake_find_similar_situations
    )

    monkeypatch.setattr(
        evaluation,
        "summarize_outcomes",
        fake_summarize_outcomes
    )

    monkeypatch.setattr(
        evaluation,
        "build_evidence",
        fake_build_evidence
    )

    # Tento test je zameren pouze
    # na optimalizaci fixed K evaluace.
    #
    # Adaptive V2 zde vypneme,
    # aby nepridavalo dalsi
    # summarize/evidence volani.
    monkeypatch.setattr(
        evaluation,
        "choose_adaptive_k_v2",
        lambda situations: {
            "selected_k": None
        }
    )

    result = (
        evaluation.evaluate_k_values(
            db=None,
            user_id="test-user",
            t0=t0,
            k_values=[
                3,
                5,
                10
            ]
        )
    )

    # Adaptive K V2 muze potrebovat
    # az TOP 20 kandidatu.
    #
    # Historie se presto hleda
    # pouze JEDNOU.
    assert (
        search_calls
        == [20]
    )

    assert (
        summary_sizes
        == [
            3,
            5,
            10
        ]
    )

    assert (
        evidence_sizes
        == [
            3,
            5,
            10
        ]
    )

    assert [
        item[
            "k_found"
        ]
        for item
        in result[
            "results"
        ]
    ] == [
        3,
        5,
        10
    ]

    assert (
        result[
            "adaptive"
        ]
        is None
    )


def test_evaluate_k_values_handles_missing_history(
    monkeypatch
):
    t0 = datetime(
        2026,
        10,
        2,
        13,
        30,
        tzinfo=ZoneInfo(
            "Europe/Prague"
        )
    )

    actual_outcome = {
        "delta_30m": 0.0,
        "delta_60m": 0.0,
        "delta_90m": 0.0,
        "delta_120m": 0.0,
        "delta_180m": 0.0,
        "outcome_coverage": 100.0
    }

    similar_situations = [
        {
            "test_id": i
        }
        for i in range(
            4
        )
    ]

    monkeypatch.setattr(
        evaluation,
        "build_situation_outcome",
        lambda **kwargs:
            actual_outcome
    )

    monkeypatch.setattr(
        evaluation,
        "find_similar_situations",
        lambda **kwargs: {
            "found": 4,

            "similar_situations":
                similar_situations
        }
    )

    monkeypatch.setattr(
        evaluation,
        "summarize_outcomes",
        lambda situations: {
            f"delta_{minutes}m": {
                "median":
                    0.0,

                "weighted_mean":
                    0.0
            }
            for minutes
            in evaluation.HORIZONS
        }
    )

    def fake_evidence(
        situations
    ):
        return {
            "sample_size":
                len(
                    situations
                ),

            "average_similarity_score":
                90.0,

            "average_ranking_score":
                90.0,

            "minimum_ranking_score":
                90.0,

            "average_data_coverage":
                100.0,

            "quality":
                "LOW"
        }

    monkeypatch.setattr(
        evaluation,
        "build_evidence",
        fake_evidence
    )

    monkeypatch.setattr(
        evaluation,
        "choose_adaptive_k_v2",
        lambda situations: {
            "selected_k": None
        }
    )

    result = (
        evaluation.evaluate_k_values(
            db=None,
            user_id="test-user",
            t0=t0,
            k_values=[
                3,
                5,
                10
            ]
        )
    )

    assert [
        item[
            "k_found"
        ]
        for item
        in result[
            "results"
        ]
    ] == [
        3,
        4,
        4
    ]

    assert (
        result[
            "adaptive"
        ]
        is None
    )