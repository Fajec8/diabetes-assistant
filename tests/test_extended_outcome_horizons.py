from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.services.outcome_interpretation import (
    build_outcome_interpretation,
)
from app.services.outcome_summary import (
    summarize_outcomes,
)
from app.services.situation_outcome import (
    build_situation_outcome,
)


def test_situation_outcome_contains_120_and_180_minutes():
    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(
                User.email
                == "test@example.com"
            )
        )

        assert user is not None

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

        outcome = (
            build_situation_outcome(
                db=db,
                user_id=user.id,
                t0=t0
            )
        )

        assert (
            outcome["baseline_glucose"]
            == 7.1
        )

        assert (
            outcome["glucose_120m"]
            == 6.4
        )

        assert (
            outcome["glucose_180m"]
            == 6.1
        )

        assert (
            outcome["delta_120m"]
            == -0.7
        )

        assert (
            outcome["delta_180m"]
            == -1.0
        )

        assert (
            outcome["outcome_coverage"]
            == 100.0
        )

    finally:
        db.close()


def test_outcome_summary_contains_120_and_180_minutes():
    items = [
        {
            "ranking_score": 100.0,
            "outcome": {
                "delta_120m": -1.0,
                "delta_180m": -2.0
            }
        },
        {
            "ranking_score": 50.0,
            "outcome": {
                "delta_120m": 0.0,
                "delta_180m": 0.0
            }
        },
        {
            "ranking_score": 25.0,
            "outcome": {
                "delta_120m": 1.0,
                "delta_180m": 2.0
            }
        }
    ]

    summary = summarize_outcomes(
        items
    )

    delta_120 = (
        summary["delta_120m"]
    )

    delta_180 = (
        summary["delta_180m"]
    )

    assert (
        delta_120["count"]
        == 3
    )

    assert (
        delta_120["median"]
        == 0.0
    )

    assert (
        delta_120["weighted_mean"]
        == -0.43
    )

    assert (
        delta_120["direction"]["decreased"]
        == 1
    )

    assert (
        delta_120["direction"]["stable"]
        == 1
    )

    assert (
        delta_120["direction"]["increased"]
        == 1
    )

    assert (
        delta_180["count"]
        == 3
    )

    assert (
        delta_180["median"]
        == 0.0
    )

    assert (
        delta_180["weighted_mean"]
        == -0.86
    )

    assert (
        delta_180["direction"]["decreased"]
        == 1
    )

    assert (
        delta_180["direction"]["stable"]
        == 1
    )

    assert (
        delta_180["direction"]["increased"]
        == 1
    )


def test_outcome_interpretation_contains_120_and_180_minutes():
    summary = {
        "delta_120m": {
            "count": 10,
            "median": -0.4,
            "weighted_mean": -0.3,

            "direction": {
                "decreased": 6,
                "stable": 3,
                "increased": 1
            }
        },

        "delta_180m": {
            "count": 10,
            "median": -0.8,
            "weighted_mean": -0.6,

            "direction": {
                "decreased": 7,
                "stable": 2,
                "increased": 1
            }
        }
    }

    interpretation = (
        build_outcome_interpretation(
            summary
        )
    )

    result_120 = (
        interpretation["120m"]
    )

    result_180 = (
        interpretation["180m"]
    )

    assert (
        result_120["horizon_minutes"]
        == 120
    )

    assert (
        result_120["sample_size"]
        == 10
    )

    assert (
        result_120["dominant_direction"]
        == "decreased"
    )

    assert (
        result_120["dominant_count"]
        == 6
    )

    assert (
        result_120[
            "dominant_share_percent"
        ]
        == 60.0
    )

    assert (
        result_120["pattern_strength"]
        == "MODERATE"
    )

    assert (
        result_120["median_delta"]
        == -0.4
    )

    assert (
        "120 minut"
        in result_120["text"]
    )

    assert (
        result_180["horizon_minutes"]
        == 180
    )

    assert (
        result_180["sample_size"]
        == 10
    )

    assert (
        result_180["dominant_direction"]
        == "decreased"
    )

    assert (
        result_180["dominant_count"]
        == 7
    )

    assert (
        result_180[
            "dominant_share_percent"
        ]
        == 70.0
    )

    assert (
        result_180["pattern_strength"]
        == "STRONG"
    )

    assert (
        result_180["median_delta"]
        == -0.8
    )

    assert (
        "180 minut"
        in result_180["text"]
    )