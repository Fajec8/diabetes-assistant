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
            select(User).where(User.email == EMAIL)
        )

        if user is None:
            print(f"User {EMAIL} nebyl nalezen.")
            return

        db.execute(
            delete(GlucoseReading)
            .where(GlucoseReading.user_id == user.id)
        )

        db.execute(
            delete(InsulinDose)
            .where(InsulinDose.user_id == user.id)
        )

        db.execute(
            delete(Meal)
            .where(Meal.user_id == user.id)
        )

        db.execute(
            delete(Activity)
            .where(Activity.user_id == user.id)
        )

        t0 = datetime(
            2026, 10, 3, 13, 30,
            tzinfo=TZ
        )

        glucose_values = [
            7.6, 7.7, 7.9, 8.0, 8.2,
            8.4, 8.6, 8.8, 8.9, 9.0,
            9.1, 9.0, 8.9, 8.8, 8.6,
            8.5, 8.4, 8.2, 8.1, 8.0,
            7.8, 7.6, 7.5, 7.3, 7.2
        ]

        start = t0 - timedelta(hours=2)

        for i, value in enumerate(glucose_values):
            db.add(
                GlucoseReading(
                    user_id=user.id,
                    measured_at=start + timedelta(minutes=5 * i),
                    value_mmol_l=value,
                    source="CGM"
                )
            )

        db.add(
            Meal(
                user_id=user.id,
                eaten_at=datetime(
                    2026, 10, 3, 12, 0,
                    tzinfo=TZ
                ),
                carbohydrates_g=60,
                description="Testovací oběd",
                note=None
            )
        )

        db.add(
            InsulinDose(
                user_id=user.id,
                insulin_type="NOVORAPID",
                units=6,
                administered_at=datetime(
                    2026, 10, 3, 12, 5,
                    tzinfo=TZ
                ),
                source="MANUAL",
                note="Testovací bolus"
            )
        )

        db.add(
            InsulinDose(
                user_id=user.id,
                insulin_type="TRESIBA",
                units=16,
                administered_at=datetime(
                    2026, 10, 2, 22, 0,
                    tzinfo=TZ
                ),
                source="MANUAL",
                note=None
            )
        )

        db.add(
            Activity(
                user_id=user.id,
                started_at=datetime(
                    2026, 10, 3, 9, 0,
                    tzinfo=TZ
                ),
                ended_at=datetime(
                    2026, 10, 3, 11, 0,
                    tzinfo=TZ
                ),
                activity_type="GYM",
                intensity="MEDIUM",
                note="Testovací trénink"
            )
        )

        db.commit()

        print("Testovací data byla vytvořena.")
        print(f"User: {EMAIL}")
        print(f"User ID: {user.id}")
        print(f"Analyzovaný čas t0: {t0}")
        print(f"Počet CGM hodnot: {len(glucose_values)}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
