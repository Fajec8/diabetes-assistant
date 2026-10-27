from __future__ import annotations

from bisect import (
    bisect_left,
    bisect_right,
)
from copy import deepcopy
from datetime import (
    datetime,
    timedelta,
)
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from app.services.research_action_estimation import (
    DEFAULT_MIN_EVIDENCE_SCORE,
    DEFAULT_MIN_SUPPORT_CASES,
    estimate_research_action,
)
from app.services.similarity import (
    compare_situations,
)


CLARITY_SOURCE = "DEXCOM_CLARITY"
CLARITY_NOTE = (
    "Imported from Dexcom Clarity CSV"
)

HISTORY_DAYS = 90
REFERENCE_SAFETY_HOURS = 6

TOP_K = 10
MIN_SEPARATION_HOURS = 4
MIN_CONTEXT_COVERAGE = 70.0

LINKED_MEAL_LOOKAHEAD_MINUTES = 30

NOVORAPID_ACTIVE_DURATION_MINUTES = 240
ACTIVITY_HISTORY_HOURS = 48

HORIZONS = [
    30,
    60,
    90,
    120,
    180,
]

GLUCOSE_TOLERANCE_MINUTES = 10


def _parse_datetime(
    value: str | datetime,
) -> datetime:
    if isinstance(
        value,
        datetime,
    ):
        result = value

    else:
        result = datetime.fromisoformat(
            value
        )

    if (
        result.tzinfo is None
        or result.utcoffset() is None
    ):
        raise ValueError(
            "Datetime must be timezone-aware"
        )

    return result


