from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models.activity import Activity
from app.models.insulin import InsulinDose
from app.models.meal import Meal


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

CLARITY_SOURCE = "DEXCOM_CLARITY"
CLARITY_NOTE = "Imported from Dexcom Clarity CSV"

WINDOW_MINUTES = 180

CANDIDATES = [
    "2026-08-30T15:30:01+02:00",
    "2026-10-06T14:15:09+02:00",
    "2026-10-16T14:00:04+02:00",
    "2026-10-15T13:30:05+02:00",
    "2026-08-17T13:30:55+02:00",
    "2026-08-02T15:15:02+02:00",
    "2026-08-04T12:45:08+02:00",
    "2026-10-05T13:00:05+02:00",
    "2026-10-07T12:15:12+02:00",
    "2026-10-10T13:15:05+02:00",
]


def minutes_after(
    event_time: datetime,
    t0: datetime,
) -> int:
    return round(
        (
            event_time - t0
        ).total_seconds()
        / 60
    )


def main():
    db = SessionLocal()

    try:
        clean_count = 0
        affected_count = 0

        print()
        print("=" * 78)
        print("REAL CLARITY FUTURE ACTIONS PROBE")
        print("=" * 78)

        for index, raw_t0 in enumerate(
            CANDIDATES,
            start=1,
        ):
            t0 = datetime.fromisoformat(
                raw_t0
            )

            end = (
                t0
                + timedelta(
                    minutes=WINDOW_MINUTES
                )
            )

            insulin = (
                db.execute(
                    select(
                        InsulinDose
                    )
                    .where(
                        InsulinDose.user_id
                        == USER_ID,

                        InsulinDose.source
                        == CLARITY_SOURCE,

                        InsulinDose.administered_at
                        > t0,

                        InsulinDose.administered_at
                        <= end,
                    )
                    .order_by(
                        InsulinDose.administered_at
                    )
                )
                .scalars()
                .all()
            )

            meals = (
                db.execute(
                    select(
                        Meal
                    )
                    .where(
                        Meal.user_id
                        == USER_ID,

                        Meal.note
                        == CLARITY_NOTE,

                        Meal.eaten_at
                        > t0,

                        Meal.eaten_at
                        <= end,
                    )
                    .order_by(
                        Meal.eaten_at
                    )
                )
                .scalars()
                .all()
            )

            activities = (
                db.execute(
                    select(
                        Activity
                    )
                    .where(
                        Activity.user_id
                        == USER_ID,

                        Activity.note
                        == CLARITY_NOTE,

                        Activity.started_at
                        > t0,

                        Activity.started_at
                        <= end,
                    )
                    .order_by(
                        Activity.started_at
                    )
                )
                .scalars()
                .all()
            )

            affected = bool(
                insulin
                or meals
                or activities
            )

            if affected:
                affected_count += 1
                status = "AFFECTED"
            else:
                clean_count += 1
                status = "CLEAN"

            print()
            print(
                f"{index:2}. {raw_t0}"
                f" | {status}"
            )
            print("-" * 78)

            if not affected:
                print(
                    "    No new meal, insulin or "
                    "activity within +180 min."
                )
                continue

            for dose in insulin:
                offset = minutes_after(
                    dose.administered_at,
                    t0,
                )

                print(
                    f"    +{offset:3} min"
                    f" | INSULIN"
                    f" | {dose.insulin_type}"
                    f" | {dose.units} U"
                )

            for meal in meals:
                offset = minutes_after(
                    meal.eaten_at,
                    t0,
                )

                print(
                    f"    +{offset:3} min"
                    f" | MEAL"
                    f" | {meal.carbohydrates_g} g"
                    f" | {meal.description}"
                )

            for activity in activities:
                offset = minutes_after(
                    activity.started_at,
                    t0,
                )

                duration = round(
                    (
                        activity.ended_at
                        - activity.started_at
                    ).total_seconds()
                    / 60
                )

                print(
                    f"    +{offset:3} min"
                    f" | ACTIVITY"
                    f" | {duration} min"
                    f" | {activity.activity_type}"
                    f" | {activity.intensity}"
                )

        print()
        print("=" * 78)
        print("SUMMARY")
        print("-" * 78)

        print(
            f"CLEAN:     {clean_count}"
        )

        print(
            f"AFFECTED:  {affected_count}"
        )

        print(
            f"TOTAL:     "
            f"{clean_count + affected_count}"
        )

        print()
        print(
            "CLEAN = no later Clarity meal, "
            "insulin or activity within 180 min."
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 78)

    finally:
        db.close()


if __name__ == "__main__":
    main()