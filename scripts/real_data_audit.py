import uuid

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.activity import Activity
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.meal import Meal


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

CLARITY_NOTE = (
    "Imported from Dexcom Clarity CSV"
)


def main():
    db = SessionLocal()

    try:
        print()
        print("=" * 60)
        print("REAL DATA AUDIT")
        print("=" * 60)

        print("\nGLUCOSE BY SOURCE")
        rows = db.execute(
            select(
                GlucoseReading.source,
                func.count()
            )
            .where(
                GlucoseReading.user_id == USER_ID
            )
            .group_by(
                GlucoseReading.source
            )
        ).all()

        for source, count in rows:
            print(source, count)

        print("\nINSULIN BY SOURCE")
        rows = db.execute(
            select(
                InsulinDose.source,
                func.count()
            )
            .where(
                InsulinDose.user_id == USER_ID
            )
            .group_by(
                InsulinDose.source
            )
        ).all()

        for source, count in rows:
            print(source, count)

        clarity_meals = db.scalar(
            select(func.count())
            .select_from(Meal)
            .where(
                Meal.user_id == USER_ID,
                Meal.note == CLARITY_NOTE
            )
        )

        other_meals = db.scalar(
            select(func.count())
            .select_from(Meal)
            .where(
                Meal.user_id == USER_ID,
                Meal.note != CLARITY_NOTE
            )
        )

        print("\nMEALS")
        print("Clarity:", clarity_meals)
        print("Other:  ", other_meals)

        clarity_activities = db.scalar(
            select(func.count())
            .select_from(Activity)
            .where(
                Activity.user_id == USER_ID,
                Activity.note == CLARITY_NOTE
            )
        )

        other_activities = db.scalar(
            select(func.count())
            .select_from(Activity)
            .where(
                Activity.user_id == USER_ID,
                Activity.note != CLARITY_NOTE
            )
        )

        print("\nACTIVITIES")
        print(
            "Clarity:",
            clarity_activities
        )
        print(
            "Other:  ",
            other_activities
        )

        print()
        print("DATABASE CHANGED: NO")
        print("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    main()