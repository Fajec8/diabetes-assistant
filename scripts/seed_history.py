from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models.activity import Activity
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.meal import Meal
from app.models.user import User


EMAIL = "test@example.com"
TZ = ZoneInfo("Europe/Prague")

HISTORY_DAYS = 60
ORIGINAL_HISTORY_DAYS = 12

BASE_GLUCOSE = [
    7.6, 7.7, 7.9, 8.0, 8.2,
    8.4, 8.6, 8.8, 8.9, 9.0,
    9.1, 9.0, 8.9, 8.8, 8.6,
    8.5, 8.4, 8.2, 8.1, 8.0,
    7.8, 7.6, 7.5, 7.3, 7.2
]

TIME_OFFSETS = [
    -20, -10, 0, 10,
    20, -15, 5, 15,
    30, -30, 45, 0
]

CARBS = [
    55, 60, 65, 60,
    50, 70, 60, 55,
    65, 60, 50, 60
]

BOLUSES = [
    5.5, 6.0, 6.5, 6.0,
    5.0, 7.0, 6.0, 5.5,
    6.5, 6.0, 5.0, 6.0
]


def _add_glucose_history(
    db,
    user_id,
    t0,
    glucose_shift,
    trend_factor
):
    start = (
        t0
        - timedelta(hours=2)
    )

    for j, base_value in enumerate(
        BASE_GLUCOSE
    ):
        trend_change = (
            trend_factor
            * (j - 12)
        )

        value = round(
            base_value
            + glucose_shift
            + trend_change,
            1
        )

        db.add(
            GlucoseReading(
                user_id=user_id,
                measured_at=(
                    start
                    + timedelta(
                        minutes=5 * j
                    )
                ),
                value_mmol_l=value,
                source="CGM"
            )
        )


def _add_future_glucose(
    db,
    user_id,
    t0,
    starting_glucose,
    future_step
):
    for k in range(
        1,
        37
    ):
        value = round(
            max(
                3.5,
                starting_glucose
                + future_step * k
            ),
            1
        )

        db.add(
            GlucoseReading(
                user_id=user_id,
                measured_at=(
                    t0
                    + timedelta(
                        minutes=5 * k
                    )
                ),
                value_mmol_l=value,
                source="CGM"
            )
        )


def _old_history_parameters(
    old_index
):
    time_offset = (
        TIME_OFFSETS[
            old_index
        ]
    )

    carbs = (
        CARBS[
            old_index
        ]
    )

    bolus = (
        BOLUSES[
            old_index
        ]
    )

    glucose_shift = (
        (
            old_index % 5
        )
        - 2
    ) * 0.15

    trend_factor = (
        (
            old_index % 3
        )
        - 1
    ) * 0.005

    future_step = (
        (
            old_index % 5
        )
        - 2
    ) * 0.025

    activity_type = (
        "GYM"
        if old_index % 4 != 0
        else "TEAM_SPORT"
    )

    intensity = "MEDIUM"

    return {
        "time_offset":
            time_offset,

        "carbs":
            carbs,

        "bolus":
            bolus,

        "glucose_shift":
            glucose_shift,

        "trend_factor":
            trend_factor,

        "future_step":
            future_step,

        "activity_type":
            activity_type,

        "intensity":
            intensity
    }


def _extended_history_parameters(
    index
):
    time_offset_pattern = [
        -30,
        -15,
        0,
        15,
        30,
        -20,
        10,
        20
    ]

    carb_pattern = [
        45,
        50,
        55,
        60,
        65,
        70,
        75,
        60
    ]

    bolus_pattern = [
        4.5,
        5.0,
        5.5,
        6.0,
        6.5,
        7.0,
        7.5,
        6.0
    ]

    activity_pattern = [
        "GYM",
        "GYM",
        "TEAM_SPORT",
        "GYM",
        "WALK",
        "GYM"
    ]

    intensity_pattern = [
        "LOW",
        "MEDIUM",
        "MEDIUM",
        "HIGH",
        "MEDIUM",
        "MEDIUM"
    ]

    time_offset = (
        time_offset_pattern[
            index
            % len(
                time_offset_pattern
            )
        ]
    )

    carbs = (
        carb_pattern[
            index
            % len(
                carb_pattern
            )
        ]
    )

    bolus = (
        bolus_pattern[
            (
                index * 3
                + 1
            )
            % len(
                bolus_pattern
            )
        ]
    )

    activity_type = (
        activity_pattern[
            index
            % len(
                activity_pattern
            )
        ]
    )

    intensity = (
        intensity_pattern[
            (
                index * 2
                + 1
            )
            % len(
                intensity_pattern
            )
        ]
    )

    glucose_shift = (
        (
            index % 9
        )
        - 4
    ) * 0.1

    trend_factor = (
        (
            index % 5
        )
        - 2
    ) * 0.004

    carb_effect = (
        carbs - 60
    ) * 0.0008

    bolus_effect = -(
        bolus - 6
    ) * 0.007

    if activity_type == "TEAM_SPORT":
        activity_effect = -0.008

    elif activity_type == "GYM":
        activity_effect = -0.004

    elif activity_type == "WALK":
        activity_effect = -0.002

    else:
        activity_effect = 0.0

    if intensity == "HIGH":
        intensity_effect = -0.004

    elif intensity == "LOW":
        intensity_effect = 0.002

    else:
        intensity_effect = 0.0

    day_variation = (
        (
            index % 7
        )
        - 3
    ) * 0.002

    future_step = (
        carb_effect
        + bolus_effect
        + activity_effect
        + intensity_effect
        + day_variation
    )

    return {
        "time_offset":
            time_offset,

        "carbs":
            carbs,

        "bolus":
            bolus,

        "glucose_shift":
            glucose_shift,

        "trend_factor":
            trend_factor,

        "future_step":
            future_step,

        "activity_type":
            activity_type,

        "intensity":
            intensity
    }


