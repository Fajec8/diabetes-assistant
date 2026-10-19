from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from scripts.seed_validation_sets import (
    EMAIL,
    HOLDOUT_DAYS,
    TOTAL_DAYS,
    TZ,
    WARMUP_DAYS,
    _delete_dataset,
    _seed_dataset,
)


# ---------------------------------------------------------
# FINAL HOLDOUT
#
# Tyto datasety jsou urcene pouze pro
# posledni nezavislou evaluaci:
#
# FIXED K10
# vs.
# ADAPTIVE K V2
#
# Po zobrazeni vysledku se podle nich
# NESMI menit parametry Adaptive K V2.
# ---------------------------------------------------------


HISTORY_SEPARATION_DAYS = 90


FINAL_DATASETS = [
    {
        "name":
            "FINAL_A_MIXED",

        "start":
            datetime(
                2019,
                1,
                2,
                13,
                30,
                tzinfo=TZ
            ),

        "seed":
            55123,

        "carbs":
            [
                40,
                50,
                55,
                60,
                65,
                75,
                80
            ],

        "boluses":
            [
                4.0,
                5.0,
                5.5,
                6.0,
                6.5,
                7.5,
                8.0
            ],

        "activity_probability":
            0.70,

        "activity_durations":
            [
                30,
                60,
                75,
                90,
                120,
                150
            ],

        "activity_end_minutes":
            [
                75,
                120,
                165,
                210,
                270
            ],

        "glucose_shift":
            0.8,

        "trend_range":
            0.013,

        "outcome_noise":
            0.0075,

        "carb_coefficient":
            0.00075,

        "bolus_coefficient":
            0.0068,

        "previous_activity_coefficient":
            -0.000014,

        "missing_cgm_probability":
            0.02,

        "extra_meal_probability":
            0.20,

        "extra_bolus_probability":
            0.18
    },

    {
        "name":
            "FINAL_B_CARB_VARIABILITY",

        "start":
            datetime(
                2019,
                10,
                2,
                13,
                30,
                tzinfo=TZ
            ),

        "seed":
            66234,

        "carbs":
            [
                25,
                35,
                45,
                55,
                65,
                75,
                85,
                95,
                110
            ],

        "boluses":
            [
                3.0,
                4.0,
                5.0,
                6.0,
                7.0,
                8.0,
                9.0,
                10.0
            ],

        "activity_probability":
            0.60,

        "activity_durations":
            [
                30,
                45,
                60,
                90,
                120
            ],

        "activity_end_minutes":
            [
                60,
                105,
                150,
                210,
                270,
                330
            ],

        "glucose_shift":
            1.0,

        "trend_range":
            0.016,

        "outcome_noise":
            0.010,

        "carb_coefficient":
            0.0010,

        "bolus_coefficient":
            0.0070,

        "previous_activity_coefficient":
            -0.000010,

        "missing_cgm_probability":
            0.03,

        "extra_meal_probability":
            0.40,

        "extra_bolus_probability":
            0.35
    },

    {
        "name":
            "FINAL_C_ACTIVITY_MIXED",

        "start":
            datetime(
                2020,
                8,
                2,
                13,
                30,
                tzinfo=TZ
            ),

        "seed":
            77345,

        "carbs":
            [
                40,
                50,
                60,
                70,
                80
            ],

        "boluses":
            [
                4.0,
                5.0,
                6.0,
                7.0,
                8.0
            ],

        "activity_probability":
            0.85,

        "activity_durations":
            [
                30,
                45,
                60,
                90,
                120,
                150,
                180
            ],

        "activity_end_minutes":
            [
                45,
                90,
                135,
                180,
                240,
                300,
                360
            ],

        "glucose_shift":
            0.85,

        "trend_range":
            0.014,

        "outcome_noise":
            0.008,

        "carb_coefficient":
            0.00075,

        "bolus_coefficient":
            0.0065,

        "previous_activity_coefficient":
            -0.000025,

        "missing_cgm_probability":
            0.04,

        "extra_meal_probability":
            0.18,

        "extra_bolus_probability":
            0.20
    },

    {
        "name":
            "FINAL_D_IRREGULAR",

        "start":
            datetime(
                2021,
                5,
                2,
                13,
                30,
                tzinfo=TZ
            ),

        "seed":
            88456,

        "carbs":
            [
                30,
                45,
                60,
                75,
                90,
                105
            ],

        "boluses":
            [
                3.0,
                4.5,
                6.0,
                7.5,
                9.0
            ],

        "activity_probability":
            0.50,

        "activity_durations":
            [
                30,
                45,
                75,
                90,
                120,
                150
            ],

        "activity_end_minutes":
            [
                45,
                90,
                150,
                210,
                300,
                360
            ],

        "glucose_shift":
            1.3,

        "trend_range":
            0.022,

        "outcome_noise":
            0.016,

        "carb_coefficient":
            0.00065,

        "bolus_coefficient":
            0.0062,

        "previous_activity_coefficient":
            -0.000015,

        "missing_cgm_probability":
            0.12,

        "extra_meal_probability":
            0.30,

        "extra_bolus_probability":
            0.30
    }
]


