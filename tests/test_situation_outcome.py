from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.services.situation_outcome import build_situation_outcome


def test_historical_outcome():
    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(
                User.email == "test@example.com"
            )
        )

        assert user is not None

        t0 = datetime(
            2026, 10, 2, 13, 30,
            tzinfo=ZoneInfo("Europe/Prague")
        )

        outcome = build_situation_outcome(
            db=db,
            user_id=user.id,
            t0=t0
        )

        assert outcome["baseline_glucose"] == 7.1

        assert outcome["glucose_30m"] == 6.9
        assert outcome["glucose_60m"] == 6.8
        assert outcome["glucose_90m"] == 6.6

        assert outcome["delta_30m"] == -0.2
        assert outcome["delta_60m"] == -0.3
        assert outcome["delta_90m"] == -0.5

        assert outcome["outcome_coverage"] == 100.0

    finally:
        db.close()
