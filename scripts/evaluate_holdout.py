from datetime import datetime
from math import ceil, floor, sqrt
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models.glucose import GlucoseReading
from app.models.user import User
from app.services.batch_evaluation import (
    evaluate_batch,
)
from app.services.situation_outcome import (
    build_situation_outcome,
)


TEST_USER_EMAIL = (
    "test@example.com"
)

TZ = ZoneInfo(
    "Europe/Prague"
)

HOLDOUT_START = datetime(
    2025,
    4,
    2,
    0,
    0,
    tzinfo=TZ
)

HOLDOUT_END = datetime(
    2025,
    6,
    1,
    0,
    0,
    tzinfo=TZ
)

TARGET_HOUR = 13
TARGET_MINUTE = 30

K_VALUES = [
    3,
    5,
    10,
    20,
    30
]

HORIZONS = [
    "30m",
    "60m",
    "90m",
    "120m",
    "180m"
]

# Toto pravidlo bylo zvoleno PRED analyzou
# holdout datasetu na zaklade development dat
# z roku 2026.
HORIZON_SPECIFIC_K = {
    "30m": 3,
    "60m": 3,
    "90m": 5,
    "120m": 5,
    "180m": 5
}


def _format_number(
    value
):
    if value is None:
        return "-"

    return f"{value:.3f}"


def _available_values(
    values
):
    return [
        value
        for value in values
        if value is not None
    ]


def _mean(
    values,
    digits=3
):
    available = (
        _available_values(
            values
        )
    )

    if not available:
        return None

    return round(
        sum(available)
        / len(available),
        digits
    )


def _median(
    values
):
    available = sorted(
        _available_values(
            values
        )
    )

    if not available:
        return None

    count = len(
        available
    )

    middle = (
        count // 2
    )

    if (
        count % 2
        == 1
    ):
        result = (
            available[
                middle
            ]
        )

    else:
        result = (
            (
                available[
                    middle - 1
                ]
                + available[
                    middle
                ]
            )
            / 2
        )

    return round(
        result,
        3
    )


def _standard_deviation(
    values
):
    available = (
        _available_values(
            values
        )
    )

    if not available:
        return None

    mean_value = (
        sum(available)
        / len(available)
    )

    variance = (
        sum(
            (
                value
                - mean_value
            ) ** 2
            for value
            in available
        )
        / len(available)
    )

    return round(
        sqrt(
            variance
        ),
        3
    )


def _percentile(
    values,
    percentile
):
    available = sorted(
        _available_values(
            values
        )
    )

    if not available:
        return None

    if (
        len(available)
        == 1
    ):
        return round(
            available[0],
            3
        )

    position = (
        (
            len(available)
            - 1
        )
        * percentile
        / 100
    )

    lower_index = floor(
        position
    )

    upper_index = ceil(
        position
    )

    if (
        lower_index
        == upper_index
    ):
        result = (
            available[
                lower_index
            ]
        )

    else:
        fraction = (
            position
            - lower_index
        )

        result = (
            available[
                lower_index
            ]
            + (
                available[
                    upper_index
                ]
                - available[
                    lower_index
                ]
            )
            * fraction
        )

    return round(
        result,
        3
    )


def _statistics(
    values
):
    available = (
        _available_values(
            values
        )
    )

    if not available:
        return {
            "mean": None,
            "median": None,
            "standard_deviation": None,
            "p90": None,
            "p95": None,
            "maximum": None
        }

    return {
        "mean":
            _mean(
                available
            ),

        "median":
            _median(
                available
            ),

        "standard_deviation":
            _standard_deviation(
                available
            ),

        "p90":
            _percentile(
                available,
                90
            ),

        "p95":
            _percentile(
                available,
                95
            ),

        "maximum":
            round(
                max(
                    available
                ),
                3
            )
    }


def _minutes_from_midnight(
    timestamp
):
    return (
        timestamp.hour * 60
        + timestamp.minute
    )


def _find_k_result(
    evaluation,
    k
):
    for item in evaluation.get(
        "results",
        []
    ):
        if (
            item.get(
                "k_requested"
            )
            == k
        ):
            return item

    return None


def _discover_holdout_times(
    db,
    user
):
    timezone = ZoneInfo(
        user.timezone
    )

    readings = db.scalars(
        select(
            GlucoseReading
        )
        .where(
            GlucoseReading.user_id
            == user.id,

            GlucoseReading.measured_at
            >= HOLDOUT_START,

            GlucoseReading.measured_at
            < HOLDOUT_END
        )
        .order_by(
            GlucoseReading.measured_at
        )
    ).all()

    target_minutes = (
        TARGET_HOUR * 60
        + TARGET_MINUTE
    )

    candidates_per_day = {}

    for reading in readings:
        local_time = (
            reading.measured_at
            .astimezone(
                timezone
            )
        )

        if (
            local_time.minute
            % 15
            != 0
        ):
            continue

        day = (
            local_time.date()
        )

        candidates_per_day.setdefault(
            day,
            []
        ).append(
            local_time
        )

    evaluation_times = []
    skipped_days = []

    for day in sorted(
        candidates_per_day.keys()
    ):
        candidates = sorted(
            candidates_per_day[
                day
            ],
            key=lambda timestamp: (
                abs(
                    _minutes_from_midnight(
                        timestamp
                    )
                    - target_minutes
                ),
                timestamp
            )
        )

        selected_time = None

        for candidate_time in candidates:
            outcome = (
                build_situation_outcome(
                    db=db,
                    user_id=user.id,
                    t0=candidate_time
                )
            )

            if (
                outcome.get(
                    "outcome_coverage"
                )
                == 100.0
            ):
                selected_time = (
                    candidate_time
                )

                break

        if selected_time is None:
            skipped_days.append(
                day.isoformat()
            )

            continue

        evaluation_times.append(
            selected_time
        )

    return (
        evaluation_times,
        skipped_days
    )


