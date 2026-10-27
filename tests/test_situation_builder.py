import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.database import SessionLocal
from app.models.activity import Activity
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.meal import Meal
from app.models.user import User
from app.services.situation_builder import build_situation


TZ = ZoneInfo("Europe/Prague")


GLUCOSE_VALUES = [
    7.6,
    7.7,
    7.9,
    8.0,
    8.2,
    8.4,
    8.6,
    8.8,
    8.9,
    9.0,
    9.1,
    9.0,
    8.9,
    8.8,
    8.6,
    8.5,
    8.4,
    8.2,
    8.1,
    8.0,
    7.8,
    7.6,
    7.5,
    7.3,
    7.2,
]


def _seed_isolated_situation(
    db,
    t0: datetime,
) -> User:
    user = User(
        email=(
            f"situation-builder-"
            f"{uuid.uuid4()}@example.com"
        ),
        password_hash="test-only",
        display_name="Situation Builder Test",
        timezone="Europe/Prague",
    )

    db.add(
        user
    )

    db.flush()

    glucose_start = (
        t0
        - timedelta(
            minutes=120
        )
    )

    for index, value in enumerate(
        GLUCOSE_VALUES
    ):
        db.add(
            GlucoseReading(
                user_id=user.id,
                measured_at=(
                    glucose_start
                    + timedelta(
                        minutes=5 * index
                    )
                ),
                value_mmol_l=value,
                source="CGM",
            )
        )

    meal = Meal(
        user_id=user.id,
        eaten_at=(
            t0
            - timedelta(
                minutes=90
            )
        ),
        carbohydrates_g=60,
        description=(
            "Isolated situation builder test meal"
        ),
        note=None,
    )

    db.add(
        meal
    )

    db.add(
        InsulinDose(
            user_id=user.id,
            meal_id=None,
            insulin_type="NOVORAPID",
            units=6,
            administered_at=(
                t0
                - timedelta(
                    minutes=85
                )
            ),
            source="MANUAL",
            note=None,
        )
    )

    basal_time = (
        t0.replace(
            hour=22,
            minute=0,
            second=0,
            microsecond=0,
        )
        - timedelta(
            days=1
        )
    )

    db.add(
        InsulinDose(
            user_id=user.id,
            meal_id=None,
            insulin_type="TRESIBA",
            units=16,
            administered_at=(
                basal_time
            ),
            source="MANUAL",
            note=None,
        )
    )

    db.add(
        Activity(
            user_id=user.id,
            started_at=(
                t0
                - timedelta(
                    minutes=270
                )
            ),
            ended_at=(
                t0
                - timedelta(
                    minutes=150
                )
            ),
            activity_type="GYM",
            intensity="MEDIUM",
            note=None,
        )
    )

    db.add(
        Activity(
            user_id=user.id,
            started_at=(
                t0
                - timedelta(
                    hours=30
                )
            ),
            ended_at=(
                t0
                - timedelta(
                    hours=28
                )
            ),
            activity_type="GYM",
            intensity="MEDIUM",
            note=None,
        )
    )

    db.flush()

    return user


def test_seeded_situation_1330():
    db = SessionLocal()

    try:
        t0 = datetime(
            2026,
            10,
            3,
            13,
            30,
            tzinfo=TZ,
        )

        user = _seed_isolated_situation(
            db=db,
            t0=t0,
        )

        situation = build_situation(
            db=db,
            user_id=user.id,
            t0=t0,
        )

        assert (
            situation["glucose"]["current"]
            == 7.2
        )

        assert (
            situation["glucose"]["delta_15m"]
            == -0.4
        )

        assert (
            situation["glucose"]["delta_30m"]
            == -0.9
        )

        assert (
            situation["glucose"]["delta_60m"]
            == -1.7
        )

        quality = (
            situation["glucose"]["data_quality"]
        )

        assert (
            quality["window_minutes"]
            == 120
        )

        assert (
            quality[
                "expected_interval_minutes"
            ]
            == 5
        )

        assert (
            quality["expected_readings"]
            == 25
        )

        assert (
            quality["actual_readings"]
            == 25
        )

        assert (
            quality["coverage_percent"]
            == 100.0
        )

        assert (
            quality["max_gap_minutes"]
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
                abs=0.01,
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
        db.rollback()
        db.close()