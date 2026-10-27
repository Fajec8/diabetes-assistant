from datetime import datetime, timedelta
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.glucose import GlucoseReading
from app.services.outcome_summary import summarize_outcomes


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

SOURCE = "DEXCOM_CLARITY"
TOLERANCE = timedelta(minutes=10)

CANDIDATES = [
    ("2026-08-30T15:30:01+02:00", 77.0),
    ("2026-10-06T14:15:09+02:00", 76.8),
    ("2026-10-16T14:00:04+02:00", 76.5),
    ("2026-10-15T13:30:05+02:00", 75.3),
    ("2026-08-17T13:30:55+02:00", 75.1),
    ("2026-08-02T15:15:02+02:00", 70.9),
    ("2026-08-04T12:45:08+02:00", 70.9),
    ("2026-10-05T13:00:05+02:00", 70.6),
    ("2026-10-07T12:15:12+02:00", 70.6),
    ("2026-10-10T13:15:05+02:00", 70.3),
]

HORIZONS = [30, 60, 90, 120, 180]


def nearest_glucose(db, target):
    rows = db.scalars(
        select(GlucoseReading).where(
            GlucoseReading.user_id == USER_ID,
            GlucoseReading.source == SOURCE,
            GlucoseReading.measured_at >= target - TOLERANCE,
            GlucoseReading.measured_at <= target + TOLERANCE,
        )
    ).all()

    if not rows:
        return None

    row = min(
        rows,
        key=lambda r: abs(
            (r.measured_at - target).total_seconds()
        ),
    )

    return float(row.value_mmol_l)


def build_outcome(db, t0):
    baseline = nearest_glucose(db, t0)

    result = {
        "baseline_glucose": baseline,
    }

    available = 0

    for minutes in HORIZONS:
        value = nearest_glucose(
            db,
            t0 + timedelta(minutes=minutes),
        )

        result[f"glucose_{minutes}m"] = value

        if baseline is not None and value is not None:
            delta = round(value - baseline, 2)
            available += 1
        else:
            delta = None

        result[f"delta_{minutes}m"] = delta

    result["outcome_coverage"] = round(
        available / len(HORIZONS) * 100,
        1,
    )

    return result


def main():
    db = SessionLocal()

    try:
        items = []

        print()
        print("=" * 72)
        print("REAL CLARITY OUTCOME PROBE")
        print("=" * 72)

        for i, (timestamp, ranking) in enumerate(
            CANDIDATES,
            start=1,
        ):
            t0 = datetime.fromisoformat(timestamp)

            outcome = build_outcome(
                db,
                t0,
            )

            items.append(
                {
                    "ranking_score": ranking,
                    "outcome": outcome,
                }
            )

            print(
                f"{i:2}. {timestamp} | "
                f"base={outcome['baseline_glucose']} | "
                f"30={outcome['glucose_30m']} "
                f"({outcome['delta_30m']:+} ) | "
                f"60={outcome['glucose_60m']} "
                f"({outcome['delta_60m']:+} ) | "
                f"90={outcome['glucose_90m']} "
                f"({outcome['delta_90m']:+} ) | "
                f"coverage={outcome['outcome_coverage']}%"
            )

        summary = summarize_outcomes(
            items
        )

        print()
        print("SUMMARY")
        print("-" * 72)

        for minutes in HORIZONS:
            key = f"delta_{minutes}m"
            row = summary[key]

            print(
                f"{minutes:3} min | "
                f"n={row['count']} | "
                f"median={row['median']} | "
                f"weighted={row['weighted_mean']} | "
                f"down={row['direction']['decreased']} "
                f"stable={row['direction']['stable']} "
                f"up={row['direction']['increased']}"
            )

        print()
        print("DATABASE CHANGED: NO")
        print("=" * 72)

    finally:
        db.close()


if __name__ == "__main__":
    main()