def _build_horizon_specific_result(
    evaluation
):
    horizon_errors = {}

    for horizon in HORIZONS:
        selected_k = (
            HORIZON_SPECIFIC_K[
                horizon
            ]
        )

        k_result = (
            _find_k_result(
                evaluation,
                selected_k
            )
        )

        if k_result is None:
            return None

        horizon_result = (
            k_result
            .get(
                "horizons",
                {}
            )
            .get(
                horizon,
                {}
            )
        )

        error = (
            horizon_result.get(
                "absolute_error_median"
            )
        )

        if error is None:
            return None

        horizon_errors[
            horizon
        ] = {
            "k":
                selected_k,

            "absolute_error":
                error
        }

    errors = [
        item[
            "absolute_error"
        ]
        for item
        in horizon_errors.values()
    ]

    return {
        "mae":
            _mean(
                errors,
                digits=2
            ),

        "horizons":
            horizon_errors
    }


def _compare_methods(
    evaluations,
    adaptive_results,
    fixed_k
):
    adaptive_wins = 0
    ties = 0
    fixed_wins = 0

    for evaluation in evaluations:
        timestamp = (
            evaluation[
                "evaluation_timestamp"
            ]
        )

        adaptive = (
            adaptive_results.get(
                timestamp
            )
        )

        fixed = (
            _find_k_result(
                evaluation,
                fixed_k
            )
        )

        if (
            adaptive is None
            or fixed is None
        ):
            continue

        adaptive_mae = (
            adaptive[
                "mae"
            ]
        )

        fixed_mae = (
            fixed.get(
                "mae_median"
            )
        )

        if (
            adaptive_mae is None
            or fixed_mae is None
        ):
            continue

        if (
            adaptive_mae
            < fixed_mae
        ):
            adaptive_wins += 1

        elif (
            adaptive_mae
            > fixed_mae
        ):
            fixed_wins += 1

        else:
            ties += 1

    return {
        "adaptive_wins":
            adaptive_wins,

        "ties":
            ties,

        "fixed_wins":
            fixed_wins
    }


