from datetime import datetime, timedelta
from random import Random
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

# ---------------------------------------------------------
# Samostatny synteticky validacni dataset.
#
# 90 dni = warm-up historie
# 60 dni = holdout evaluace
#
# Holdout jsme nepouzili pri vyberu K.
# ---------------------------------------------------------

WARMUP_DAYS = 90
HOLDOUT_DAYS = 60
TOTAL_DAYS = (
    WARMUP_DAYS
    + HOLDOUT_DAYS
)

DATASET_START = datetime(
    2025,
    1,
    2,
    13,
    30,
    tzinfo=TZ
)

CLEANUP_START = datetime(
    2025,
    1,
    1,
    0,
    0,
    tzinfo=TZ
)

CLEANUP_END = datetime(
    2025,
    6,
    2,
    0,
    0,
    tzinfo=TZ
)


BASE_GLUCOSE = [
    7.4,
    7.5,
    7.6,
    7.8,
    7.9,
    8.1,
    8.3,
    8.4,
    8.5,
    8.6,
    8.7,
    8.6,
    8.5,
    8.4,
    8.2,
    8.1,
    8.0,
    7.9,
    7.8,
    7.7,
    7.6,
    7.5,
    7.4,
    7.3,
    7.2
]


ACTIVITY_TYPES = [
    "GYM",
    "TEAM_SPORT",
    "WALK"
]

INTENSITIES = [
    "LOW",
    "MEDIUM",
    "HIGH"
]


def _random_for_day(
    index,
    phase
):
    if phase == "WARMUP":
        seed = (
            10000
            + index * 97
        )

    else:
        seed = (
            50000
            + index * 131
        )

    return Random(
        seed
    )


def _build_parameters(
    index,
    phase
):
    rng = (
        _random_for_day(
            index=index,
            phase=phase
        )
    )

    time_offset = (
        rng.choice([
            -35,
            -25,
            -15,
            -5,
            0,
            5,
            15,
            25,
            35,
            45
        ])
    )

    carbs = (
        rng.choice([
            45,
            50,
            52,
            55,
            58,
            60,
            63,
            65,
            68,
            70,
            74,
            78
        ])
    )

    bolus = (
        rng.choice([
            4.5,
            5.0,
            5.5,
            6.0,
            6.5,
            7.0,
            7.5
        ])
    )

    activity_type = (
        rng.choice(
            ACTIVITY_TYPES
        )
    )

    intensity = (
        rng.choice(
            INTENSITIES
        )
    )

    activity_duration = (
        rng.choice([
            45,
            60,
            75,
            90,
            105,
            120,
            135
        ])
    )

    minutes_since_activity_end = (
        rng.choice([
            90,
            120,
            150,
            180,
            210,
            240
        ])
    )

    meal_minutes_ago = (
        rng.choice([
            60,
            75,
            90,
            105,
            120
        ])
    )

    bolus_minutes_ago = (
        max(
            45,
            meal_minutes_ago
            + rng.choice([
                -10,
                -5,
                0,
                5,
                10
            ])
        )
    )

    basal_units = (
        rng.choice([
            14,
            15,
            16,
            17,
            18
        ])
    )

    glucose_shift = round(
        rng.uniform(
            -0.7,
            0.7
        ),
        2
    )

    trend_factor = round(
        rng.uniform(
            -0.012,
            0.012
        ),
        4
    )

    day_noise = (
        rng.uniform(
            -0.006,
            0.006
        )
    )

    carb_effect = (
        carbs - 60
    ) * 0.0007

    bolus_effect = -(
        bolus - 6
    ) * 0.0065

    if activity_type == "TEAM_SPORT":
        activity_effect = -0.006

    elif activity_type == "GYM":
        activity_effect = -0.0035

    else:
        activity_effect = -0.0015

    if intensity == "HIGH":
        intensity_effect = -0.003

    elif intensity == "LOW":
        intensity_effect = 0.0015

    else:
        intensity_effect = 0.0

    trend_effect = (
        trend_factor
        * 0.35
    )

    linear_step = (
        carb_effect
        + bolus_effect
        + activity_effect
        + intensity_effect
        + trend_effect
        + day_noise
    )

    # Druhy parametr vytvari mirnou nelinearitu
    # ve vyvoji po t0.
    #
    # Jde pouze o synteticky technicky generator,
    # nikoliv fyziologicky model.
    late_effect = (
        (
            carbs - 60
        ) * 0.004
        - (
            bolus - 6
        ) * 0.025
        + rng.uniform(
            -0.12,
            0.12
        )
    )

    return {
        "time_offset":
            time_offset,

        "carbs":
            carbs,

        "bolus":
            bolus,

        "activity_type":
            activity_type,

        "intensity":
            intensity,

        "activity_duration":
            activity_duration,

        "minutes_since_activity_end":
            minutes_since_activity_end,

        "meal_minutes_ago":
            meal_minutes_ago,

        "bolus_minutes_ago":
            bolus_minutes_ago,

        "basal_units":
            basal_units,

        "glucose_shift":
            glucose_shift,

        "trend_factor":
            trend_factor,

        "linear_step":
            linear_step,

        "late_effect":
            late_effect
    }


