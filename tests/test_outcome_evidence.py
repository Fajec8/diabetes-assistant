import pytest

from app.services.outcome_evidence import (
    evaluate_evidence_strength,
)


def test_perfect_evidence():
    result = (
        evaluate_evidence_strength(
            context_score=100.0,
            quality_score=100.0,
            confidence=100.0,
        )
    )

    assert (
        result["evidence_score"]
        == 100.0
    )

    assert (
        result["evidence_level"]
        == "STRONG"
    )


def test_strong_evidence():
    result = (
        evaluate_evidence_strength(
            context_score=75.0,
            quality_score=80.0,
            confidence=100.0,
        )
    )

    assert (
        result["evidence_score"]
        == 60.0
    )

    assert (
        result["evidence_level"]
        == "STRONG"
    )


def test_low_confidence_reduces_evidence():
    result = (
        evaluate_evidence_strength(
            context_score=75.0,
            quality_score=80.0,
            confidence=20.0,
        )
    )

    assert (
        result["evidence_score"]
        == 12.0
    )

    assert (
        result["evidence_level"]
        == "WEAK"
    )


def test_missing_quality_returns_no_data():
    result = (
        evaluate_evidence_strength(
            context_score=80.0,
            quality_score=None,
            confidence=100.0,
        )
    )

    assert (
        result["evidence_score"]
        is None
    )

    assert (
        result["evidence_level"]
        == "NO_DATA"
    )


def test_invalid_value_raises():
    with pytest.raises(
        ValueError
    ):
        evaluate_evidence_strength(
            context_score=101.0,
            quality_score=80.0,
            confidence=100.0,
        )