def _validate_final_datasets():
    names = [
        dataset[
            "name"
        ]
        for dataset
        in FINAL_DATASETS
    ]

    seeds = [
        dataset[
            "seed"
        ]
        for dataset
        in FINAL_DATASETS
    ]

    if (
        len(
            names
        )
        != len(
            set(
                names
            )
        )
    ):
        raise ValueError(
            "Final datasety maji "
            "duplicitni nazvy."
        )

    if (
        len(
            seeds
        )
        != len(
            set(
                seeds
            )
        )
    ):
        raise ValueError(
            "Final datasety maji "
            "duplicitni seedy."
        )

    ordered = sorted(
        FINAL_DATASETS,
        key=lambda dataset:
            dataset[
                "start"
            ]
    )

    for index in range(
        1,
        len(
            ordered
        )
    ):
        previous_dataset = (
            ordered[
                index - 1
            ]
        )

        current_dataset = (
            ordered[
                index
            ]
        )

        previous_end = (
            previous_dataset[
                "start"
            ]
            + timedelta(
                days=
                    TOTAL_DAYS - 1
            )
        )

        minimum_next_start = (
            previous_end
            + timedelta(
                days=
                    HISTORY_SEPARATION_DAYS
            )
        )

        if (
            current_dataset[
                "start"
            ]
            < minimum_next_start
        ):
            raise ValueError(
                "Final datasety nejsou "
                "dostatecne casove oddelene: "
                f"{previous_dataset['name']} "
                "a "
                f"{current_dataset['name']}."
            )


def main():
    _validate_final_datasets()

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
            "FINAL HOLDOUT SEED"
        )

        print(
            "=" * 82
        )

        print(
            "POZOR:"
        )

        print(
            "Tyto datasety jsou urcene "
            "pro finalni nezavislou evaluaci."
        )

        print(
            "Po zobrazeni finalnich vysledku "
            "se Adaptive K V2 uz neladi."
        )

        print()

        for dataset in FINAL_DATASETS:
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

        for dataset in FINAL_DATASETS:
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
                "  FINAL holdout:",
                holdout_first,
                "->",
                holdout_last
            )

        print()
        print(
            "=" * 82
        )

        print(
            "Vytvoreno final datasetu:",
            len(
                FINAL_DATASETS
            )
        )

        print(
            "Warm-up dni na dataset:",
            WARMUP_DAYS
        )

        print(
            "Final holdout dni na dataset:",
            HOLDOUT_DAYS
        )

        print(
            "Celkem novych syntetickych dnu:",
            len(
                FINAL_DATASETS
            )
            * TOTAL_DAYS
        )

        print(
            "Celkem FINAL evaluacnich situaci:",
            len(
                FINAL_DATASETS
            )
            * HOLDOUT_DAYS
        )

        print()

        print(
            "Development datasety 2022-2026 "
            "zustaly nedotcene."
        )

        print()

        print(
            "FINAL HOLDOUT JE NYNI ZAMKNUTY."
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()