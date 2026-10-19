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


def main():
    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(
                User.email == EMAIL
            )
        )

        if user is None:
            print("Testovaci uzivatel nebyl nalezen.")
            return

        day_start = datetime(
            2026,
            9,
            20,
            0,
            0,
            tzinfo=TZ
        )

        next_day = (
            day_start
            + timedelta(days=1)
        )

        previous_evening = datetime(
            2026,
            9,
            19,
            21,
            0,
            tzinfo=TZ
        )

        # Aby šel script bezpečně spustit opakovaně,
        # nejdřív smažeme případná stará testovací data.

        db.execute(
            delete(GlucoseReading).where(
                GlucoseReading.user_id == user.id,
                GlucoseReading.measured_at >= day_start,
                GlucoseReading.measured_at < next_day
            )
        )

        db.execute(
            delete(Meal).where(
                Meal.user_id == user.id,
                Meal.eaten_at >= day_start,
                Meal.eaten_at < next_day
            )
        )

        db.execute(
            delete(Activity).where(
                Activity.user_id == user.id,
                Activity.started_at >= day_start,
                Activity.started_at < next_day
            )
        )

        db.execute(
            delete(InsulinDose).where(
                InsulinDose.user_id == user.id,
                InsulinDose.administered_at >= previous_evening,
                InsulinDose.administered_at < next_day
            )
        )

        t0 = datetime(
            2026,
            9,
            20,
            13,
            30,
            tzinfo=TZ
        )

        # Schválně pouze 8 hodnot místo očekávaných 25.
        # Klíčové časy 13:30, 13:15, 13:00 a 12:30
        # ale zachováme, takže trend půjde stále spočítat.
        sparse_glucose = [
            (datetime(2026, 9, 20, 11, 30, tzinfo=TZ), 7.6),
            (datetime(2026, 9, 20, 11, 55, tzinfo=TZ), 8.4),
            (datetime(2026, 9, 20, 12, 30, tzinfo=TZ), 8.9),
            (datetime(2026, 9, 20, 12, 45, tzinfo=TZ), 8.5),
            (datetime(2026, 9, 20, 13, 0, tzinfo=TZ), 8.1),
            (datetime(2026, 9, 20, 13, 15, tzinfo=TZ), 7.6),
            (datetime(2026, 9, 20, 13, 25, tzinfo=TZ), 7.3),
            (datetime(2026, 9, 20, 13, 30, tzinfo=TZ), 7.2),
        ]

        for measured_at, value in sparse_glucose:
            db.add(
                GlucoseReading(
                    user_id=user.id,
                    measured_at=measured_at,
                    value_mmol_l=value,
                    source="CGM"
                )
            )

        db.add(
            Meal(
                user_id=user.id,
                eaten_at=datetime(
                    2026,
                    9,
                    20,
                    12,
                    0,
                    tzinfo=TZ
                ),
                carbohydrates_g=60,
                description="Sparse CGM test meal",
                note=None
            )
        )

        db.add(
            InsulinDose(
                user_id=user.id,
                insulin_type="NOVORAPID",
                units=6,
                administered_at=datetime(
                    2026,
                    9,
                    20,
                    12,
                    5,
                    tzinfo=TZ
                ),
                source="MANUAL",
                note="Sparse CGM test bolus"
            )
        )

        db.add(
            InsulinDose(
                user_id=user.id,
                insulin_type="TRESIBA",
                units=16,
                administered_at=datetime(
                    2026,
                    9,
                    19,
                    22,
                    0,
                    tzinfo=TZ
                ),
                source="MANUAL",
                note="Sparse CGM test basal"
            )
        )

        db.add(
            Activity(
                user_id=user.id,
                started_at=datetime(
                    2026,
                    9,
                    20,
                    9,
                    0,
                    tzinfo=TZ
                ),
                ended_at=datetime(
                    2026,
                    9,
                    20,
                    11,
                    0,
                    tzinfo=TZ
                ),
                activity_type="GYM",
                intensity="MEDIUM",
                note="Sparse CGM test activity"
            )
        )

        db.commit()

        print("Sparse CGM test day created.")
        print(f"User ID: {user.id}")
        print(f"Timestamp: {t0}")
        print(f"CGM readings: {len(sparse_glucose)}")

    finally:
        db.close()


if __name__ == "__main__":
    main()