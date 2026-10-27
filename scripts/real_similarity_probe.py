from __future__ import annotations

import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.activity import Activity
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.user import User
from app.services.history_search import (
    HISTORY_SAFETY_HOURS,
    HISTORY_SEARCH_DAYS,
    _HistorySituationCache,
    calculate_ranking_score,
    select_diverse_candidates,
)
from app.services.similarity import compare_situations


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

CLARITY_SOURCE = "DEXCOM_CLARITY"
CLARITY_NOTE = "Imported from Dexcom Clarity CSV"


def keep_only_real_data(cache):
    cache.glucose_readings = [
        row
        for row in cache.glucose_readings
        if row.source == CLARITY_SOURCE
    ]

    cache.glucose_times = [
        row.measured_at
        for row in cache.glucose_readings
    ]

    cache.novorapid_doses = [
        row
        for row in cache.novorapid_doses
        if row.source == CLARITY_SOURCE
    ]

    cache.tresiba_doses = [
        row
        for row in cache.tresiba_doses
        if row.source == CLARITY_SOURCE
    ]

    cache.novorapid_times = [
        row.administered_at
        for row in cache.novorapid_doses
    ]

    cache.tresiba_times = [
        row.administered_at
        for row in cache.tresiba_doses
    ]

    cache.novorapid_units_prefix = (
        cache._build_prefix(
            cache.novorapid_doses,
            "units",
        )
    )

    cache.novorapid_doses_by_meal = {}

    for dose in cache.novorapid_doses:
        if dose.meal_id is None:
            continue

        cache.novorapid_doses_by_meal.setdefault(
            dose.meal_id,
            [],
        ).append(dose)

    cache.activities = [
        row
        for row in cache.activities
        if row.note == CLARITY_NOTE
    ]

    cache.activity_end_times = [
        row.ended_at
        for row in cache.activities
    ]


def brief(situation):
    glucose = situation["glucose"]
    meal = situation["meal"]
    bolus = situation["novorapid"]
    activity = situation["activity"]

    return (
        f"glucose={glucose['current']} "
        f"d15={glucose['delta_15m']} "
        f"d30={glucose['delta_30m']} "
        f"d60={glucose['delta_60m']} | "
        f"meal={meal['last_meal_carbs']}g "
        f"({meal['minutes_since_last_meal']} min) "
        f"{meal['last_meal_description']} | "
        f"NovoRapid={bolus['last_bolus_units']}U "
        f"({bolus['minutes_since_last_bolus']} min) | "
        f"activity={activity['minutes_last_6h']} min/6h"
    )


def main():
    db = SessionLocal()

    try:
        user = db.get(
            User,
            USER_ID,
        )

        if user is None:
            raise RuntimeError(
                "User not found"
            )

        timezone = ZoneInfo(
            user.timezone
        )

        latest_real_t0 = db.scalar(
            select(
                func.max(
                    GlucoseReading.measured_at
                )
            ).where(
                GlucoseReading.user_id
                == USER_ID,
                GlucoseReading.source
                == CLARITY_SOURCE,
            )
        )

        if latest_real_t0 is None:
            raise RuntimeError(
                "No Clarity glucose found"
            )

        cache = _HistorySituationCache(
            db=db,
            user_id=USER_ID,
            search_t0=latest_real_t0,
        )

        keep_only_real_data(
            cache
        )

        current = cache.build_situation(
            t0=latest_real_t0,
            timezone=timezone,
        )

        candidate_start = (
            latest_real_t0
            - timedelta(
                days=HISTORY_SEARCH_DAYS
            )
        )

        candidate_end = (
            latest_real_t0
            - timedelta(
                hours=HISTORY_SAFETY_HOURS
            )
        )

        current_date = (
            latest_real_t0
            .astimezone(timezone)
            .date()
        )

        candidates = []

        for reading in cache.glucose_readings:
            if (
                reading.measured_at
                < candidate_start
            ):
                continue

            if (
                reading.measured_at
                >= candidate_end
            ):
                continue

            local_time = (
                reading.measured_at
                .astimezone(timezone)
            )

            if local_time.minute % 15 != 0:
                continue

            if (
                local_time.date()
                == current_date
            ):
                continue

            historical = (
                cache.build_situation(
                    t0=reading.measured_at,
                    timezone=timezone,
                )
            )

            comparison = (
                compare_situations(
                    current,
                    historical,
                )
            )

            ranking = (
                calculate_ranking_score(
                    comparison[
                        "similarity_score"
                    ],
                    comparison[
                        "data_coverage"
                    ],
                )
            )

            candidates.append(
                {
                    "timestamp":
                        local_time.isoformat(),

                    "similarity_score":
                        comparison[
                            "similarity_score"
                        ],

                    "data_coverage":
                        comparison[
                            "data_coverage"
                        ],

                    "ranking_score":
                        ranking,

                    "situation":
                        historical,
                }
            )

        top = (
            select_diverse_candidates(
                candidates,
                limit=10,
            )
        )

        print()
        print("=" * 72)
        print("REAL CLARITY SIMILARITY PROBE")
        print("=" * 72)

        print(
            "Current:",
            current["timestamp"],
        )

        print(
            brief(current)
        )

        print()
        print(
            "Candidates:",
            len(candidates),
        )

        print(
            "TOP results:",
            len(top),
        )

        print()

        for index, item in enumerate(
            top,
            start=1,
        ):
            print(
                f"{index:2}. "
                f"{item['timestamp']} | "
                f"similarity="
                f"{item['similarity_score']} | "
                f"coverage="
                f"{item['data_coverage']}% | "
                f"rank="
                f"{item['ranking_score']}"
            )

            print(
                "    "
                + brief(
                    item["situation"]
                )
            )

        print()
        print(
            "DATABASE CHANGED: NO"
        )
        print("=" * 72)

    finally:
        db.close()


if __name__ == "__main__":
    main()