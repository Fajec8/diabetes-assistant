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

WARMUP_DAYS = 90
HOLDOUT_DAYS = 60

TOTAL_DAYS = (
    WARMUP_DAYS
    + HOLDOUT_DAYS
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


DATASETS = [
    {
        "name":
            "A_BALANCED",

        "start":
            datetime(
                2022,
                1,
                2,
                13,
                30,
                tzinfo=TZ
            ),

        "seed":
            11000,

        "carbs":
            [
                45,
                50,
                55,
                60,
                65,
                70,
                75
            ],

        "boluses":
            [
                4.5,
                5.0,
                5.5,
                6.0,
                6.5,
                7.0,
                7.5
            ],

        "activity_probability":
            0.75,

        "activity_durations":
            [
                45,
                60,
                75,
                90,
                120
            ],

        "activity_end_minutes":
            [
                90,
                120,
                150,
                180,
                210,
                240
            ],

        "glucose_shift":
            0.7,

        "trend_range":
            0.012,

        "outcome_noise":
            0.006,

        "carb_coefficient":
            0.0007,

        "bolus_coefficient":
            0.0065,

        "previous_activity_coefficient":
            -0.000010,

        "missing_cgm_probability":
            0.00,

        "extra_meal_probability":
            0.15,

        "extra_bolus_probability":
            0.15
    },

    {
        "name":
            "B_MEAL_BOLUS",

        "start":
            datetime(
                2022,
                10,
                2,
                13,
                30,
                tzinfo=TZ
            ),

        "seed":
            22000,

        "carbs":
            [
                30,
                40,
                50,
                60,
                70,
                80,
                90,
                100
            ],

        "boluses":
            [
                3.0,
                4.0,
                5.0,
                6.0,
                7.0,
                8.0,
                9.0
            ],

        "activity_probability":
            0.65,

        "activity_durations":
            [
                45,
                60,
                75,
                90,
                120
            ],

        "activity_end_minutes":
            [
                90,
                120,
                150,
                180,
                240
            ],

        "glucose_shift":
            0.9,

        "trend_range":
            0.014,

        "outcome_noise":
            0.008,

        "carb_coefficient":
            0.0009,

        "bolus_coefficient":
            0.0075,

        "previous_activity_coefficient":
            -0.000008,

        "missing_cgm_probability":
            0.00,

        "extra_meal_probability":
            0.35,

        "extra_bolus_probability":
            0.30
    },

    {
        "name":
            "C_ACTIVITY",

        "start":
            datetime(
                2023,
                8,
                2,
                13,
                30,
                tzinfo=TZ
            ),

        "seed":
            33000,

        "carbs":
            [
                45,
                50,
                55,
                60,
                65,
                70
            ],

        "boluses":
            [
                4.5,
                5.0,
                5.5,
                6.0,
                6.5,
                7.0
            ],

        "activity_probability":
            0.90,

        "activity_durations":
            [
                45,
                60,
                90,
                120,
                150,
                180
            ],

        "activity_end_minutes":
            [
                60,
                90,
                120,
                150,
                180,
                240,
                300
            ],

        "glucose_shift":
            0.7,

        "trend_range":
            0.012,

        "outcome_noise":
            0.006,

        "carb_coefficient":
            0.0007,

        "bolus_coefficient":
            0.0065,

        # Tento scenar dava v syntetickem
        # generatoru vetsi vyznam aktivite
        # z predchoziho dne.
        "previous_activity_coefficient":
            -0.000030,

        "missing_cgm_probability":
            0.00,

        "extra_meal_probability":
            0.10,

        "extra_bolus_probability":
            0.10
    },

    {
        "name":
            "D_NOISY",

        "start":
            datetime(
                2024,
                5,
                2,
                13,
                30,
                tzinfo=TZ
            ),

        "seed":
            44000,

        "carbs":
            [
                35,
                45,
                50,
                55,
                60,
                65,
                75,
                85
            ],

        "boluses":
            [
                3.5,
                4.5,
                5.0,
                5.5,
                6.0,
                6.5,
                7.5,
                8.0
            ],

        "activity_probability":
            0.55,

        "activity_durations":
            [
                30,
                45,
                60,
                75,
                90,
                120
            ],

        "activity_end_minutes":
            [
                60,
                90,
                120,
                180,
                240,
                300,
                360
            ],

        "glucose_shift":
            1.2,

        "trend_range":
            0.020,

        "outcome_noise":
            0.014,

        "carb_coefficient":
            0.0006,

        "bolus_coefficient":
            0.0060,

        "previous_activity_coefficient":
            -0.000012,

        # Chybi pouze nektere body
        # pred t0. Future outcome
        # zustava kompletni.
        "missing_cgm_probability":
            0.08,

        "extra_meal_probability":
            0.25,

        "extra_bolus_probability":
            0.25
    }
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

TIME_OFFSETS = [
    -45,
    -30,
    -15,
    0,
    15,
    30,
    45
]


def _add_glucose_history(
    db,
    user_id,
    t0,
    glucose_shift,
    trend_factor,
    missing_probability,
    rng
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
        # Bod presne v t0 nikdy
        # nevynechavame.
        if (
            index != 24
            and missing_probability > 0
            and rng.random()
            < missing_probability
        ):
            continue

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


def _delete_dataset(
    db,
    user_id,
    dataset
):
    start = (
        dataset["start"]
        - timedelta(
            days=2
        )
    )

    end = (
        dataset["start"]
        + timedelta(
            days=TOTAL_DAYS + 2
        )
    )

    db.execute(
        delete(
            GlucoseReading
        ).where(
            GlucoseReading.user_id
            == user_id,

            GlucoseReading.measured_at
            >= start,

            GlucoseReading.measured_at
            < end
        )
    )

    db.execute(
        delete(
            Meal
        ).where(
            Meal.user_id
            == user_id,

            Meal.eaten_at
            >= start,

            Meal.eaten_at
            < end
        )
    )

    db.execute(
        delete(
            InsulinDose
        ).where(
            InsulinDose.user_id
            == user_id,

            InsulinDose.administered_at
            >= start,

            InsulinDose.administered_at
            < end
        )
    )

    db.execute(
        delete(
            Activity
        ).where(
            Activity.user_id
            == user_id,

            Activity.ended_at
            >= start,

            Activity.ended_at
            < end
        )
    )


def _build_day_parameters(
    dataset,
    day_index,
    previous_activity_minutes
):
    rng = Random(
        dataset["seed"]
        + day_index * 137
    )

    carbs = (
        rng.choice(
            dataset[
                "carbs"
            ]
        )
    )

    bolus = (
        rng.choice(
            dataset[
                "boluses"
            ]
        )
    )

    time_offset = (
        rng.choice(
            TIME_OFFSETS
        )
    )

    glucose_shift = (
        rng.uniform(
            -dataset[
                "glucose_shift"
            ],
            dataset[
                "glucose_shift"
            ]
        )
    )

    trend_factor = (
        rng.uniform(
            -dataset[
                "trend_range"
            ],
            dataset[
                "trend_range"
            ]
        )
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

    has_activity = (
        rng.random()
        < dataset[
            "activity_probability"
        ]
    )

    activity_type = None
    intensity = None
    activity_duration = 0
    activity_end_minutes = None

    if has_activity:
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
            rng.choice(
                dataset[
                    "activity_durations"
                ]
            )
        )

        activity_end_minutes = (
            rng.choice(
                dataset[
                    "activity_end_minutes"
                ]
            )
        )

    extra_meal = (
        rng.random()
        < dataset[
            "extra_meal_probability"
        ]
    )

    extra_meal_carbs = 0

    if extra_meal:
        extra_meal_carbs = (
            rng.choice([
                10,
                15,
                20,
                25,
                30
            ])
        )

    extra_bolus = (
        rng.random()
        < dataset[
            "extra_bolus_probability"
        ]
    )

    extra_bolus_units = 0.0

    if extra_bolus:
        extra_bolus_units = (
            rng.choice([
                0.5,
                1.0,
                1.5,
                2.0
            ])
        )

    carb_effect = (
        (
            carbs
            + extra_meal_carbs * 0.35
            - 60
        )
        * dataset[
            "carb_coefficient"
        ]
    )

    bolus_effect = -(
        (
            bolus
            + extra_bolus_units * 0.40
            - 6
        )
        * dataset[
            "bolus_coefficient"
        ]
    )

    activity_effect = 0.0

    if activity_type == "TEAM_SPORT":
        activity_effect = -0.006

    elif activity_type == "GYM":
        activity_effect = -0.0035

    elif activity_type == "WALK":
        activity_effect = -0.0015

    intensity_effect = 0.0

    if intensity == "HIGH":
        intensity_effect = -0.003

    elif intensity == "LOW":
        intensity_effect = 0.0015

    previous_activity_effect = (
        previous_activity_minutes
        * dataset[
            "previous_activity_coefficient"
        ]
    )

    trend_effect = (
        trend_factor
        * 0.35
    )

    random_effect = (
        rng.uniform(
            -dataset[
                "outcome_noise"
            ],
            dataset[
                "outcome_noise"
            ]
        )
    )

    linear_step = (
        carb_effect
        + bolus_effect
        + activity_effect
        + intensity_effect
        + previous_activity_effect
        + trend_effect
        + random_effect
    )

    late_effect = (
        (
            carbs - 60
        ) * 0.004
        - (
            bolus - 6
        ) * 0.025
        + rng.uniform(
            -0.15,
            0.15
        )
    )

    return {
        "rng":
            rng,

        "time_offset":
            time_offset,

        "carbs":
            carbs,

        "bolus":
            bolus,

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

        "has_activity":
            has_activity,

        "activity_type":
            activity_type,

        "intensity":
            intensity,

        "activity_duration":
            activity_duration,

        "activity_end_minutes":
            activity_end_minutes,

        "extra_meal":
            extra_meal,

        "extra_meal_carbs":
            extra_meal_carbs,

        "extra_bolus":
            extra_bolus,

        "extra_bolus_units":
            extra_bolus_units,

        "linear_step":
            linear_step,

        "late_effect":
            late_effect
    }


def _seed_dataset(
    db,
    user,
    dataset
):
    previous_activity_minutes = 0

    for day_index in range(
        TOTAL_DAYS
    ):
        if (
            day_index
            < WARMUP_DAYS
        ):
            phase = "WARMUP"

        else:
            phase = "HOLDOUT"

        parameters = (
            _build_day_parameters(
                dataset=
                    dataset,

                day_index=
                    day_index,

                previous_activity_minutes=
                    previous_activity_minutes
            )
        )

        base_t0 = (
            dataset[
                "start"
            ]
            + timedelta(
                days=
                    day_index
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
                ],

            missing_probability=
                dataset[
                    "missing_cgm_probability"
                ],

            rng=
                parameters[
                    "rng"
                ]
        )

        starting_glucose = (
            7.2
            + parameters[
                "glucose_shift"
            ]
            + parameters[
                "trend_factor"
            ] * 12
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
                    f"{dataset['name']} "
                    f"{phase} main meal "
                    f"{day_index + 1}"
                ),

                note=None
            )
        )

        if (
            parameters[
                "extra_meal"
            ]
        ):
            db.add(
                Meal(
                    user_id=user.id,

                    eaten_at=(
                        t0
                        - timedelta(
                            minutes=210
                        )
                    ),

                    carbohydrates_g=
                        parameters[
                            "extra_meal_carbs"
                        ],

                    description=(
                        f"{dataset['name']} "
                        f"{phase} extra meal "
                        f"{day_index + 1}"
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
                    f"{dataset['name']} "
                    f"{phase} main bolus "
                    f"{day_index + 1}"
                )
            )
        )

        if (
            parameters[
                "extra_bolus"
            ]
        ):
            db.add(
                InsulinDose(
                    user_id=user.id,

                    insulin_type=
                        "NOVORAPID",

                    units=
                        parameters[
                            "extra_bolus_units"
                        ],

                    administered_at=(
                        t0
                        - timedelta(
                            minutes=200
                        )
                    ),

                    source="MANUAL",

                    note=(
                        f"{dataset['name']} "
                        f"{phase} extra bolus "
                        f"{day_index + 1}"
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
                    f"{dataset['name']} "
                    f"{phase} basal "
                    f"{day_index + 1}"
                )
            )
        )

        if (
            parameters[
                "has_activity"
            ]
        ):
            activity_end = (
                t0
                - timedelta(
                    minutes=
                        parameters[
                            "activity_end_minutes"
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
                        f"{dataset['name']} "
                        f"{phase} activity "
                        f"{day_index + 1}"
                    )
                )
            )

            previous_activity_minutes = (
                parameters[
                    "activity_duration"
                ]
            )

        else:
            previous_activity_minutes = 0


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

        print()
        print(
            "MULTI-DATASET VALIDATION SEED"
        )

        print(
            "=" * 78
        )

        for dataset in DATASETS:
            _delete_dataset(
                db=db,
                user_id=user.id,
                dataset=dataset
            )

            _seed_dataset(
                db=db,
                user=user,
                dataset=dataset
            )

        db.commit()

        for dataset in DATASETS:
            first_day = (
                dataset[
                    "start"
                ].date()
            )

            warmup_last = (
                dataset[
                    "start"
                ]
                + timedelta(
                    days=
                        WARMUP_DAYS - 1
                )
            ).date()

            holdout_first = (
                dataset[
                    "start"
                ]
                + timedelta(
                    days=
                        WARMUP_DAYS
                )
            ).date()

            holdout_last = (
                dataset[
                    "start"
                ]
                + timedelta(
                    days=
                        TOTAL_DAYS - 1
                )
            ).date()

            print()
            print(
                dataset[
                    "name"
                ]
            )

            print(
                "  Warm-up:",
                first_day,
                "->",
                warmup_last
            )

            print(
                "  Holdout:",
                holdout_first,
                "->",
                holdout_last
            )

        print()
        print(
            "Vytvoreno datasetu:",
            len(
                DATASETS
            )
        )

        print(
            "Warm-up dni na dataset:",
            WARMUP_DAYS
        )

        print(
            "Holdout dni na dataset:",
            HOLDOUT_DAYS
        )

        print(
            "Celkem novych syntetickych dnu:",
            len(
                DATASETS
            )
            * TOTAL_DAYS
        )

        print()
        print(
            "Existujici dataset 2025 "
            "a development dataset 2026 "
            "zustaly nedotcene."
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()