def main():
    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(
                User.email
                == TEST_USER_EMAIL
            )
        )

        if user is None:
            print(
                "Testovaci uzivatel nebyl nalezen."
            )
            return

        (
            evaluation_times,
            discovery_skipped
        ) = (
            _discover_holdout_times(
                db=db,
                user=user
            )
        )

        print()
        print(
            "HOLDOUT EVALUACE"
        )

        print(
            "=" * 92
        )

        print(
            "Holdout obdobi:",
            HOLDOUT_START.date(),
            "->",
            (
                HOLDOUT_END.date()
            )
        )

        print(
            "Nalezene evaluacni dny:",
            len(
                evaluation_times
            )
        )

        print(
            "Dny bez kompletniho outcome:",
            len(
                discovery_skipped
            )
        )

        print(
            "Testovana fixed K:",
            K_VALUES
        )

        print()

        print(
            "Predem stanovene "
            "horizon-specific pravidlo:"
        )

        for horizon in HORIZONS:
            print(
                f"  "
                f"{horizon:<5} "
                f"-> "
                f"K="
                f"{HORIZON_SPECIFIC_K[horizon]}"
            )

        print()

        result = (
            evaluate_batch(
                db=db,
                user_id=user.id,
                evaluation_times=
                    evaluation_times,
                k_values=
                    K_VALUES
            )
        )

        print(
            "=" * 92
        )

        print(
            "Pozadovanych evaluaci:",
            result[
                "requested_evaluation_count"
            ]
        )

        print(
            "Pouzitych evaluaci:",
            result[
                "evaluated_count"
            ]
        )

        print(
            "Preskocenych:",
            result[
                "skipped_count"
            ]
        )

        aggregate = (
            result[
                "aggregate"
            ]
        )

        aggregate_results = (
            aggregate[
                "results"
            ]
        )

        print()
        print(
            "=" * 92
        )

        print(
            "FIXED K - MEDIAN PREDICTION"
        )

        print(
            "=" * 92
        )

        print(
            f"{'K':<6}"
            f"{'AVG':<10}"
            f"{'MEDIAN':<10}"
            f"{'STD':<10}"
            f"{'P90':<10}"
            f"{'P95':<10}"
            f"{'MAX':<10}"
            f"{'WINS':<8}"
        )

        print(
            "-" * 92
        )

        for item in aggregate_results:
            stats = (
                item[
                    "median_method"
                ]
            )

            print(
                f"{item['k']:<6}"
                f"{_format_number(stats['mean_mae']):<10}"
                f"{_format_number(stats['median_mae']):<10}"
                f"{_format_number(stats['standard_deviation']):<10}"
                f"{_format_number(stats['p90']):<10}"
                f"{_format_number(stats['p95']):<10}"
                f"{_format_number(stats['maximum']):<10}"
                f"{stats['win_count']:<8}"
            )

        adaptive_results = {}

        adaptive_maes = []

        adaptive_horizon_errors = {
            horizon: []
            for horizon
            in HORIZONS
        }

        for evaluation in result[
            "evaluations"
        ]:
            adaptive = (
                _build_horizon_specific_result(
                    evaluation
                )
            )

            if adaptive is None:
                continue

            timestamp = (
                evaluation[
                    "evaluation_timestamp"
                ]
            )

            adaptive_results[
                timestamp
            ] = adaptive

            adaptive_maes.append(
                adaptive[
                    "mae"
                ]
            )

            for horizon in HORIZONS:
                adaptive_horizon_errors[
                    horizon
                ].append(
                    adaptive[
                        "horizons"
                    ][
                        horizon
                    ][
                        "absolute_error"
                    ]
                )

        adaptive_stats = (
            _statistics(
                adaptive_maes
            )
        )

        print()
        print(
            "=" * 92
        )

        print(
            "HORIZON-SPECIFIC K - "
            "PREDEFINED HOLDOUT TEST"
        )

        print(
            "=" * 92
        )

        print(
            "Pouzite pravidlo:"
        )

        print(
            "  30m  -> K=3"
        )

        print(
            "  60m  -> K=3"
        )

        print(
            "  90m  -> K=5"
        )

        print(
            "  120m -> K=5"
        )

        print(
            "  180m -> K=5"
        )

        print()

        print(
            f"{'METHOD':<24}"
            f"{'AVG':<10}"
            f"{'MEDIAN':<10}"
            f"{'STD':<10}"
            f"{'P90':<10}"
            f"{'P95':<10}"
            f"{'MAX':<10}"
        )

        print(
            "-" * 92
        )

        print(
            f"{'HORIZON-SPECIFIC':<24}"
            f"{_format_number(adaptive_stats['mean']):<10}"
            f"{_format_number(adaptive_stats['median']):<10}"
            f"{_format_number(adaptive_stats['standard_deviation']):<10}"
            f"{_format_number(adaptive_stats['p90']):<10}"
            f"{_format_number(adaptive_stats['p95']):<10}"
            f"{_format_number(adaptive_stats['maximum']):<10}"
        )

        print()
        print(
            "=" * 92
        )

        print(
            "HORIZON-SPECIFIC CHYBA "
            "PODLE HORIZONTU"
        )

        print(
            "=" * 92
        )

        print(
            f"{'HORIZONT':<12}"
            f"{'K':<8}"
            f"{'AVG ERROR':<14}"
            f"{'MEDIAN':<14}"
            f"{'P95':<14}"
        )

        print(
            "-" * 92
        )

        for horizon in HORIZONS:
            stats = (
                _statistics(
                    adaptive_horizon_errors[
                        horizon
                    ]
                )
            )

            print(
                f"{horizon:<12}"
                f"{HORIZON_SPECIFIC_K[horizon]:<8}"
                f"{_format_number(stats['mean']):<14}"
                f"{_format_number(stats['median']):<14}"
                f"{_format_number(stats['p95']):<14}"
            )

        print()
        print(
            "=" * 92
        )

        print(
            "PRIME POROVNANI "
            "HORIZON-SPECIFIC VS FIXED"
        )

        print(
            "=" * 92
        )

        for fixed_k in [
            3,
            5,
            10
        ]:
            comparison = (
                _compare_methods(
                    evaluations=
                        result[
                            "evaluations"
                        ],

                    adaptive_results=
                        adaptive_results,

                    fixed_k=
                        fixed_k
                )
            )

            print(
                f"Horizon-specific vs K={fixed_k}: "
                f"vyhry="
                f"{comparison['adaptive_wins']}, "
                f"remizy="
                f"{comparison['ties']}, "
                f"prohry="
                f"{comparison['fixed_wins']}"
            )

        print()
        print(
            "=" * 92
        )

        print(
            "DULEZITE:"
        )

        print(
            "Tento holdout nepouzivame "
            "k dalsimu ladeni pravidla."
        )

        print(
            "Nejprve pouze vyhodnotime, "
            "zda predem zvolena strategie "
            "zobecnila na nova data."
        )

        if discovery_skipped:
            print()
            print(
                "Dny bez kompletniho outcome:"
            )

            for day in discovery_skipped:
                print(
                    " ",
                    day
                )

        if result[
            "skipped"
        ]:
            print()
            print(
                "Situace preskocene "
                "batch evaluaci:"
            )

            for item in result[
                "skipped"
            ]:
                print(
                    " ",
                    item
                )

    finally:
        db.close()


if __name__ == "__main__":
    main()