def _add_glucose_history(
    db,
    user_id,
    t0,
    glucose_shift,
    trend_factor
):
    start = (
        t0
        - timedelta(
            hours=2
        )
    )

    for index, base_value in enumerate(
        BASE_GLUCOSE
    ):
        trend_change = (
            trend_factor
            * (
                index - 12
            )
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
                        minutes=
                            5 * index
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
    linear_step,
    late_effect
):
    for step in range(
        1,
        37
    ):
        progress = (
            step / 36
        )

        linear_change = (
            linear_step
            * step
        )

        curved_change = (
            late_effect
            * (
                progress ** 2
            )
        )

        value = round(
            max(
                3.5,
                starting_glucose
                + linear_change
                + curved_change
            ),
            1
        )

        db.add(
            GlucoseReading(
                user_id=user_id,

                measured_at=(
                    t0
                    + timedelta(
                        minutes=
                            5 * step
                    )
                ),

                value_mmol_l=value,

                source="CGM"
            )
        )


def _delete_existing_dataset(
    db,
    user_id
):
    db.execute(
        delete(
            GlucoseReading
        ).where(
            GlucoseReading.user_id
            == user_id,

            GlucoseReading.measured_at
            >= CLEANUP_START,

            GlucoseReading.measured_at
            < CLEANUP_END
        )
    )

    db.execute(
        delete(
            InsulinDose
        ).where(
            InsulinDose.user_id
            == user_id,

            InsulinDose.administered_at
            >= CLEANUP_START,

            InsulinDose.administered_at
            < CLEANUP_END
        )
    )

    db.execute(
        delete(
            Meal
        ).where(
            Meal.user_id
            == user_id,

            Meal.eaten_at
            >= CLEANUP_START,

            Meal.eaten_at
            < CLEANUP_END
        )
    )

    db.execute(
        delete(
            Activity
        ).where(
            Activity.user_id
            == user_id,

            Activity.ended_at
            >= CLEANUP_START,

            Activity.ended_at
            < CLEANUP_END
        )
    )


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
                "Testovaci uzivatel "
                "nebyl nalezen."
            )
            return

        _delete_existing_dataset(
            db=db,
            user_id=user.id
        )

        holdout_first_time = None
        holdout_last_time = None

        for index in range(
            TOTAL_DAYS
        ):
            if (
                index
                < WARMUP_DAYS
            ):
                phase = "WARMUP"

            else:
                phase = "HOLDOUT"

            parameters = (
                _build_parameters(
                    index=index,
                    phase=phase
                )
            )

            base_t0 = (
                DATASET_START
                + timedelta(
                    days=index
                )
            )

            t0 = (
                base_t0
                + timedelta(
                    minutes=
                        parameters[
                            "time_offset"
                        ]
                )
            )

            if (
                phase
                == "HOLDOUT"
            ):
                if (
                    holdout_first_time
                    is None
                ):
                    holdout_first_time = (
                        t0
                    )

                holdout_last_time = (
                    t0
                )

            _add_glucose_history(
                db=db,
                user_id=user.id,
                t0=t0,
                glucose_shift=
                    parameters[
                        "glucose_shift"
                    ],
                trend_factor=
                    parameters[
                        "trend_factor"
                    ]
            )

            starting_glucose = (
                7.2
                + parameters[
                    "glucose_shift"
                ]
            )

            _add_future_glucose(
                db=db,
                user_id=user.id,
                t0=t0,
                starting_glucose=
                    starting_glucose,
                linear_step=
                    parameters[
                        "linear_step"
                    ],
                late_effect=
                    parameters[
                        "late_effect"
                    ]
            )

            db.add(
                Meal(
                    user_id=user.id,

                    eaten_at=(
                        t0
                        - timedelta(
                            minutes=
                                parameters[
                                    "meal_minutes_ago"
                                ]
                        )
                    ),

                    carbohydrates_g=
                        parameters[
                            "carbs"
                        ],

                    description=(
                        f"{phase} "
                        f"synthetic meal "
                        f"{index + 1}"
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
                            minutes=
                                parameters[
                                    "bolus_minutes_ago"
                                ]
                        )
                    ),

                    source="MANUAL",

                    note=(
                        f"{phase} "
                        f"synthetic bolus "
                        f"{index + 1}"
                    )
                )
            )

            basal_time = (
                t0.replace(
                    hour=22,
                    minute=0,
                    second=0,
                    microsecond=0
                )
                - timedelta(
                    days=1
                )
            )

            db.add(
                InsulinDose(
                    user_id=user.id,

                    insulin_type=
                        "TRESIBA",

                    units=
                        parameters[
                            "basal_units"
                        ],

                    administered_at=
                        basal_time,

                    source="MANUAL",

                    note=(
                        f"{phase} "
                        f"synthetic basal "
                        f"{index + 1}"
                    )
                )
            )

            activity_end = (
                t0
                - timedelta(
                    minutes=
                        parameters[
                            "minutes_since_activity_end"
                        ]
                )
            )

            activity_start = (
                activity_end
                - timedelta(
                    minutes=
                        parameters[
                            "activity_duration"
                        ]
                )
            )

            db.add(
                Activity(
                    user_id=user.id,

                    started_at=
                        activity_start,

                    ended_at=
                        activity_end,

                    activity_type=
                        parameters[
                            "activity_type"
                        ],

                    intensity=
                        parameters[
                            "intensity"
                        ],

                    note=(
                        f"{phase} "
                        f"synthetic activity "
                        f"{index + 1}"
                    )
                )
            )

        db.commit()

        warmup_first_time = (
            DATASET_START
        )

        warmup_last_time = (
            DATASET_START
            + timedelta(
                days=
                    WARMUP_DAYS - 1
            )
        )

        print()
        print(
            "Samostatny holdout dataset "
            "byl vytvoren."
        )

        print(
            "Warm-up dni:",
            WARMUP_DAYS
        )

        print(
            "Holdout dni:",
            HOLDOUT_DAYS
        )

        print(
            "Celkem dni:",
            TOTAL_DAYS
        )

        print()

        print(
            "Warm-up obdobi:"
        )

        print(
            " ",
            warmup_first_time.date(),
            "->",
            warmup_last_time.date()
        )

        print()

        print(
            "Holdout obdobi:"
        )

        print(
            " ",
            holdout_first_time.date(),
            "->",
            holdout_last_time.date()
        )

        print()
        print(
            "Dataset z roku 2026 "
            "zustal nedotceny."
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()