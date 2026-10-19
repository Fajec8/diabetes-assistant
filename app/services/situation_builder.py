from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.activity import Activity
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.meal import Meal
from app.models.user import User
from app.services.meal_bolus_analysis import (
    analyze_meal_bolus,
)


MAX_GLUCOSE_GAP = timedelta(
    minutes=10
)

CGM_EXPECTED_INTERVAL_MINUTES = 5
CGM_QUALITY_WINDOW_MINUTES = 120

NOVORAPID_ACTIVE_DURATION_MINUTES = 240

ACTIVITY_HISTORY_HOURS = 48


def _latest_glucose(
    db: Session,
    user_id,
    timestamp: datetime
):
    reading = db.scalar(
        select(
            GlucoseReading
        )
        .where(
            GlucoseReading.user_id
            == user_id,

            GlucoseReading.measured_at
            <= timestamp
        )
        .order_by(
            GlucoseReading.measured_at.desc()
        )
        .limit(
            1
        )
    )

    if reading is None:
        return None

    if (
        timestamp
        - reading.measured_at
        > MAX_GLUCOSE_GAP
    ):
        return None

    return reading


def _glucose_delta(
    db: Session,
    user_id,
    t0: datetime,
    minutes: int
):
    current = (
        _latest_glucose(
            db,
            user_id,
            t0
        )
    )

    previous = (
        _latest_glucose(
            db,
            user_id,
            t0
            - timedelta(
                minutes=
                    minutes
            )
        )
    )

    if (
        current is None
        or previous is None
    ):
        return None

    return round(
        current.value_mmol_l
        - previous.value_mmol_l,
        2
    )


def _glucose_data_quality(
    db: Session,
    user_id,
    t0: datetime
):
    window_start = (
        t0
        - timedelta(
            minutes=
                CGM_QUALITY_WINDOW_MINUTES
        )
    )

    readings = db.scalars(
        select(
            GlucoseReading
        )
        .where(
            GlucoseReading.user_id
            == user_id,

            GlucoseReading.measured_at
            >= window_start,

            GlucoseReading.measured_at
            <= t0
        )
        .order_by(
            GlucoseReading.measured_at
        )
    ).all()

    expected_readings = (
        CGM_QUALITY_WINDOW_MINUTES
        // CGM_EXPECTED_INTERVAL_MINUTES
        + 1
    )

    actual_readings = len(
        readings
    )

    coverage_percent = min(
        actual_readings
        / expected_readings
        * 100,
        100.0
    )

    if not readings:
        max_gap_minutes = float(
            CGM_QUALITY_WINDOW_MINUTES
        )

    else:
        timestamps = [
            window_start
        ]

        timestamps.extend(
            reading.measured_at
            for reading
            in readings
        )

        timestamps.append(
            t0
        )

        gaps = []

        for index in range(
            len(
                timestamps
            ) - 1
        ):
            gap = (
                timestamps[
                    index + 1
                ]
                - timestamps[
                    index
                ]
            ).total_seconds() / 60

            gaps.append(
                gap
            )

        max_gap_minutes = max(
            gaps
        )

    return {
        "window_minutes":
            CGM_QUALITY_WINDOW_MINUTES,

        "expected_interval_minutes":
            CGM_EXPECTED_INTERVAL_MINUTES,

        "expected_readings":
            expected_readings,

        "actual_readings":
            actual_readings,

        "coverage_percent":
            round(
                coverage_percent,
                1
            ),

        "max_gap_minutes":
            round(
                max_gap_minutes,
                1
            )
    }


def _sum_carbs(
    db: Session,
    user_id,
    t0: datetime,
    hours: int
):
    value = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    Meal.carbohydrates_g
                ),
                0.0
            )
        )
        .where(
            Meal.user_id
            == user_id,

            Meal.eaten_at
            > (
                t0
                - timedelta(
                    hours=
                        hours
                )
            ),

            Meal.eaten_at
            <= t0
        )
    )

    return float(
        value
    )


def _sum_novorapid(
    db: Session,
    user_id,
    t0: datetime,
    hours: int
):
    value = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    InsulinDose.units
                ),
                0.0
            )
        )
        .where(
            InsulinDose.user_id
            == user_id,

            InsulinDose.insulin_type
            == "NOVORAPID",

            InsulinDose.administered_at
            > (
                t0
                - timedelta(
                    hours=
                        hours
                )
            ),

            InsulinDose.administered_at
            <= t0
        )
    )

    return float(
        value
    )


