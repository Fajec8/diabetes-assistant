from __future__ import annotations

import uuid
from datetime import (
    datetime,
    timedelta,
)
from pprint import pprint
from zoneinfo import ZoneInfo

from sqlalchemy import (
    func,
    select,
)

from app.database import SessionLocal

from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.user import User

from app.services.predose_shadow_engine import (
    build_current_situation_from_snapshot,
    estimate_unlinked_shadow_action,
)

from scripts.real_predose_backtest import (
    CLARITY_SOURCE,
    build_predose_situation,
    prepare_real_cache,
)

from scripts.shadow_v1_historical_replay import (
    HISTORY_DAYS,
    build_replay_input_snapshot,
)


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

NOVORAPID = "NOVORAPID"

TARGET_DECISION_AT = datetime.fromisoformat(
    "2026-10-25T07:33:09+01:00"
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

        expected_dose_time = (
            TARGET_DECISION_AT
            + timedelta(
                seconds=1
            )
        )

        target_dose = db.scalar(
            select(
                InsulinDose
            )
            .where(
                InsulinDose.user_id
                == USER_ID,

                InsulinDose.source
                == CLARITY_SOURCE,

                InsulinDose.insulin_type
                == NOVORAPID,

                InsulinDose.meal_id
                .is_(None),

                InsulinDose.administered_at
                >= (
                    expected_dose_time
                    - timedelta(
                        seconds=2
                    )
                ),

                InsulinDose.administered_at
                <= (
                    expected_dose_time
                    + timedelta(
                        seconds=2
                    )
                ),
            )
        )

        if target_dose is None:
            raise RuntimeError(
                "Target NovoRapid dose not found"
            )

        decision_t0 = (
            target_dose.administered_at
            - timedelta(
                seconds=1
            )
        )

        preload_start = (
            decision_t0
            - timedelta(
                days=
                    HISTORY_DAYS,
                hours=2,
            )
        )

        cache = prepare_real_cache(
            db,
            target_dose.administered_at,
            preload_start,
        )

        meal_by_id = {
            meal.id:
                meal

            for meal
            in cache.meals
        }

        (
            _,
            old_predose_situation,
        ) = build_predose_situation(
            cache=cache,
            dose=target_dose,
            timezone=timezone,
            meal_by_id=meal_by_id,
        )

        snapshot = (
            build_replay_input_snapshot(
                db=db,
                target_dose=
                    target_dose,
                decision_t0=
                    decision_t0,
                target_situation=
                    old_predose_situation,
            )
        )

        new_input_situation = (
            build_current_situation_from_snapshot(
                input_snapshot=
                    snapshot,
                timezone=
                    timezone,
            )
        )

        result = (
            estimate_unlinked_shadow_action(
                db=db,
                user_id=USER_ID,
                input_snapshot=
                    snapshot,
            )
        )

        print()
        print("=" * 110)
        print(
            "SHADOW V1 OUTLIER DEBUG"
        )
        print("=" * 110)

        print(
            "Decision:",
            decision_t0
            .astimezone(
                timezone
            )
            .isoformat(),
        )

        print(
            "Actual hidden dose:",
            float(
                target_dose.units
            ),
            "U",
        )

        print()
        print("-" * 110)
        print(
            "NEW INPUT SNAPSHOT"
        )
        print("-" * 110)

        pprint(
            snapshot,
            sort_dicts=False,
        )

        print()
        print("-" * 110)
        print(
            "SITUATION CREATED FROM NEW INPUT"
        )
        print("-" * 110)

        pprint(
            new_input_situation,
            sort_dicts=False,
        )

        print()
        print("-" * 110)
        print(
            "OLD HISTORICAL PRE-DOSE SITUATION"
        )
        print("-" * 110)

        pprint(
            old_predose_situation,
            sort_dicts=False,
        )

        print()
        print("-" * 110)
        print(
            "SHADOW RESULT"
        )
        print("-" * 110)

        print(
            "status:",
            result[
                "status"
            ],
        )

        print(
            "estimated_units:",
            result[
                "estimated_units"
            ],
        )

        print(
            "support_count:",
            result[
                "support_count"
            ],
        )

        print(
            "strongest_evidence:",
            result[
                "strongest_evidence"
            ],
        )

        print(
            "average_evidence:",
            result[
                "average_evidence"
            ],
        )

        print(
            "abstain_reason:",
            result[
                "abstain_reason"
            ],
        )

        evidence = (
            result[
                "evidence_snapshot"
            ]
            or {}
        )

        print()
        print("-" * 110)
        print(
            "TOP HISTORICAL MATCHES"
        )
        print("-" * 110)

        matches = evidence.get(
            "matches",
            [],
        )

        for (
            index,
            match,
        ) in enumerate(
            matches,
            start=1,
        ):
            print()
            print(
                f"MATCH {index}"
            )

            print(
                "decision_at:",
                match.get(
                    "decision_at"
                ),
            )

            print(
                "historical dose:",
                match.get(
                    "dose_units"
                ),
                "U",
            )

            print(
                "similarity:",
                match.get(
                    "similarity"
                ),
            )

            print(
                "coverage:",
                match.get(
                    "coverage"
                ),
            )

            print(
                "context_rank:",
                match.get(
                    "context_rank"
                ),
            )

            print(
                "outcome_quality:",
                match.get(
                    "outcome_quality"
                ),
            )

            print(
                "outcome_confidence:",
                match.get(
                    "outcome_confidence"
                ),
            )

            print(
                "evidence_score:",
                match.get(
                    "evidence_score"
                ),
            )

            print(
                "evidence_level:",
                match.get(
                    "evidence_level"
                ),
            )

        print()
        print("=" * 110)
        print(
            "DATABASE CHANGED: NO"
        )
        print("=" * 110)

    finally:
        db.close()


if __name__ == "__main__":
    main()