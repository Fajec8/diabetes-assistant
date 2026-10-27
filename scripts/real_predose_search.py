from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

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

SEARCH_DAYS = 90
SAFETY_HOURS = 6
MIN_SEPARATION_HOURS = 4
TOP_K = 10

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


def keep_only_real_data(
    cache,
):
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
        ).append(
            dose
        )

    cache.activities = [
        row
        for row in cache.activities
        if row.note == CLARITY_NOTE
    ]

    cache.activity_end_times = [
        row.ended_at
        for row in cache.activities
    ]


def find_current_actual_dose(
    db,
    latest_glucose_time,
):
    return (
        db.execute(
            select(
                InsulinDose
            )
            .where(
                InsulinDose.user_id == USER_ID,
                InsulinDose.source == CLARITY_SOURCE,
                InsulinDose.insulin_type == NOVORAPID,
                InsulinDose.administered_at
                <= latest_glucose_time,
            )
            .order_by(
                InsulinDose.administered_at.desc()
            )
            .limit(1)
        )
        .scalars()
        .first()
    )


def get_historical_doses(
    db,
    current_decision_t0,
    current_actual_dose,
):
    search_start = (
        current_decision_t0
        - timedelta(
            days=SEARCH_DAYS
        )
    )

    search_end = (
        current_decision_t0
        - timedelta(
            hours=SAFETY_HOURS
        )
    )

    return (
        db.execute(
            select(
                InsulinDose
            )
            .where(
                InsulinDose.user_id == USER_ID,
                InsulinDose.source == CLARITY_SOURCE,
                InsulinDose.insulin_type == NOVORAPID,
                InsulinDose.administered_at
                >= search_start,
                InsulinDose.administered_at
                <= search_end,
                InsulinDose.id
                != current_actual_dose.id,
            )
            .order_by(
                InsulinDose.administered_at
            )
        )
        .scalars()
        .all()
    )


