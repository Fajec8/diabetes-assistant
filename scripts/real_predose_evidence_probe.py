from __future__ import annotations

import uuid
from datetime import (
    datetime,
    timedelta,
)
from zoneinfo import ZoneInfo

from sqlalchemy import (
    func,
    select,
)

from app.database import SessionLocal

from app.models.activity import Activity
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.meal import Meal
from app.models.user import User

from app.services.history_search import (
    _HistorySituationCache,
    calculate_ranking_score,
)

from app.services.outcome_evidence import (
    evaluate_evidence_strength,
)

from app.services.outcome_quality import (
    evaluate_outcome_quality,
)

from app.services.similarity import (
    compare_situations,
)


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

CLARITY_SOURCE = "DEXCOM_CLARITY"
CLARITY_NOTE = "Imported from Dexcom Clarity CSV"

NOVORAPID = "NOVORAPID"

HORIZONS = [
    30,
    60,
    90,
    120,
    180,
]

GLUCOSE_TOLERANCE = timedelta(
    minutes=10
)

# Situace, které nám vyšly v původním
# real similarity probe.
ORIGINAL_CANDIDATES = [
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


def keep_only_real_data(
    cache,
):
    cache.glucose_readings = [
        row
        for row in cache.glucose_readings
        if row.source
        == CLARITY_SOURCE
    ]

    cache.glucose_times = [
        row.measured_at
        for row
        in cache.glucose_readings
    ]

    cache.novorapid_doses = [
        row
        for row in cache.novorapid_doses
        if row.source
        == CLARITY_SOURCE
    ]

    cache.tresiba_doses = [
        row
        for row in cache.tresiba_doses
        if row.source
        == CLARITY_SOURCE
    ]

    cache.novorapid_times = [
        row.administered_at
        for row
        in cache.novorapid_doses
    ]

    cache.tresiba_times = [
        row.administered_at
        for row
        in cache.tresiba_doses
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
        ).append(
            dose
        )

    cache.activities = [
        row
        for row in cache.activities
        if row.note
        == CLARITY_NOTE
    ]

    cache.activity_end_times = [
        row.ended_at
        for row
        in cache.activities
    ]


def nearest_glucose(
    db,
    target,
):
    rows = (
        db.execute(
            select(
                GlucoseReading
            ).where(
                GlucoseReading.user_id
                == USER_ID,

                GlucoseReading.source
                == CLARITY_SOURCE,

                GlucoseReading.measured_at
                >= target
                - GLUCOSE_TOLERANCE,

                GlucoseReading.measured_at
                <= target
                + GLUCOSE_TOLERANCE,
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return None

    row = min(
        rows,
        key=lambda item: abs(
            (
                item.measured_at
                - target
            ).total_seconds()
        ),
    )

    return float(
        row.value_mmol_l
    )


def find_reference_dose(
    db,
    t0,
):
    start = (
        t0
        - timedelta(
            hours=6
        )
    )

    return (
        db.execute(
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

                InsulinDose.administered_at
                >= start,

                InsulinDose.administered_at
                <= t0,
            )
            .order_by(
                InsulinDose.administered_at.desc()
            )
            .limit(1)
        )
        .scalars()
        .first()
    )


def first_future_action_minutes(
    db,
    decision_t0,
    selected_dose,
):
    end = (
        decision_t0
        + timedelta(
            minutes=180
        )
    )

    times = []

    # Vybranou dávku samotnou ignorujeme.
    # Je to právě rozhodnutí, jehož outcome
    # chceme zpětně hodnotit.
    later_insulin = (
        db.execute(
            select(
                InsulinDose
            ).where(
                InsulinDose.user_id
                == USER_ID,

                InsulinDose.source
                == CLARITY_SOURCE,

                InsulinDose.administered_at
                > selected_dose.administered_at,

                InsulinDose.administered_at
                <= end,
            )
        )
        .scalars()
        .all()
    )

    for dose in later_insulin:
        times.append(
            dose.administered_at
        )

    meals = (
        db.execute(
            select(
                Meal
            ).where(
                Meal.user_id
                == USER_ID,

                Meal.note
                == CLARITY_NOTE,

                Meal.eaten_at
                > decision_t0,

                Meal.eaten_at
                <= end,
            )
        )
        .scalars()
        .all()
    )

    for meal in meals:
        # Pokud je dávka přímo propojená
        # s tímto jídlem, nejde o novou
        # kontaminující akci.
        if (
            selected_dose.meal_id
            is not None
            and meal.id
            == selected_dose.meal_id
        ):
            continue

        times.append(
            meal.eaten_at
        )

    activities = (
        db.execute(
            select(
                Activity
            ).where(
                Activity.user_id
                == USER_ID,

                Activity.note
                == CLARITY_NOTE,

                Activity.started_at
                > decision_t0,

                Activity.started_at
                <= end,
            )
        )
        .scalars()
        .all()
    )

    for activity in activities:
        times.append(
            activity.started_at
        )

    if not times:
        return None

    first = min(
        times
    )

    return (
        first
        - decision_t0
    ).total_seconds() / 60.0


def build_clean_outcome(
    db,
    decision_t0,
    selected_dose,
):
    baseline = nearest_glucose(
        db,
        decision_t0,
    )

    first_action = (
        first_future_action_minutes(
            db,
            decision_t0,
            selected_dose,
        )
    )

    outcome = {
        "baseline_glucose":
            baseline
    }

    for minutes in HORIZONS:
        contaminated = (
            first_action is not None
            and first_action <= minutes
        )

        if contaminated:
            value = None
            delta = None

        else:
            value = nearest_glucose(
                db,
                decision_t0
                + timedelta(
                    minutes=minutes
                ),
            )

            if (
                baseline is not None
                and value is not None
            ):
                delta = round(
                    value - baseline,
                    2,
                )

            else:
                delta = None

        outcome[
            f"glucose_{minutes}m"
        ] = value

        outcome[
            f"delta_{minutes}m"
        ] = delta

    return (
        outcome,
        first_action,
    )


def brief_situation(
    situation,
):
    glucose = situation[
        "glucose"
    ]

    meal = situation[
        "meal"
    ]

    novorapid = situation[
        "novorapid"
    ]

    return (
        f"glucose="
        f"{glucose['current']} "
        f"d15="
        f"{glucose['delta_15m']} "
        f"d30="
        f"{glucose['delta_30m']} "
        f"d60="
        f"{glucose['delta_60m']} "
        f"| meal="
        f"{meal['last_meal_carbs']}g "
        f"({meal['minutes_since_last_meal']} min) "
        f"| previous NovoRapid="
        f"{novorapid['last_bolus_units']}U "
        f"({novorapid['minutes_since_last_bolus']} min)"
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

        # Dávka, která už byla ve skutečnosti
        # podaná, ale pro shadow test ji
        # schováme před modelem.
        current_actual_dose = (
            find_reference_dose(
                db,
                latest_real_t0,
            )
        )

        if current_actual_dose is None:
            raise RuntimeError(
                "No recent current NovoRapid dose found"
            )

        current_decision_t0 = (
            current_actual_dose.administered_at
            - timedelta(
                seconds=1
            )
        )

        cache = _HistorySituationCache(
            db=db,
            user_id=USER_ID,
            search_t0=latest_real_t0,
        )

        keep_only_real_data(
            cache
        )

        current_situation = (
            cache.build_situation(
                t0=current_decision_t0,
                timezone=timezone,
            )
        )

        evidence_rows = []

        print()
        print("=" * 110)
        print(
            "REAL PRE-DOSE EVIDENCE PROBE"
        )
        print("=" * 110)

        print()
        print(
            "CURRENT SHADOW DECISION POINT"
        )
        print("-" * 110)

        print(
            "Decision time:",
            current_decision_t0
            .astimezone(
                timezone
            )
            .isoformat(),
        )

        print(
            brief_situation(
                current_situation
            )
        )

        print(
            "Held-out actual NovoRapid:",
            float(
                current_actual_dose.units
            ),
            "U",
        )

        print(
            "NOTE: held-out dose is NOT "
            "included in the current situation."
        )

        for (
            index,
            raw_original_t0,
        ) in enumerate(
            ORIGINAL_CANDIDATES,
            start=1,
        ):
            original_t0 = (
                datetime.fromisoformat(
                    raw_original_t0
                )
            )

            selected_dose = (
                find_reference_dose(
                    db,
                    original_t0,
                )
            )

            if selected_dose is None:
                continue

            decision_t0 = (
                selected_dose.administered_at
                - timedelta(
                    seconds=1
                )
            )

            historical_situation = (
                cache.build_situation(
                    t0=decision_t0,
                    timezone=timezone,
                )
            )

            comparison = (
                compare_situations(
                    current_situation,
                    historical_situation,
                )
            )

            similarity = float(
                comparison[
                    "similarity_score"
                ]
            )

            coverage = float(
                comparison[
                    "data_coverage"
                ]
            )

            context_rank = float(
                calculate_ranking_score(
                    similarity,
                    coverage,
                )
            )

            (
                outcome,
                first_action,
            ) = build_clean_outcome(
                db,
                decision_t0,
                selected_dose,
            )

            quality = (
                evaluate_outcome_quality(
                    outcome
                )
            )

            evidence = (
                evaluate_evidence_strength(
                    context_score=
                        context_rank,

                    quality_score=
                        quality[
                            "quality_score"
                        ],

                    confidence=
                        quality[
                            "confidence"
                        ],
                )
            )

            if first_action is None:
                action_text = "none"
            else:
                action_text = (
                    f"+{round(first_action)} min"
                )

            row = {
                "index":
                    index,

                "decision_t0":
                    decision_t0,

                "dose_units":
                    float(
                        selected_dose.units
                    ),

                "similarity":
                    similarity,

                "coverage":
                    coverage,

                "context_rank":
                    context_rank,

                "quality":
                    quality[
                        "quality_score"
                    ],

                "confidence":
                    quality[
                        "confidence"
                    ],

                "evidence":
                    evidence[
                        "evidence_score"
                    ],

                "evidence_level":
                    evidence[
                        "evidence_level"
                    ],

                "first_action":
                    action_text,

                "situation":
                    historical_situation,
            }

            evidence_rows.append(
                row
            )

            print()
            print(
                f"#{index:2} "
                f"{decision_t0.astimezone(timezone).isoformat()}"
            )

            print(
                "    "
                + brief_situation(
                    historical_situation
                )
            )

            print(
                f"    selected historical dose="
                f"{row['dose_units']} U"
            )

            print(
                f"    similarity="
                f"{similarity}"
                f" | coverage="
                f"{coverage}%"
                f" | context rank="
                f"{context_rank}"
            )

            print(
                f"    quality="
                f"{row['quality']}"
                f" | confidence="
                f"{row['confidence']}%"
                f" | first future action="
                f"{action_text}"
            )

            print(
                f"    EVIDENCE="
                f"{row['evidence']}"
                f" | "
                f"{row['evidence_level']}"
            )

        evidence_rows.sort(
            key=lambda item: (
                item["evidence"]
                if item["evidence"]
                is not None
                else -1
            ),
            reverse=True,
        )

        print()
        print("=" * 110)
        print(
            "EVIDENCE RANKING"
        )
        print("-" * 110)

        for position, row in enumerate(
            evidence_rows,
            start=1,
        ):
            print(
                f"{position:2}. "
                f"case #{row['index']}"
                f" | evidence="
                f"{row['evidence']}"
                f" {row['evidence_level']}"
                f" | context="
                f"{row['context_rank']}"
                f" | quality="
                f"{row['quality']}"
                f" | confidence="
                f"{row['confidence']}%"
                f" | historical dose="
                f"{row['dose_units']} U"
            )

        print()
        print(
            "Held-out current actual dose:",
            float(
                current_actual_dose.units
            ),
            "U",
        )

        print()
        print(
            "IMPORTANT:"
        )

        print(
            "- Historical doses are shown "
            "for retrospective research only."
        )

        print(
            "- Evidence ranking does NOT "
            "recommend an insulin dose."
        )

        print(
            "- Current actual dose was hidden "
            "from similarity calculation."
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 110)

    finally:
        db.close()


if __name__ == "__main__":
    main()