def main():
    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(
                User.email
                == EMAIL
            )
        )

        if user is None:
            print(
                "Testovaci uzivatel nebyl nalezen."
            )
            return

        cutoff = datetime(
            2026,
            10,
            3,
            0,
            0,
            tzinfo=TZ
        )

        db.execute(
            delete(
                GlucoseReading
            ).where(
                GlucoseReading.user_id
                == user.id,

                GlucoseReading.measured_at
                < cutoff
            )
        )

        db.execute(
            delete(
                InsulinDose
            ).where(
                InsulinDose.user_id
                == user.id,

                InsulinDose.administered_at
                < cutoff
            )
        )

        db.execute(
            delete(
                Meal
            ).where(
                Meal.user_id
                == user.id,

                Meal.eaten_at
                < cutoff
            )
        )

        db.execute(
            delete(
                Activity
            ).where(
                Activity.user_id
                == user.id,

                Activity.ended_at
                < cutoff
            )
        )

        original_first_day = datetime(
            2026,
            9,
            21,
            13,
            30,
            tzinfo=TZ
        )

        extended_days = (
            HISTORY_DAYS
            - ORIGINAL_HISTORY_DAYS
        )

        first_day = (
            original_first_day
            - timedelta(
                days=extended_days
            )
        )

        for i in range(
            HISTORY_DAYS
        ):
            if i < extended_days:
                parameters = (
                    _extended_history_parameters(
                        i
                    )
                )

                description_number = (
                    i + 1
                )

            else:
                old_index = (
                    i
                    - extended_days
                )

                parameters = (
                    _old_history_parameters(
                        old_index
                    )
                )

                description_number = (
                    i + 1
                )

            t0 = (
                first_day
                + timedelta(
                    days=i
                )
                + timedelta(
                    minutes=parameters[
                        "time_offset"
                    ]
                )
            )

            glucose_shift = (
                parameters[
                    "glucose_shift"
                ]
            )

            _add_glucose_history(
                db=db,
                user_id=user.id,
                t0=t0,
                glucose_shift=
                    glucose_shift,
                trend_factor=
                    parameters[
                        "trend_factor"
                    ]
            )

            starting_glucose = (
                7.2
                + glucose_shift
            )

            _add_future_glucose(
                db=db,
                user_id=user.id,
                t0=t0,
                starting_glucose=
                    starting_glucose,
                future_step=
                    parameters[
                        "future_step"
                    ]
            )

            db.add(
                Meal(
                    user_id=user.id,
                    eaten_at=(
                        t0
                        - timedelta(
                            minutes=90
                        )
                    ),
                    carbohydrates_g=
                        parameters[
                            "carbs"
                        ],
                    description=(
                        f"Historicke jidlo "
                        f"{description_number}"
                    ),
                    note=None
                )
            )

            db.add(
                InsulinDose(
                    user_id=user.id,
                    insulin_type=
                        "NOVORAPID",
                    units=
                        parameters[
                            "bolus"
                        ],
                    administered_at=(
                        t0
                        - timedelta(
                            minutes=85
                        )
                    ),
                    source="MANUAL",
                    note=None
                )
            )

            db.add(
                InsulinDose(
                    user_id=user.id,
                    insulin_type=
                        "TRESIBA",
                    units=16,
                    administered_at=(
                        t0.replace(
                            hour=22,
                            minute=0
                        )
                        - timedelta(
                            days=1
                        )
                    ),
                    source="MANUAL",
                    note=None
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
                    activity_type=
                        parameters[
                            "activity_type"
                        ],
                    intensity=
                        parameters[
                            "intensity"
                        ],
                    note=None
                )
            )

        db.add(
            InsulinDose(
                user_id=user.id,
                insulin_type="TRESIBA",
                units=16,
                administered_at=datetime(
                    2026,
                    10,
                    2,
                    22,
                    0,
                    tzinfo=TZ
                ),
                source="MANUAL",
                note=(
                    "Aktualni testovaci basal"
                )
            )
        )

        db.commit()

        print(
            "Historicka testovaci data vytvorena."
        )

        print(
            "Pocet historickych dnu:",
            HISTORY_DAYS
        )

        print(
            "Prvni historicky den:",
            first_day.date()
        )

        print(
            "Posledni historicky den:",
            (
                first_day
                + timedelta(
                    days=HISTORY_DAYS - 1
                )
            ).date()
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()