def nearest_glucose(
    db,
    target,
    past_only=False,
):
    query = select(
        GlucoseReading
    ).where(
        GlucoseReading.user_id == USER_ID,
        GlucoseReading.source == CLARITY_SOURCE,
        GlucoseReading.measured_at
        >= target - GLUCOSE_TOLERANCE,
    )

    if past_only:
        query = query.where(
            GlucoseReading.measured_at
            <= target
        )
    else:
        query = query.where(
            GlucoseReading.measured_at
            <= target + GLUCOSE_TOLERANCE
        )

    rows = (
        db.execute(
            query
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

    later_insulin = (
        db.execute(
            select(
                InsulinDose
            ).where(
                InsulinDose.user_id == USER_ID,
                InsulinDose.source == CLARITY_SOURCE,
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
                Meal.user_id == USER_ID,
                Meal.note == CLARITY_NOTE,
                Meal.eaten_at > decision_t0,
                Meal.eaten_at <= end,
            )
        )
        .scalars()
        .all()
    )

    for meal in meals:
        # Pokud jde o jídlo přímo propojené
        # s vybranou historickou dávkou,
        # jde o součást stejného rozhodnutí.
        if (
            selected_dose.meal_id is not None
            and meal.id == selected_dose.meal_id
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
                Activity.user_id == USER_ID,
                Activity.note == CLARITY_NOTE,
                Activity.started_at > decision_t0,
                Activity.started_at <= end,
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
        first - decision_t0
    ).total_seconds() / 60.0


def build_clean_outcome(
    db,
    decision_t0,
    selected_dose,
):
    baseline = nearest_glucose(
        db,
        decision_t0,
        past_only=True,
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


def select_diverse_top_k(
    candidates,
):
    ordered = sorted(
        candidates,
        key=lambda item:
            item["context_rank"],
        reverse=True,
    )

    selected = []

    minimum_separation = timedelta(
        hours=MIN_SEPARATION_HOURS
    )

    for candidate in ordered:
        too_close = False

        for existing in selected:
            distance = abs(
                candidate["decision_t0"]
                - existing["decision_t0"]
            )

            if distance < minimum_separation:
                too_close = True
                break

        if too_close:
            continue

        selected.append(
            candidate
        )

        if len(selected) >= TOP_K:
            break

    return selected


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

    activity = situation[
        "activity"
    ]

    return (
        f"glucose={glucose['current']} "
        f"d15={glucose['delta_15m']} "
        f"d30={glucose['delta_30m']} "
        f"d60={glucose['delta_60m']} "
        f"| meal="
        f"{meal['last_meal_carbs']}g "
        f"({meal['minutes_since_last_meal']} min) "
        f"| previous NovoRapid="
        f"{novorapid['last_bolus_units']}U "
        f"({novorapid['minutes_since_last_bolus']} min) "
        f"| activity="
        f"{activity['minutes_last_6h']} min/6h"
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

        latest_real_glucose_time = db.scalar(
            select(
                func.max(
                    GlucoseReading.measured_at
                )
            ).where(
                GlucoseReading.user_id == USER_ID,
                GlucoseReading.source == CLARITY_SOURCE,
            )
        )

        if latest_real_glucose_time is None:
            raise RuntimeError(
                "No Clarity glucose found"
            )

        current_actual_dose = (
            find_current_actual_dose(
                db,
                latest_real_glucose_time,
            )
        )

        if current_actual_dose is None:
            raise RuntimeError(
                "No recent NovoRapid dose found"
            )

        # Shadow decision point:
        # těsně před skutečnou dávkou.
        current_decision_t0 = (
            current_actual_dose.administered_at
            - timedelta(
                seconds=1
            )
        )

        cache = _HistorySituationCache(
            db=db,
            user_id=USER_ID,
            search_t0=latest_real_glucose_time,
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

        historical_doses = (
            get_historical_doses(
                db,
                current_decision_t0,
                current_actual_dose,
            )
        )

        candidates = []

        print()
        print("=" * 112)
        print(
            "REAL PRE-DOSE FULL HISTORY SEARCH"
        )
        print("=" * 112)

        print()
        print(
            "CURRENT SHADOW DECISION"
        )
        print("-" * 112)

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
            "Held-out actual dose:",
            float(
                current_actual_dose.units
            ),
            "U",
        )

        print()
        print(
            "Historical NovoRapid doses "
            "in search window:",
            len(
                historical_doses
            ),
        )

        for dose in historical_doses:
            decision_t0 = (
                dose.administered_at
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

            candidates.append(
                {
                    "dose":
                        dose,

                    "decision_t0":
                        decision_t0,

                    "situation":
                        historical_situation,

                    "similarity":
                        similarity,

                    "coverage":
                        coverage,

                    "context_rank":
                        context_rank,
                }
            )

        top = select_diverse_top_k(
            candidates
        )

        print(
            "Pre-dose candidates built:",
            len(
                candidates
            ),
        )

        print(
            "Selected TOP:",
            len(
                top
            ),
        )

        evidence_rows = []

        print()
        print("=" * 112)
        print(
            "TOP 10 PRE-DOSE MATCHES"
        )
        print("-" * 112)

        for index, candidate in enumerate(
            top,
            start=1,
        ):
            dose = candidate[
                "dose"
            ]

            decision_t0 = candidate[
                "decision_t0"
            ]

            (
                outcome,
                first_action,
            ) = build_clean_outcome(
                db,
                decision_t0,
                dose,
            )

            quality = (
                evaluate_outcome_quality(
                    outcome
                )
            )

            evidence = (
                evaluate_evidence_strength(
                    context_score=
                        candidate[
                            "context_rank"
                        ],

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
                **candidate,

                "dose_units":
                    float(
                        dose.units
                    ),

                "quality":
                    quality[
                        "quality_score"
                    ],

                "quality_status":
                    quality[
                        "status"
                    ],

                "confidence":
                    quality[
                        "confidence"
                    ],

                "confidence_level":
                    quality[
                        "confidence_level"
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
            }

            evidence_rows.append(
                row
            )

            print()
            print(
                f"{index:2}. "
                f"{decision_t0.astimezone(timezone).isoformat()}"
            )

            print(
                "    "
                + brief_situation(
                    candidate[
                        "situation"
                    ]
                )
            )

            print(
                f"    historical action="
                f"{row['dose_units']} U NovoRapid"
            )

            print(
                f"    similarity="
                f"{row['similarity']}"
                f" | coverage="
                f"{row['coverage']}%"
                f" | context="
                f"{row['context_rank']}"
            )

            print(
                f"    quality="
                f"{row['quality']}"
                f" | "
                f"{row['quality_status']}"
                f" | confidence="
                f"{row['confidence']}%"
                f" | "
                f"{row['confidence_level']}"
            )

            print(
                f"    evidence="
                f"{row['evidence']}"
                f" | "
                f"{row['evidence_level']}"
                f" | first future action="
                f"{action_text}"
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
        print("=" * 112)
        print(
            "EVIDENCE RANKING"
        )
        print("-" * 112)

        for position, row in enumerate(
            evidence_rows,
            start=1,
        ):
            print(
                f"{position:2}. "
                f"dose="
                f"{row['dose_units']} U"
                f" | evidence="
                f"{row['evidence']}"
                f" {row['evidence_level']}"
                f" | similarity="
                f"{row['similarity']}"
                f" | context="
                f"{row['context_rank']}"
                f" | quality="
                f"{row['quality']}"
                f" | confidence="
                f"{row['confidence']}%"
            )

        print()
        print("=" * 112)

        print(
            "Held-out actual current dose:",
            float(
                current_actual_dose.units
            ),
            "U",
        )

        print()
        print(
            "Search method:"
        )

        print(
            f"- last {SEARCH_DAYS} days"
        )

        print(
            f"- current safety gap: "
            f"{SAFETY_HOURS} h"
        )

        print(
            f"- minimum separation between "
            f"selected historical decisions: "
            f"{MIN_SEPARATION_HOURS} h"
        )

        print(
            "- every candidate is built "
            "1 second BEFORE its historical dose"
        )

        print(
            "- actual historical dose is hidden "
            "during similarity calculation"
        )

        print(
            "- historical dose is revealed only "
            "after matching for retrospective analysis"
        )

        print()
        print(
            "RESEARCH / SHADOW ANALYSIS ONLY."
        )

        print(
            "No insulin dose is recommended."
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print("=" * 112)

    finally:
        db.close()


if __name__ == "__main__":
    main()