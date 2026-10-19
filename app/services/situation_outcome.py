from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.glucose import GlucoseReading


GLUCOSE_TOLERANCE = timedelta(
    minutes=10
)

OUTCOME_HORIZONS = [
    30,
    60,
    90,
    120,
    180
]


def _nearest_glucose(
    db: Session,
    user_id,
    target_time
):
    readings = db.scalars(
        select(
            GlucoseReading
        )
        .where(
            GlucoseReading.user_id
            == user_id,

            GlucoseReading.measured_at
            >= (
                target_time
                - GLUCOSE_TOLERANCE
            ),

            GlucoseReading.measured_at
            <= (
                target_time
                + GLUCOSE_TOLERANCE
            )
        )
    ).all()

    if not readings:
        return None

    nearest = min(
        readings,
        key=lambda reading:
            abs(
                (
                    reading.measured_at
                    - target_time
                ).total_seconds()
            )
    )

    return float(
        nearest.value_mmol_l
    )


def _calculate_delta(
    baseline,
    future_value
):
    if (
        baseline is None
        or future_value is None
    ):
        return None

    return round(
        future_value
        - baseline,
        2
    )


def build_situation_outcome(
    db: Session,
    user_id,
    t0
):
    baseline = _nearest_glucose(
        db=db,
        user_id=user_id,
        target_time=t0
    )

    future_values = {}

    for minutes in OUTCOME_HORIZONS:
        target_time = (
            t0
            + timedelta(
                minutes=minutes
            )
        )

        future_values[minutes] = (
            _nearest_glucose(
                db=db,
                user_id=user_id,
                target_time=target_time
            )
        )

    available_future_values = sum(
        1
        for value
        in future_values.values()
        if value is not None
    )

    outcome_coverage = round(
        available_future_values
        / len(OUTCOME_HORIZONS)
        * 100,
        1
    )

    return {
        "baseline_glucose":
            baseline,

        "glucose_30m":
            future_values[30],

        "glucose_60m":
            future_values[60],

        "glucose_90m":
            future_values[90],

        "glucose_120m":
            future_values[120],

        "glucose_180m":
            future_values[180],

        "delta_30m":
            _calculate_delta(
                baseline,
                future_values[30]
            ),

        "delta_60m":
            _calculate_delta(
                baseline,
                future_values[60]
            ),

        "delta_90m":
            _calculate_delta(
                baseline,
                future_values[90]
            ),

        "delta_120m":
            _calculate_delta(
                baseline,
                future_values[120]
            ),

        "delta_180m":
            _calculate_delta(
                baseline,
                future_values[180]
            ),

        "outcome_coverage":
            outcome_coverage
    }