def _estimate_active_novorapid(
    db: Session,
    user_id,
    t0: datetime
):
    window_start = (
        t0
        - timedelta(
            minutes=
                NOVORAPID_ACTIVE_DURATION_MINUTES
        )
    )

    doses = db.scalars(
        select(
            InsulinDose
        )
        .where(
            InsulinDose.user_id
            == user_id,

            InsulinDose.insulin_type
            == "NOVORAPID",

            InsulinDose.administered_at
            > window_start,

            InsulinDose.administered_at
            <= t0
        )
    ).all()

    active_units = 0.0

    for dose in doses:
        minutes_since_dose = (
            t0
            - dose.administered_at
        ).total_seconds() / 60

        if (
            minutes_since_dose
            < 0
            or minutes_since_dose
            >= NOVORAPID_ACTIVE_DURATION_MINUTES
        ):
            continue

        remaining_fraction = (
            1.0
            - (
                minutes_since_dose
                / NOVORAPID_ACTIVE_DURATION_MINUTES
            )
        )

        active_units += (
            dose.units
            * remaining_fraction
        )

    return round(
        active_units,
        2
    )


def _activity_minutes_in_window(
    db: Session,
    user_id,
    t0: datetime,
    older_hours: int,
    newer_hours: int
):
    window_start = (
        t0
        - timedelta(
            hours=
                older_hours
        )
    )

    window_end = (
        t0
        - timedelta(
            hours=
                newer_hours
        )
    )

    activities = db.scalars(
        select(
            Activity
        )
        .where(
            Activity.user_id
            == user_id,

            Activity.started_at
            < window_end,

            Activity.ended_at
            > window_start
        )
    ).all()

    total_minutes = 0.0

    for activity in activities:
        overlap_start = max(
            activity.started_at,
            window_start
        )

        overlap_end = min(
            activity.ended_at,
            window_end
        )

        if (
            overlap_end
            > overlap_start
        ):
            total_minutes += (
                overlap_end
                - overlap_start
            ).total_seconds() / 60

    return round(
        total_minutes
    )


def _activity_minutes_last_6h(
    db: Session,
    user_id,
    t0: datetime
):
    return (
        _activity_minutes_in_window(
            db=db,
            user_id=user_id,
            t0=t0,
            older_hours=6,
            newer_hours=0
        )
    )


def _activity_minutes_6_24h(
    db: Session,
    user_id,
    t0: datetime
):
    return (
        _activity_minutes_in_window(
            db=db,
            user_id=user_id,
            t0=t0,
            older_hours=24,
            newer_hours=6
        )
    )


def _activity_minutes_24_48h(
    db: Session,
    user_id,
    t0: datetime
):
    return (
        _activity_minutes_in_window(
            db=db,
            user_id=user_id,
            t0=t0,
            older_hours=48,
            newer_hours=24
        )
    )


def _meal_items(
    meal
):
    if meal is None:
        return []

    return [
        {
            "id":
                item.id,

            "food_name":
                item.food_name,

            "preparation":
                item.preparation,

            "variant":
                item.variant,

            "amount_g":
                item.amount_g,

            "carbohydrates_g":
                item.carbohydrates_g,

            "note":
                item.note
        }
        for item
        in meal.items
    ]