def _prepare_real_cache(
    db: Session,
    user_id,
    search_t0: datetime,
    preload_start: datetime,
):
    cache = _HistorySituationCache(
        db=db,
        user_id=user_id,
        search_t0=search_t0,
    )

    cache.glucose_readings = (
        db.execute(
            select(
                GlucoseReading
            )
            .where(
                GlucoseReading.user_id
                == user_id,

                GlucoseReading.source
                == CLARITY_SOURCE,

                GlucoseReading.measured_at
                >= preload_start,

                GlucoseReading.measured_at
                <= search_t0,
            )
            .order_by(
                GlucoseReading.measured_at
            )
        )
        .scalars()
        .all()
    )

    cache.glucose_times = [
        row.measured_at
        for row
        in cache.glucose_readings
    ]

    cache.meals = [
        meal
        for meal
        in cache.meals
        if (
            meal.note
            == CLARITY_NOTE
        )
    ]

    cache.meal_times = [
        meal.eaten_at
        for meal
        in cache.meals
    ]

    cache.meal_carbs_prefix = (
        cache._build_prefix(
            cache.meals,
            "carbohydrates_g",
        )
    )

    cache.novorapid_doses = [
        dose
        for dose
        in cache.novorapid_doses
        if (
            dose.source
            == CLARITY_SOURCE
        )
    ]

    cache.tresiba_doses = [
        dose
        for dose
        in cache.tresiba_doses
        if (
            dose.source
            == CLARITY_SOURCE
        )
    ]

    cache.novorapid_times = [
        dose.administered_at
        for dose
        in cache.novorapid_doses
    ]

    cache.tresiba_times = [
        dose.administered_at
        for dose
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

    cache.activities = (
        db.execute(
            select(
                Activity
            )
            .where(
                Activity.user_id
                == user_id,

                Activity.note
                == CLARITY_NOTE,

                Activity.ended_at
                >= (
                    preload_start
                    - timedelta(
                        hours=
                            ACTIVITY_HISTORY_HOURS
                    )
                ),

                Activity.started_at
                <= search_t0,
            )
            .order_by(
                Activity.ended_at
            )
        )
        .scalars()
        .all()
    )

    cache.activity_end_times = [
        activity.ended_at
        for activity
        in cache.activities
    ]

    return cache


def _sum_snapshot_novorapid(
    doses: list[dict],
    t0: datetime,
    hours: int,
) -> float:
    start = (
        t0
        - timedelta(
            hours=hours
        )
    )

    total = 0.0

    for dose in doses:
        administered_at = (
            _parse_datetime(
                dose[
                    "administered_at"
                ]
            )
        )

        if (
            administered_at
            > start
            and administered_at
            <= t0
        ):
            total += float(
                dose[
                    "units"
                ]
            )

    return round(
        total,
        2,
    )


def _active_snapshot_novorapid(
    doses: list[dict],
    t0: datetime,
) -> float:
    active = 0.0

    for dose in doses:
        administered_at = (
            _parse_datetime(
                dose[
                    "administered_at"
                ]
            )
        )

        minutes = (
            t0
            - administered_at
        ).total_seconds() / 60.0

        if (
            minutes < 0
            or minutes
            >= NOVORAPID_ACTIVE_DURATION_MINUTES
        ):
            continue

        remaining_fraction = (
            1.0
            - (
                minutes
                / NOVORAPID_ACTIVE_DURATION_MINUTES
            )
        )

        active += (
            float(
                dose[
                    "units"
                ]
            )
            * remaining_fraction
        )

    return round(
        active,
        2,
    )


def _activity_overlap_minutes(
    activities: list[dict],
    t0: datetime,
    older_hours: int,
    newer_hours: int,
) -> int:
    window_start = (
        t0
        - timedelta(
            hours=older_hours
        )
    )

    window_end = (
        t0
        - timedelta(
            hours=newer_hours
        )
    )

    total = 0.0

    for activity in activities:
        started_at = (
            _parse_datetime(
                activity[
                    "started_at"
                ]
            )
        )

        ended_at = (
            _parse_datetime(
                activity[
                    "ended_at"
                ]
            )
        )

        overlap_start = max(
            started_at,
            window_start,
        )

        overlap_end = min(
            ended_at,
            window_end,
        )

        if (
            overlap_end
            > overlap_start
        ):
            total += (
                overlap_end
                - overlap_start
            ).total_seconds() / 60.0

    return round(
        total
    )


def build_current_situation_from_snapshot(
    input_snapshot: dict,
    timezone: ZoneInfo,
) -> dict:
    t0 = _parse_datetime(
        input_snapshot[
            "decision_at"
        ]
    )

    local_t0 = t0.astimezone(
        timezone
    )

    glucose = (
        input_snapshot.get(
            "glucose"
        )
        or {}
    )

    planned_meal = (
        input_snapshot.get(
            "planned_meal"
        )
    )

    if planned_meal is None:
        meal = {
            "last_meal_carbs":
                None,

            "minutes_since_last_meal":
                None,

            "carbs_last_2h":
                None,

            "carbs_last_4h":
                None,

            "last_meal_id":
                None,

            "last_meal_description":
                None,

            "last_meal_note":
                None,

            "items":
                [],

            "linked_bolus":
                None,
        }

    else:
        carbs = float(
            planned_meal[
                "carbohydrates_g"
            ]
        )

        meal = {
            "last_meal_carbs":
                carbs,

            "minutes_since_last_meal":
                0,

            "carbs_last_2h":
                carbs,

            "carbs_last_4h":
                carbs,

            "last_meal_id":
                None,

            "last_meal_description":
                planned_meal.get(
                    "description"
                ),

            "last_meal_note":
                None,

            "items":
                planned_meal.get(
                    "items",
                    [],
                ),

            "linked_bolus":
                None,
        }

    recent_novorapid = [
        dose
        for dose
        in input_snapshot.get(
            "recent_novorapid",
            [],
        )
        if (
            _parse_datetime(
                dose[
                    "administered_at"
                ]
            )
            <= t0
        )
    ]

    recent_novorapid.sort(
        key=lambda dose:
            _parse_datetime(
                dose[
                    "administered_at"
                ]
            )
    )

    last_bolus = (
        recent_novorapid[-1]
        if recent_novorapid
        else None
    )

    if last_bolus is not None:
        last_bolus_time = (
            _parse_datetime(
                last_bolus[
                    "administered_at"
                ]
            )
        )

        minutes_since_last_bolus = round(
            (
                t0
                - last_bolus_time
            ).total_seconds()
            / 60.0
        )

        last_bolus_units = float(
            last_bolus[
                "units"
            ]
        )

    else:
        minutes_since_last_bolus = None
        last_bolus_units = None

    activities = [
        activity
        for activity
        in input_snapshot.get(
            "activities",
            [],
        )
        if (
            _parse_datetime(
                activity[
                    "ended_at"
                ]
            )
            <= t0
        )
    ]

    activities.sort(
        key=lambda activity:
            _parse_datetime(
                activity[
                    "ended_at"
                ]
            )
    )

    recent_activity_cutoff = (
        t0
        - timedelta(
            hours=
                ACTIVITY_HISTORY_HOURS
        )
    )

    recent_activities = [
        activity
        for activity
        in activities
        if (
            _parse_datetime(
                activity[
                    "ended_at"
                ]
            )
            > recent_activity_cutoff
        )
    ]

    last_activity = (
        recent_activities[-1]
        if recent_activities
        else None
    )

    if last_activity is not None:
        activity_start = (
            _parse_datetime(
                last_activity[
                    "started_at"
                ]
            )
        )

        activity_end = (
            _parse_datetime(
                last_activity[
                    "ended_at"
                ]
            )
        )

        activity_duration = round(
            (
                activity_end
                - activity_start
            ).total_seconds()
            / 60.0
        )

        activity_minutes_since_end = round(
            (
                t0
                - activity_end
            ).total_seconds()
            / 60.0
        )

        activity_type = (
            last_activity[
                "activity_type"
            ]
        )

        activity_intensity = (
            last_activity[
                "intensity"
            ]
        )

    else:
        activity_duration = None
        activity_minutes_since_end = None
        activity_type = None
        activity_intensity = None

    tresiba = input_snapshot.get(
        "tresiba"
    )

    if tresiba is not None:
        tresiba_time = (
            _parse_datetime(
                tresiba[
                    "administered_at"
                ]
            )
        )

        tresiba_units = float(
            tresiba[
                "units"
            ]
        )

        tresiba_minutes = round(
            (
                t0
                - tresiba_time
            ).total_seconds()
            / 60.0
        )

    else:
        tresiba_units = None
        tresiba_minutes = None

    return {
        "timestamp":
            local_t0.isoformat(),

        "glucose": {
            "current":
                glucose.get(
                    "current"
                ),

            "delta_15m":
                glucose.get(
                    "delta_15m"
                ),

            "delta_30m":
                glucose.get(
                    "delta_30m"
                ),

            "delta_60m":
                glucose.get(
                    "delta_60m"
                ),

            "data_quality":
                None,
        },

        "meal":
            meal,

        "novorapid": {
            "last_bolus_units":
                last_bolus_units,

            "minutes_since_last_bolus":
                minutes_since_last_bolus,

            "units_last_2h":
                _sum_snapshot_novorapid(
                    recent_novorapid,
                    t0,
                    2,
                ),

            "units_last_4h":
                _sum_snapshot_novorapid(
                    recent_novorapid,
                    t0,
                    4,
                ),

            "units_last_6h":
                _sum_snapshot_novorapid(
                    recent_novorapid,
                    t0,
                    6,
                ),

            "estimated_active_units":
                _active_snapshot_novorapid(
                    recent_novorapid,
                    t0,
                ),

            "active_duration_minutes":
                NOVORAPID_ACTIVE_DURATION_MINUTES,
        },

        "activity": {
            "type":
                activity_type,

            "intensity":
                activity_intensity,

            "duration_minutes":
                activity_duration,

            "minutes_since_end":
                activity_minutes_since_end,

            "minutes_last_6h":
                _activity_overlap_minutes(
                    activities,
                    t0,
                    6,
                    0,
                ),

            "minutes_6_24h":
                _activity_overlap_minutes(
                    activities,
                    t0,
                    24,
                    6,
                ),

            "minutes_24_48h":
                _activity_overlap_minutes(
                    activities,
                    t0,
                    48,
                    24,
                ),

            "history_window_hours":
                ACTIVITY_HISTORY_HOURS,
        },

        "tresiba": {
            "last_basal_units":
                tresiba_units,

            "minutes_since_last_basal":
                tresiba_minutes,
        },

        "time": {
            "hour":
                local_t0.hour,

            "minute":
                local_t0.minute,

            "minutes_from_midnight":
                (
                    local_t0.hour
                    * 60
                    + local_t0.minute
                ),
        },
    }


def _apply_linked_meal_context(
    situation,
    dose,
    meal_by_id,
    cache,
    decision_t0,
):
    if dose.meal_id is None:
        return situation

    meal = meal_by_id.get(
        dose.meal_id
    )

    if meal is None:
        return situation

    if (
        meal.eaten_at
        <= decision_t0
    ):
        return situation

    delay_minutes = (
        meal.eaten_at
        - dose.administered_at
    ).total_seconds() / 60.0

    if (
        delay_minutes < 0
        or delay_minutes
        > LINKED_MEAL_LOOKAHEAD_MINUTES
    ):
        return situation

    result = deepcopy(
        situation
    )

    carbs = float(
        meal.carbohydrates_g
    )

    result[
        "meal"
    ][
        "last_meal_carbs"
    ] = carbs

    result[
        "meal"
    ][
        "minutes_since_last_meal"
    ] = 0

    result[
        "meal"
    ][
        "carbs_last_2h"
    ] = round(
        float(
            result[
                "meal"
            ][
                "carbs_last_2h"
            ]
        )
        + carbs,
        2,
    )

    result[
        "meal"
    ][
        "carbs_last_4h"
    ] = round(
        float(
            result[
                "meal"
            ][
                "carbs_last_4h"
            ]
        )
        + carbs,
        2,
    )

    result[
        "meal"
    ][
        "last_meal_id"
    ] = meal.id

    result[
        "meal"
    ][
        "last_meal_description"
    ] = meal.description

    result[
        "meal"
    ][
        "last_meal_note"
    ] = meal.note

    result[
        "meal"
    ][
        "items"
    ] = cache._meal_items(
        meal
    )

    result[
        "meal"
    ][
        "linked_bolus"
    ] = None

    return result


def _build_predose_situation(
    cache,
    dose,
    timezone,
    meal_by_id,
):
    decision_t0 = (
        dose.administered_at
        - timedelta(
            seconds=1
        )
    )

    situation = (
        cache.build_situation(
            t0=decision_t0,
            timezone=timezone,
        )
    )

    situation = (
        _apply_linked_meal_context(
            situation=situation,
            dose=dose,
            meal_by_id=meal_by_id,
            cache=cache,
            decision_t0=decision_t0,
        )
    )

    return (
        decision_t0,
        situation,
    )


def _nearest_glucose_value(
    glucose_rows,
    glucose_times,
    target,
    past_only=False,
):
    if not glucose_rows:
        return None

    tolerance = timedelta(
        minutes=
            GLUCOSE_TOLERANCE_MINUTES
    )

    index = bisect_left(
        glucose_times,
        target,
    )

    candidates = []

    if (
        index
        < len(
            glucose_rows
        )
    ):
        candidates.append(
            glucose_rows[
                index
            ]
        )

    if index > 0:
        candidates.append(
            glucose_rows[
                index - 1
            ]
        )

    if past_only:
        candidates = [
            row
            for row
            in candidates
            if (
                row.measured_at
                <= target
            )
        ]

    if not candidates:
        return None

    row = min(
        candidates,
        key=lambda item:
            abs(
                (
                    item.measured_at
                    - target
                ).total_seconds()
            ),
    )

    if (
        abs(
            row.measured_at
            - target
        )
        > tolerance
    ):
        return None

    return float(
        row.value_mmol_l
    )


def _first_future_action_minutes(
    decision_t0,
    selected_dose,
    insulin_rows,
    insulin_times,
    meal_rows,
    meal_times,
    activity_rows,
    activity_times,
):
    end = (
        decision_t0
        + timedelta(
            minutes=180
        )
    )

    possible_times = []

    insulin_index = bisect_right(
        insulin_times,
        selected_dose.administered_at,
    )

    if (
        insulin_index
        < len(
            insulin_rows
        )
    ):
        next_insulin = (
            insulin_rows[
                insulin_index
            ]
        )

        if (
            next_insulin.administered_at
            <= end
        ):
            possible_times.append(
                next_insulin.administered_at
            )

    meal_index = bisect_right(
        meal_times,
        decision_t0,
    )

    while (
        meal_index
        < len(
            meal_rows
        )
    ):
        meal = meal_rows[
            meal_index
        ]

        if meal.eaten_at > end:
            break

        if not (
            selected_dose.meal_id
            is not None
            and meal.id
            == selected_dose.meal_id
        ):
            possible_times.append(
                meal.eaten_at
            )
            break

        meal_index += 1

    activity_index = bisect_right(
        activity_times,
        decision_t0,
    )

    if (
        activity_index
        < len(
            activity_rows
        )
    ):
        activity = (
            activity_rows[
                activity_index
            ]
        )

        if (
            activity.started_at
            <= end
        ):
            possible_times.append(
                activity.started_at
            )

    if not possible_times:
        return None

    first = min(
        possible_times
    )

    return (
        first
        - decision_t0
    ).total_seconds() / 60.0


def _build_clean_outcome(
    decision_t0,
    selected_dose,
    glucose_rows,
    glucose_times,
    insulin_rows,
    insulin_times,
    meal_rows,
    meal_times,
    activity_rows,
    activity_times,
):
    baseline = (
        _nearest_glucose_value(
            glucose_rows,
            glucose_times,
            decision_t0,
            past_only=True,
        )
    )

    first_action = (
        _first_future_action_minutes(
            decision_t0=
                decision_t0,

            selected_dose=
                selected_dose,

            insulin_rows=
                insulin_rows,

            insulin_times=
                insulin_times,

            meal_rows=
                meal_rows,

            meal_times=
                meal_times,

            activity_rows=
                activity_rows,

            activity_times=
                activity_times,
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
            value = (
                _nearest_glucose_value(
                    glucose_rows,
                    glucose_times,
                    decision_t0
                    + timedelta(
                        minutes=minutes
                    ),
                )
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

    return outcome


def _select_diverse_top_k(
    candidates,
):
    ordered = sorted(
        candidates,
        key=lambda item:
            item[
                "context_rank"
            ],
        reverse=True,
    )

    selected = []

    minimum_separation = timedelta(
        hours=
            MIN_SEPARATION_HOURS
    )

    for candidate in ordered:
        too_close = any(
            abs(
                candidate[
                    "decision_t0"
                ]
                - selected_item[
                    "decision_t0"
                ]
            )
            < minimum_separation

            for selected_item
            in selected
        )

        if too_close:
            continue

        selected.append(
            candidate
        )

        if (
            len(
                selected
            )
            >= TOP_K
        ):
            break

    return selected


def estimate_unlinked_shadow_action(
    db: Session,
    user_id,
    input_snapshot: dict,
) -> dict:
    user = db.get(
        User,
        user_id,
    )

    if user is None:
        raise ValueError(
            "User not found"
        )

    if (
        input_snapshot.get(
            "planned_meal"
        )
        is not None
    ):
        return {
            "status":
                "ABSTAIN",

            "estimated_units":
                None,

            "support_count":
                0,

            "strongest_evidence":
                None,

            "average_evidence":
                None,

            "abstain_reason":
                "MEAL_CONTEXT_NOT_SUPPORTED_V1",

            "evidence_snapshot":
                None,
        }

    timezone = ZoneInfo(
        user.timezone
    )

    decision_t0 = _parse_datetime(
        input_snapshot[
            "decision_at"
        ]
    )

    current_situation = (
        build_current_situation_from_snapshot(
            input_snapshot=
                input_snapshot,

            timezone=
                timezone,
        )
    )

    if (
        current_situation[
            "glucose"
        ][
            "current"
        ]
        is None
    ):
        return {
            "status":
                "ABSTAIN",

            "estimated_units":
                None,

            "support_count":
                0,

            "strongest_evidence":
                None,

            "average_evidence":
                None,

            "abstain_reason":
                "MISSING_CURRENT_GLUCOSE_V1",

            "evidence_snapshot":
                None,
        }

    preload_start = (
        decision_t0
        - timedelta(
            days=
                HISTORY_DAYS,
            hours=2,
        )
    )

    candidate_start = (
        decision_t0
        - timedelta(
            days=
                HISTORY_DAYS
        )
    )

    candidate_end = (
        decision_t0
        - timedelta(
            hours=
                REFERENCE_SAFETY_HOURS
        )
    )

    cache = _prepare_real_cache(
        db=db,
        user_id=user_id,
        search_t0=decision_t0,
        preload_start=preload_start,
    )

    meal_by_id = {
        meal.id:
            meal

        for meal
        in cache.meals
    }

    all_insulin = (
        db.execute(
            select(
                InsulinDose
            )
            .where(
                InsulinDose.user_id
                == user_id,

                InsulinDose.source
                == CLARITY_SOURCE,

                InsulinDose.administered_at
                >= preload_start,

                InsulinDose.administered_at
                <= decision_t0,
            )
            .order_by(
                InsulinDose.administered_at
            )
        )
        .scalars()
        .all()
    )

    insulin_times = [
        dose.administered_at
        for dose
        in all_insulin
    ]

    all_meals = [
        meal
        for meal
        in cache.meals
        if (
            meal.eaten_at
            >= preload_start
            and meal.eaten_at
            <= decision_t0
        )
    ]

    meal_times = [
        meal.eaten_at
        for meal
        in all_meals
    ]

    all_activities = sorted(
        cache.activities,
        key=lambda item:
            item.started_at,
    )

    activity_times = [
        activity.started_at
        for activity
        in all_activities
    ]

    # DŮLEŽITÉ:
    # No-meal Shadow V1 smí používat
    # pouze historické UNLINKED dávky.
    #
    # Meal-linked dávky by mohly mít
    # vysokou podobnost podle času,
    # glykémie nebo Tresiby, přestože
    # jejich skutečný důvod byla dávka
    # k jídlu.
    rapid_doses = [
        dose
        for dose
        in cache.novorapid_doses
        if (
            dose.administered_at
            >= candidate_start
            and dose.administered_at
            < candidate_end
            and dose.meal_id is None
        )
    ]

    historical_snapshots = []

    for dose in rapid_doses:
        (
            historical_t0,
            historical_situation,
        ) = _build_predose_situation(
            cache=cache,
            dose=dose,
            timezone=timezone,
            meal_by_id=meal_by_id,
        )

        outcome = (
            _build_clean_outcome(
                decision_t0=
                    historical_t0,

                selected_dose=
                    dose,

                glucose_rows=
                    cache.glucose_readings,

                glucose_times=
                    cache.glucose_times,

                insulin_rows=
                    all_insulin,

                insulin_times=
                    insulin_times,

                meal_rows=
                    all_meals,

                meal_times=
                    meal_times,

                activity_rows=
                    all_activities,

                activity_times=
                    activity_times,
            )
        )

        quality = (
            evaluate_outcome_quality(
                outcome
            )
        )

        historical_snapshots.append(
            {
                "dose":
                    dose,

                "decision_t0":
                    historical_t0,

                "situation":
                    historical_situation,

                "quality_score":
                    quality[
                        "quality_score"
                    ],

                "confidence":
                    quality[
                        "confidence"
                    ],
            }
        )

    comparisons = []

    for reference in historical_snapshots:
        comparison = (
            compare_situations(
                current_situation,
                reference[
                    "situation"
                ],
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

        if (
            coverage
            < MIN_CONTEXT_COVERAGE
        ):
            continue

        context_rank = float(
            calculate_ranking_score(
                similarity,
                coverage,
            )
        )

        comparisons.append(
            {
                **reference,

                "similarity":
                    similarity,

                "coverage":
                    coverage,

                "context_rank":
                    context_rank,
            }
        )

    top_matches = (
        _select_diverse_top_k(
            comparisons
        )
    )

    evidence_cases = []
    evidence_snapshot_matches = []

    for match in top_matches:
        evidence = (
            evaluate_evidence_strength(
                context_score=
                    match[
                        "context_rank"
                    ],

                quality_score=
                    match[
                        "quality_score"
                    ],

                confidence=
                    match[
                        "confidence"
                    ],
            )
        )

        evidence_score = (
            evidence[
                "evidence_score"
            ]
        )

        dose_units = float(
            match[
                "dose"
            ].units
        )

        evidence_cases.append(
            {
                "dose_units":
                    dose_units,

                "evidence_score":
                    evidence_score,
            }
        )

        evidence_snapshot_matches.append(
            {
                "decision_at":
                    match[
                        "decision_t0"
                    ].isoformat(),

                "dose_units":
                    dose_units,

                "similarity":
                    match[
                        "similarity"
                    ],

                "coverage":
                    match[
                        "coverage"
                    ],

                "context_rank":
                    match[
                        "context_rank"
                    ],

                "outcome_quality":
                    match[
                        "quality_score"
                    ],

                "outcome_confidence":
                    match[
                        "confidence"
                    ],

                "evidence_score":
                    evidence_score,

                "evidence_level":
                    evidence[
                        "evidence_level"
                    ],
            }
        )

    estimate = (
        estimate_research_action(
            evidence_cases
        )
    )

    evidence_values = [
        float(
            case[
                "evidence_score"
            ]
        )
        for case
        in evidence_cases
        if (
            case.get(
                "evidence_score"
            )
            is not None
        )
    ]

    usable_evidence_values = [
        value
        for value
        in evidence_values
        if (
            value
            >= DEFAULT_MIN_EVIDENCE_SCORE
        )
    ]

    strongest_evidence = (
        round(
            max(
                evidence_values
            ),
            2,
        )
        if evidence_values
        else None
    )

    average_evidence = (
        round(
            sum(
                usable_evidence_values
            )
            / len(
                usable_evidence_values
            ),
            2,
        )
        if usable_evidence_values
        else None
    )

    evidence_snapshot = {
        "engine_version":
            "PRE_DOSE_EVIDENCE_V1_1",

        "history_days":
            HISTORY_DAYS,

        "safety_hours":
            REFERENCE_SAFETY_HOURS,

        "top_k":
            TOP_K,

        "minimum_context_coverage":
            MIN_CONTEXT_COVERAGE,

        "minimum_evidence_score":
            DEFAULT_MIN_EVIDENCE_SCORE,

        "minimum_support_cases":
            DEFAULT_MIN_SUPPORT_CASES,

        "reference_group":
            "UNLINKED_ONLY",

        "historical_dose_count":
            len(
                historical_snapshots
            ),

        "candidate_count":
            len(
                comparisons
            ),

        "top_match_count":
            len(
                top_matches
            ),

        "matches":
            evidence_snapshot_matches,
    }

    if (
        estimate[
            "status"
        ]
        != "ESTIMATED"
    ):
        return {
            "status":
                "ABSTAIN",

            "estimated_units":
                None,

            "support_count":
                estimate[
                    "support_count"
                ],

            "strongest_evidence":
                strongest_evidence,

            "average_evidence":
                average_evidence,

            "abstain_reason":
                "INSUFFICIENT_EVIDENCE_V1",

            "evidence_snapshot":
                evidence_snapshot,
        }

    return {
        "status":
            "ESTIMATED",

        "estimated_units":
            estimate[
                "estimated_units"
            ],

        "support_count":
            estimate[
                "support_count"
            ],

        "strongest_evidence":
            strongest_evidence,

        "average_evidence":
            average_evidence,

        "abstain_reason":
            None,

        "evidence_snapshot":
            evidence_snapshot,
    }