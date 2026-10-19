from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.services.situation_builder import (
    build_situation,
)


def test_seeded_situation_1330():
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
            3,
            13,
            30,
            tzinfo=ZoneInfo(
                "Europe/Prague"
            )
        )

        situation = build_situation(
            db=db,
            user_id=user.id,
            t0=t0
        )

        assert (
            situation[
                "glucose"
            ][
                "current"
            ]
            == 7.2
        )

        assert (
            situation[
                "glucose"
            ][
                "delta_15m"
            ]
            == -0.4
        )

        assert (
            situation[
                "glucose"
            ][
                "delta_30m"
            ]
            == -0.9
        )

        assert (
            situation[
                "glucose"
            ][
                "delta_60m"
            ]
            == -1.7
        )

        quality = (
            situation[
                "glucose"
            ][
                "data_quality"
            ]
        )

        assert (
            quality[
                "window_minutes"
            ]
            == 120
        )

        assert (
            quality[
                "expected_interval_minutes"
            ]
            == 5
        )

        assert (
            quality[
                "expected_readings"
            ]
            == 25
        )

        assert (
            quality[
                "actual_readings"
            ]
            == 25
        )

        assert (
            quality[
                "coverage_percent"
            ]
            == 100.0
        )

        assert (
            quality[
                "max_gap_minutes"
            ]
            == 5.0
        )

        assert (
            situation[
                "meal"
            ][
                "last_meal_carbs"
            ]
            == 60
        )

        assert (
            situation[
                "meal"
            ][
                "minutes_since_last_meal"
            ]
            == 90
        )

        assert (
            situation[
                "meal"
            ][
                "carbs_last_2h"
            ]
            == 60
        )

        assert (
            situation[
                "meal"
            ][
                "carbs_last_4h"
            ]
            == 60
        )

        assert (
            situation[
                "novorapid"
            ][
                "last_bolus_units"
            ]
            == 6
        )

        assert (
            situation[
                "novorapid"
            ][
                "minutes_since_last_bolus"
            ]
            == 85
        )

        assert (
            situation[
                "novorapid"
            ][
                "units_last_2h"
            ]
            == 6
        )

        assert (
            situation[
                "novorapid"
            ][
                "units_last_4h"
            ]
            == 6
        )

        assert (
            situation[
                "novorapid"
            ][
                "units_last_6h"
            ]
            == 6
        )

        assert (
            situation[
                "novorapid"
            ][
                "estimated_active_units"
            ]
            == pytest.approx(
                3.875,
                abs=0.01
            )
        )

        assert (
            situation[
                "novorapid"
            ][
                "active_duration_minutes"
            ]
            == 240
        )

        assert (
            situation[
                "activity"
            ][
                "type"
            ]
            == "GYM"
        )

        assert (
            situation[
                "activity"
            ][
                "intensity"
            ]
            == "MEDIUM"
        )

        assert (
            situation[
                "activity"
            ][
                "duration_minutes"
            ]
            == 120
        )

        assert (
            situation[
                "activity"
            ][
                "minutes_since_end"
            ]
            == 150
        )

        assert (
            situation[
                "activity"
            ][
                "minutes_last_6h"
            ]
            == 120
        )

        assert (
            situation[
                "activity"
            ][
                "minutes_6_24h"
            ]
            == 0
        )

        assert (
            situation[
                "activity"
            ][
                "minutes_24_48h"
            ]
            == 120
        )

        assert (
            situation[
                "activity"
            ][
                "history_window_hours"
            ]
            == 48
        )

        assert (
            situation[
                "tresiba"
            ][
                "last_basal_units"
            ]
            == 16
        )

        assert (
            situation[
                "tresiba"
            ][
                "minutes_since_last_basal"
            ]
            == 930
        )

        assert (
            situation[
                "time"
            ][
                "hour"
            ]
            == 13
        )

        assert (
            situation[
                "time"
            ][
                "minute"
            ]
            == 30
        )

        assert (
            situation[
                "time"
            ][
                "minutes_from_midnight"
            ]
            == 810
        )

    finally:
        db.close()