def build_situation(
    db: Session,
    user_id,
    t0: datetime
):
    user = db.get(
        User,
        user_id
    )

    if user is None:
        raise ValueError(
            "User not found"
        )

    timezone = ZoneInfo(
        user.timezone
    )

    local_t0 = (
        t0.astimezone(
            timezone
        )
    )

    current_glucose = (
        _latest_glucose(
            db,
            user_id,
            t0
        )
    )

    glucose_data_quality = (
        _glucose_data_quality(
            db,
            user_id,
            t0
        )
    )

    last_meal = db.scalar(
        select(
            Meal
        )
        .options(
            selectinload(
                Meal.items
            )
        )
        .where(
            Meal.user_id
            == user_id,

            Meal.eaten_at
            <= t0
        )
        .order_by(
            Meal.eaten_at.desc()
        )
        .limit(
            1
        )
    )

    last_meal_bolus = None

    if last_meal is not None:
        last_meal_bolus = (
            analyze_meal_bolus(
                db=db,
                meal_id=last_meal.id,
                as_of=t0
            )
        )

    last_bolus = db.scalar(
        select(
            InsulinDose
        )
        .where(
            InsulinDose.user_id
            == user_id,

            InsulinDose.insulin_type
            == "NOVORAPID",

            InsulinDose.administered_at
            <= t0
        )
        .order_by(
            InsulinDose.administered_at.desc()
        )
        .limit(
            1
        )
    )

    last_basal = db.scalar(
        select(
            InsulinDose
        )
        .where(
            InsulinDose.user_id
            == user_id,

            InsulinDose.insulin_type
            == "TRESIBA",

            InsulinDose.administered_at
            <= t0
        )
        .order_by(
            InsulinDose.administered_at.desc()
        )
        .limit(
            1
        )
    )

    activity_history_start = (
        t0
        - timedelta(
            hours=
                ACTIVITY_HISTORY_HOURS
        )
    )

    last_activity = db.scalar(
        select(
            Activity
        )
        .where(
            Activity.user_id
            == user_id,

            Activity.ended_at
            <= t0,

            Activity.ended_at
            > activity_history_start
        )
        .order_by(
            Activity.ended_at.desc()
        )
        .limit(
            1
        )
    )

    return {
        "timestamp":
            local_t0.isoformat(),

        "glucose": {
            "current": (
                current_glucose.value_mmol_l
                if current_glucose
                else None
            ),

            "delta_15m":
                _glucose_delta(
                    db,
                    user_id,
                    t0,
                    15
                ),

            "delta_30m":
                _glucose_delta(
                    db,
                    user_id,
                    t0,
                    30
                ),

            "delta_60m":
                _glucose_delta(
                    db,
                    user_id,
                    t0,
                    60
                ),

            "data_quality":
                glucose_data_quality
        },

        "meal": {
            # ---------------------------------------------
            # Puvodni features.
            #
            # Tyto nadale pouziva soucasny
            # similarity engine.
            # ---------------------------------------------

            "last_meal_carbs": (
                last_meal.carbohydrates_g
                if last_meal
                else None
            ),

            "minutes_since_last_meal": (
                round(
                    (
                        t0
                        - last_meal.eaten_at
                    ).total_seconds() / 60
                )
                if last_meal
                else None
            ),

            "carbs_last_2h":
                _sum_carbs(
                    db,
                    user_id,
                    t0,
                    2
                ),

            "carbs_last_4h":
                _sum_carbs(
                    db,
                    user_id,
                    t0,
                    4
                ),

            # ---------------------------------------------
            # Nove kontextove informace.
            #
            # Zatim NEVSTUPUJI do similarity score.
            # ---------------------------------------------

            "last_meal_id": (
                last_meal.id
                if last_meal
                else None
            ),

            "last_meal_description": (
                last_meal.description
                if last_meal
                else None
            ),

            "last_meal_note": (
                last_meal.note
                if last_meal
                else None
            ),

            "items":
                _meal_items(
                    last_meal
                ),

            "linked_bolus":
                last_meal_bolus
        },

        "novorapid": {
            "last_bolus_units": (
                last_bolus.units
                if last_bolus
                else None
            ),

            "minutes_since_last_bolus": (
                round(
                    (
                        t0
                        - last_bolus.administered_at
                    ).total_seconds() / 60
                )
                if last_bolus
                else None
            ),

            "units_last_2h":
                _sum_novorapid(
                    db,
                    user_id,
                    t0,
                    2
                ),

            "units_last_4h":
                _sum_novorapid(
                    db,
                    user_id,
                    t0,
                    4
                ),

            "units_last_6h":
                _sum_novorapid(
                    db,
                    user_id,
                    t0,
                    6
                ),

            "estimated_active_units":
                _estimate_active_novorapid(
                    db,
                    user_id,
                    t0
                ),

            "active_duration_minutes":
                NOVORAPID_ACTIVE_DURATION_MINUTES
        },

        "activity": {
            "type": (
                last_activity.activity_type
                if last_activity
                else None
            ),

            "intensity": (
                last_activity.intensity
                if last_activity
                else None
            ),

            "duration_minutes": (
                round(
                    (
                        last_activity.ended_at
                        - last_activity.started_at
                    ).total_seconds() / 60
                )
                if last_activity
                else None
            ),

            "minutes_since_end": (
                round(
                    (
                        t0
                        - last_activity.ended_at
                    ).total_seconds() / 60
                )
                if last_activity
                else None
            ),

            "minutes_last_6h":
                _activity_minutes_last_6h(
                    db,
                    user_id,
                    t0
                ),

            "minutes_6_24h":
                _activity_minutes_6_24h(
                    db,
                    user_id,
                    t0
                ),

            "minutes_24_48h":
                _activity_minutes_24_48h(
                    db,
                    user_id,
                    t0
                ),

            "history_window_hours":
                ACTIVITY_HISTORY_HOURS
        },

        "tresiba": {
            "last_basal_units": (
                last_basal.units
                if last_basal
                else None
            ),

            "minutes_since_last_basal": (
                round(
                    (
                        t0
                        - last_basal.administered_at
                    ).total_seconds() / 60
                )
                if last_basal
                else None
            )
        },

        "time": {
            "hour":
                local_t0.hour,

            "minute":
                local_t0.minute,

            "minutes_from_midnight": (
                local_t0.hour * 60
                + local_t0.minute
            )
        }
    }