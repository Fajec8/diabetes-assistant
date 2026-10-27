import pytest
from pydantic import ValidationError

from app.schemas.decision import (
    DecisionOutcomeCreate,
)


def test_valid_decision_outcome():
    outcome = DecisionOutcomeCreate(
        baseline_glucose=10.0,
        glucose_30m=9.5,
        glucose_60m=9.0,
        glucose_90m=8.5,
        glucose_120m=8.0,
        glucose_180m=7.5,
    )

    assert (
        outcome.baseline_glucose
        == 10.0
    )

    assert (
        outcome.glucose_180m
        == 7.5
    )


def test_outcome_requires_future_value():
    with pytest.raises(
        ValidationError
    ):
        DecisionOutcomeCreate(
            baseline_glucose=10.0,
        )


def test_outcome_rejects_invalid_glucose():
    with pytest.raises(
        ValidationError
    ):
        DecisionOutcomeCreate(
            baseline_glucose=10.0,
            glucose_60m=45.0,
        )