from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.insulin import InsulinDose
from app.models.user import User
from app.services.outcome_quality import (
    evaluate_outcome_quality,
)
from app.services.predose_shadow_engine import (
    CLARITY_SOURCE,
    HISTORY_DAYS,
    HORIZONS,
    REFERENCE_SAFETY_HOURS,
    TOP_K,
    _nearest_glucose_value,
    _parse_datetime,
    _prepare_real_cache,
    _select_diverse_top_k,
    build_current_situation_from_snapshot,
)
from app.services.research_action_estimation import (
    DEFAULT_MIN_EVIDENCE_SCORE,
    DEFAULT_MIN_SUPPORT_CASES,
    estimate_research_action,
)


MODEL_VERSION = "SHADOW_V2_MEAL_4"
ENGINE_VERSION = "PRE_DOSE_EVIDENCE_V2_MEAL_4"

MEAL_REFERENCE_PRE_WINDOW_MINUTES = 30
MEAL_REFERENCE_FIRST_DOSE_AFTER_MINUTES = 30
MEAL_TOTAL_WINDOW_AFTER_MINUTES = 180

MIN_MEAL_CONTEXT_COVERAGE = 70.0

CARB_WEIGHT = 30.0
GLUCOSE_WEIGHT = 20.0
TREND_WEIGHT = 15.0
ACTIVE_INSULIN_WEIGHT = 20.0
TIME_WEIGHT = 10.0
BASAL_WEIGHT = 5.0

CARB_FULL_PENALTY_G = 40.0
GLUCOSE_FULL_PENALTY_MMOL = 8.0
TREND_FULL_PENALTY_MMOL = 4.0
ACTIVE_INSULIN_FULL_PENALTY_U = 5.0
TIME_FULL_PENALTY_MINUTES = 240.0
BASAL_FULL_PENALTY_U = 10.0

GLUCOSE_HARD_GATE_MMOL = 5.0

ACTIVE_INSULIN_PRESENT_THRESHOLD = 2.0
ACTIVE_INSULIN_ZERO_THRESHOLD = 0.5
ACTIVE_INSULIN_HIGH_REFERENCE_THRESHOLD = 3.0

RECENCY_MIN_FACTOR = 0.85

LOCAL_CONTEXT_MAX_GAP = 8.0
LOCAL_CONTEXT_MIN_RATIO = 0.90

DOMINANT_CLUSTER_WINDOW_U = 1.5
DOMINANT_CLUSTER_MIN_WEIGHT_SHARE = 0.55
DOMINANT_CLUSTER_MIN_COUNT = 2

UNCONTESTED_DOSE_RANGE_U = 3.0


def _abstain(
    reason: str,
    evidence_snapshot=None,
    support_count: int = 0,
    strongest_evidence=None,
    average_evidence=None,
) -> dict:
    return {
        "status": "ABSTAIN",
        "estimated_units": None,
        "support_count": support_count,
        "strongest_evidence": strongest_evidence,
        "average_evidence": average_evidence,
        "abstain_reason": reason,
        "evidence_snapshot": evidence_snapshot,
        "model_version": MODEL_VERSION,
    }


def _number(
    value,
) -> float | None:
    if value is None:
        return None

    return float(
        value
    )


def _linear_similarity(
    left,
    right,
    full_penalty: float,
) -> float | None:
    left = _number(
        left
    )

    right = _number(
        right
    )

    if (
        left is None
        or right is None
    ):
        return None

    difference = abs(
        left - right
    )

    score = (
        100.0
        * (
            1.0
            - difference
            / full_penalty
        )
    )

    return round(
        max(
            0.0,
            min(
                100.0,
                score,
            ),
        ),
        2,
    )


def _time_similarity(
    current_minutes,
    reference_minutes,
) -> float | None:
    current_minutes = _number(
        current_minutes
    )

    reference_minutes = _number(
        reference_minutes
    )

    if (
        current_minutes is None
        or reference_minutes is None
    ):
        return None

    raw_difference = abs(
        current_minutes
        - reference_minutes
    )

    cyclic_difference = min(
        raw_difference,
        1440.0 - raw_difference,
    )

    score = (
        100.0
        * (
            1.0
            - cyclic_difference
            / TIME_FULL_PENALTY_MINUTES
        )
    )

    return round(
        max(
            0.0,
            min(
                100.0,
                score,
            ),
        ),
        2,
    )


def _trend_similarity(
    current: dict,
    reference: dict,
) -> float | None:
    values = []

    for key in [
        "delta_15m",
        "delta_30m",
        "delta_60m",
    ]:
        score = _linear_similarity(
            current.get(
                key
            ),
            reference.get(
                key
            ),
            TREND_FULL_PENALTY_MMOL,
        )

        if score is not None:
            values.append(
                score
            )

    if not values:
        return None

    return round(
        sum(
            values
        )
        / len(
            values
        ),
        2,
    )


def _allowed_carb_difference(
    target_carbs: float,
) -> float:
    dynamic = (
        target_carbs
        * 0.35
    )

    return max(
        20.0,
        min(
            35.0,
            dynamic,
        ),
    )


def _passes_meal_gates(
    current: dict,
    reference: dict,
) -> tuple[
    bool,
    str | None,
]:
    current_carbs = _number(
        current[
            "meal"
        ].get(
            "last_meal_carbs"
        )
    )

    reference_carbs = _number(
        reference[
            "meal"
        ].get(
            "last_meal_carbs"
        )
    )

    if (
        current_carbs is not None
        and reference_carbs is not None
    ):
        carb_difference = abs(
            current_carbs
            - reference_carbs
        )

        if (
            carb_difference
            > _allowed_carb_difference(
                current_carbs
            )
        ):
            return (
                False,
                "CARB_DISTANCE",
            )

    current_glucose = _number(
        current[
            "glucose"
        ].get(
            "current"
        )
    )

    reference_glucose = _number(
        reference[
            "glucose"
        ].get(
            "current"
        )
    )

    if (
        current_glucose is not None
        and reference_glucose is not None
        and abs(
            current_glucose
            - reference_glucose
        )
        > GLUCOSE_HARD_GATE_MMOL
    ):
        return (
            False,
            "GLUCOSE_DISTANCE",
        )

    current_active = _number(
        current[
            "novorapid"
        ].get(
            "estimated_active_units"
        )
    )

    reference_active = _number(
        reference[
            "novorapid"
        ].get(
            "estimated_active_units"
        )
    )

    if (
        current_active is not None
        and reference_active is not None
    ):
        if (
            current_active
            >= ACTIVE_INSULIN_PRESENT_THRESHOLD
        ):
            allowed_difference = max(
                2.0,
                current_active
                * 0.55,
            )

            if (
                abs(
                    current_active
                    - reference_active
                )
                > allowed_difference
            ):
                return (
                    False,
                    "ACTIVE_INSULIN_DISTANCE",
                )

        elif (
            current_active
            <= ACTIVE_INSULIN_ZERO_THRESHOLD
            and reference_active
            >= ACTIVE_INSULIN_HIGH_REFERENCE_THRESHOLD
        ):
            return (
                False,
                "ACTIVE_INSULIN_DISTANCE",
            )

    return (
        True,
        None,
    )


def _meal_context_score(
    current: dict,
    reference: dict,
) -> dict:
    components = []

    def add_component(
        name: str,
        score,
        weight: float,
    ):
        if score is None:
            return

        components.append(
            {
                "name": name,
                "score": float(
                    score
                ),
                "weight": float(
                    weight
                ),
            }
        )

    add_component(
        "carbs",
        _linear_similarity(
            current[
                "meal"
            ].get(
                "last_meal_carbs"
            ),
            reference[
                "meal"
            ].get(
                "last_meal_carbs"
            ),
            CARB_FULL_PENALTY_G,
        ),
        CARB_WEIGHT,
    )

    add_component(
        "glucose",
        _linear_similarity(
            current[
                "glucose"
            ].get(
                "current"
            ),
            reference[
                "glucose"
            ].get(
                "current"
            ),
            GLUCOSE_FULL_PENALTY_MMOL,
        ),
        GLUCOSE_WEIGHT,
    )

    add_component(
        "trend",
        _trend_similarity(
            current[
                "glucose"
            ],
            reference[
                "glucose"
            ],
        ),
        TREND_WEIGHT,
    )

    add_component(
        "active_insulin",
        _linear_similarity(
            current[
                "novorapid"
            ].get(
                "estimated_active_units"
            ),
            reference[
                "novorapid"
            ].get(
                "estimated_active_units"
            ),
            ACTIVE_INSULIN_FULL_PENALTY_U,
        ),
        ACTIVE_INSULIN_WEIGHT,
    )

    add_component(
        "time",
        _time_similarity(
            current[
                "time"
            ].get(
                "minutes_from_midnight"
            ),
            reference[
                "time"
            ].get(
                "minutes_from_midnight"
            ),
        ),
        TIME_WEIGHT,
    )

    add_component(
        "basal",
        _linear_similarity(
            current[
                "tresiba"
            ].get(
                "last_basal_units"
            ),
            reference[
                "tresiba"
            ].get(
                "last_basal_units"
            ),
            BASAL_FULL_PENALTY_U,
        ),
        BASAL_WEIGHT,
    )

    available_weight = sum(
        item[
            "weight"
        ]
        for item
        in components
    )

    total_weight = (
        CARB_WEIGHT
        + GLUCOSE_WEIGHT
        + TREND_WEIGHT
        + ACTIVE_INSULIN_WEIGHT
        + TIME_WEIGHT
        + BASAL_WEIGHT
    )

    if available_weight <= 0:
        return {
            "score": 0.0,
            "coverage": 0.0,
            "components": components,
        }

    weighted_score = sum(
        item[
            "score"
        ]
        * item[
            "weight"
        ]
        for item
        in components
    )

    score = (
        weighted_score
        / available_weight
    )

    coverage = (
        available_weight
        / total_weight
        * 100.0
    )

    return {
        "score": round(
            score,
            2,
        ),
        "coverage": round(
            coverage,
            2,
        ),
        "components": components,
    }


def _recency_factor(
    target_t0: datetime,
    reference_t0: datetime,
) -> float:
    age_days = max(
        0.0,
        (
            target_t0
            - reference_t0
        ).total_seconds()
        / 86400.0,
    )

    normalized_age = min(
        1.0,
        age_days
        / HISTORY_DAYS,
    )

    factor = (
        1.0
        - (
            1.0
            - RECENCY_MIN_FACTOR
        )
        * normalized_age
    )

    return round(
        factor,
        4,
    )


def _meal_evidence_score(
    context_score: float,
    quality_score,
    confidence,
    recency_factor: float,
) -> float | None:
    if (
        quality_score is None
        or confidence is None
    ):
        return None

    quality = max(
        0.0,
        min(
            100.0,
            float(
                quality_score
            ),
        ),
    )

    outcome_confidence = max(
        0.0,
        min(
            100.0,
            float(
                confidence
            ),
        ),
    )

    outcome_factor = (
        0.45
        + 0.35
        * (
            quality
            / 100.0
        )
        + 0.20
        * (
            outcome_confidence
            / 100.0
        )
    )

    score = (
        float(
            context_score
        )
        * outcome_factor
        * recency_factor
    )

    return round(
        score,
        2,
    )


def _select_local_neighborhood(
    comparisons: list[dict],
) -> list[dict]:
    if not comparisons:
        return []

    ordered = sorted(
        comparisons,
        key=lambda item:
            item[
                "context_rank"
            ],
        reverse=True,
    )

    best_score = float(
        ordered[
            0
        ][
            "context_rank"
        ]
    )

    absolute_threshold = (
        best_score
        - LOCAL_CONTEXT_MAX_GAP
    )

    relative_threshold = (
        best_score
        * LOCAL_CONTEXT_MIN_RATIO
    )

    threshold = max(
        absolute_threshold,
        relative_threshold,
    )

    return [
        item
        for item
        in ordered
        if (
            float(
                item[
                    "context_rank"
                ]
            )
            >= threshold
        )
    ]


def _select_dominant_dose_cluster(
    evidence_cases: list[dict],
) -> dict:
    usable = [
        case
        for case
        in evidence_cases
        if (
            case.get(
                "dose_units"
            )
            is not None
            and case.get(
                "evidence_score"
            )
            is not None
            and float(
                case[
                    "evidence_score"
                ]
            )
            >= DEFAULT_MIN_EVIDENCE_SCORE
        )
    ]

    if not usable:
        return {
            "status": "NO_EVIDENCE",
            "selected_cases": [],
            "usable_count": 0,
            "dose_min": None,
            "dose_max": None,
            "dose_range": None,
            "cluster_center": None,
            "cluster_count": 0,
            "cluster_weight_share": 0.0,
        }

    doses = [
        float(
            case[
                "dose_units"
            ]
        )
        for case
        in usable
    ]

    dose_min = min(
        doses
    )

    dose_max = max(
        doses
    )

    dose_range = (
        dose_max
        - dose_min
    )

    if (
        dose_range
        <= UNCONTESTED_DOSE_RANGE_U
    ):
        return {
            "status": "UNCONTESTED",
            "selected_cases": usable,
            "usable_count": len(
                usable
            ),
            "dose_min": dose_min,
            "dose_max": dose_max,
            "dose_range": round(
                dose_range,
                2,
            ),
            "cluster_center": None,
            "cluster_count": len(
                usable
            ),
            "cluster_weight_share": 1.0,
        }

    total_weight = sum(
        float(
            case[
                "evidence_score"
            ]
        )
        for case
        in usable
    )

    best_cluster = []
    best_center = None
    best_cluster_weight = 0.0

    for center_case in usable:
        center = float(
            center_case[
                "dose_units"
            ]
        )

        cluster = [
            case
            for case
            in usable
            if (
                abs(
                    float(
                        case[
                            "dose_units"
                        ]
                    )
                    - center
                )
                <= DOMINANT_CLUSTER_WINDOW_U
            )
        ]

        cluster_weight = sum(
            float(
                case[
                    "evidence_score"
                ]
            )
            for case
            in cluster
        )

        if (
            cluster_weight
            > best_cluster_weight
        ):
            best_cluster = cluster
            best_center = center
            best_cluster_weight = (
                cluster_weight
            )

        elif (
            cluster_weight
            == best_cluster_weight
            and len(
                cluster
            )
            > len(
                best_cluster
            )
        ):
            best_cluster = cluster
            best_center = center
            best_cluster_weight = (
                cluster_weight
            )

    weight_share = (
        best_cluster_weight
        / total_weight
        if total_weight > 0
        else 0.0
    )

    accepted = (
        len(
            best_cluster
        )
        >= DOMINANT_CLUSTER_MIN_COUNT
        and weight_share
        >= DOMINANT_CLUSTER_MIN_WEIGHT_SHARE
    )

    return {
        "status": (
            "DOMINANT_CLUSTER"
            if accepted
            else "DISAGREEMENT"
        ),
        "selected_cases": (
            best_cluster
            if accepted
            else []
        ),
        "usable_count": len(
            usable
        ),
        "dose_min": dose_min,
        "dose_max": dose_max,
        "dose_range": round(
            dose_range,
            2,
        ),
        "cluster_center": best_center,
        "cluster_count": len(
            best_cluster
        ),
        "cluster_weight_share": round(
            weight_share,
            3,
        ),
    }


def _evidence_summary(
    cases: list[dict],
) -> tuple[
    float | None,
    float | None,
]:
    values = [
        float(
            case[
                "evidence_score"
            ]
        )
        for case
        in cases
        if (
            case.get(
                "evidence_score"
            )
            is not None
            and float(
                case[
                    "evidence_score"
                ]
            )
            >= DEFAULT_MIN_EVIDENCE_SCORE
        )
    ]

    if not values:
        return (
            None,
            None,
        )

    return (
        round(
            max(
                values
            ),
            2,
        ),
        round(
            sum(
                values
            )
            / len(
                values
            ),
            2,
        ),
    )


def _build_planned_meal_reference_situation(
    cache,
    meal,
    first_dose,
    timezone: ZoneInfo,
) -> tuple[
    datetime,
    dict,
]:
    decision_t0 = (
        min(
            meal.eaten_at,
            first_dose.administered_at,
        )
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

    result = deepcopy(
        situation
    )

    carbs = float(
        meal.carbohydrates_g
    )

    result[
        "meal"
    ] = {
        "last_meal_carbs": carbs,
        "minutes_since_last_meal": 0,
        "carbs_last_2h": carbs,
        "carbs_last_4h": carbs,
        "last_meal_id": None,
        "last_meal_description":
            meal.description,
        "last_meal_note": None,
        "items": cache._meal_items(
            meal
        ),
        "linked_bolus": None,
    }

    return (
        decision_t0,
        result,
    )


def _meal_reference_groups(
    cache,
    candidate_start: datetime,
    candidate_end: datetime,
) -> list[dict]:
    groups = []

    for meal in cache.meals:
        doses = sorted(
            cache.novorapid_doses_by_meal.get(
                meal.id,
                [],
            ),
            key=lambda dose:
                dose.administered_at,
        )

        if not doses:
            continue

        linked_doses = []

        for dose in doses:
            relative_minutes = (
                dose.administered_at
                - meal.eaten_at
            ).total_seconds() / 60.0

            if (
                relative_minutes
                < -MEAL_REFERENCE_PRE_WINDOW_MINUTES
                or relative_minutes
                > MEAL_TOTAL_WINDOW_AFTER_MINUTES
            ):
                continue

            linked_doses.append(
                dose
            )

        if not linked_doses:
            continue

        first_dose = (
            linked_doses[
                0
            ]
        )

        first_relative_minutes = (
            first_dose.administered_at
            - meal.eaten_at
        ).total_seconds() / 60.0

        if (
            first_relative_minutes
            > MEAL_REFERENCE_FIRST_DOSE_AFTER_MINUTES
        ):
            continue

        decision_t0 = (
            min(
                meal.eaten_at,
                first_dose.administered_at,
            )
            - timedelta(
                seconds=1
            )
        )

        if (
            decision_t0
            < candidate_start
            or decision_t0
            >= candidate_end
        ):
            continue

        total_units = round(
            sum(
                float(
                    dose.units
                )
                for dose
                in linked_doses
            ),
            2,
        )

        groups.append(
            {
                "meal": meal,
                "first_dose": first_dose,
                "linked_doses": linked_doses,
                "total_units": total_units,
                "strategy": (
                    "SPLIT"
                    if len(
                        linked_doses
                    ) > 1
                    else "SINGLE"
                ),
            }
        )

    return groups


def _first_future_action_minutes_for_meal(
    decision_t0: datetime,
    selected_meal_id,
    linked_dose_ids: set,
    insulin_rows,
    insulin_times,
    meal_rows,
    meal_times,
    activity_rows,
    activity_times,
) -> float | None:
    end = (
        decision_t0
        + timedelta(
            minutes=180
        )
    )

    possible_times = []

    insulin_index = bisect_right(
        insulin_times,
        decision_t0,
    )

    while (
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
            > end
        ):
            break

        if (
            next_insulin.id
            in linked_dose_ids
        ):
            insulin_index += 1
            continue

        possible_times.append(
            next_insulin.administered_at
        )

        break

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
        meal = (
            meal_rows[
                meal_index
            ]
        )

        if (
            meal.eaten_at
            > end
        ):
            break

        if (
            meal.id
            == selected_meal_id
        ):
            meal_index += 1
            continue

        possible_times.append(
            meal.eaten_at
        )

        break

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


def _build_clean_meal_outcome(
    decision_t0: datetime,
    selected_meal_id,
    linked_doses,
    glucose_rows,
    glucose_times,
    insulin_rows,
    insulin_times,
    meal_rows,
    meal_times,
    activity_rows,
    activity_times,
) -> dict:
    baseline = (
        _nearest_glucose_value(
            glucose_rows,
            glucose_times,
            decision_t0,
            past_only=True,
        )
    )

    linked_dose_ids = {
        dose.id
        for dose
        in linked_doses
    }

    first_action = (
        _first_future_action_minutes_for_meal(
            decision_t0=decision_t0,
            selected_meal_id=
                selected_meal_id,
            linked_dose_ids=
                linked_dose_ids,
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
            baseline,
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


def estimate_meal_linked_shadow_action(
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

    planned_meal = (
        input_snapshot.get(
            "planned_meal"
        )
    )

    if planned_meal is None:
        return _abstain(
            "MISSING_PLANNED_MEAL_V2"
        )

    planned_carbs = (
        planned_meal.get(
            "carbohydrates_g"
        )
    )

    if planned_carbs is None:
        return _abstain(
            "MISSING_PLANNED_MEAL_CARBS_V2"
        )

    timezone = ZoneInfo(
        user.timezone
    )

    decision_t0 = (
        _parse_datetime(
            input_snapshot[
                "decision_at"
            ]
        )
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
        return _abstain(
            "MISSING_CURRENT_GLUCOSE_V2"
        )

    preload_start = (
        decision_t0
        - timedelta(
            days=HISTORY_DAYS,
            hours=2,
        )
    )

    candidate_start = (
        decision_t0
        - timedelta(
            days=HISTORY_DAYS
        )
    )

    candidate_end = (
        decision_t0
        - timedelta(
            hours=
                REFERENCE_SAFETY_HOURS
        )
    )

    cache = (
        _prepare_real_cache(
            db=db,
            user_id=user_id,
            search_t0=decision_t0,
            preload_start=
                preload_start,
        )
    )

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

    reference_groups = (
        _meal_reference_groups(
            cache=cache,
            candidate_start=
                candidate_start,
            candidate_end=
                candidate_end,
        )
    )

    historical_snapshots = []

    for group in reference_groups:
        meal = (
            group[
                "meal"
            ]
        )

        first_dose = (
            group[
                "first_dose"
            ]
        )

        (
            historical_t0,
            historical_situation,
        ) = (
            _build_planned_meal_reference_situation(
                cache=cache,
                meal=meal,
                first_dose=
                    first_dose,
                timezone=
                    timezone,
            )
        )

        outcome = (
            _build_clean_meal_outcome(
                decision_t0=
                    historical_t0,
                selected_meal_id=
                    meal.id,
                linked_doses=
                    group[
                        "linked_doses"
                    ],
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
                "meal": meal,
                "decision_t0":
                    historical_t0,
                "situation":
                    historical_situation,
                "dose_units":
                    group[
                        "total_units"
                    ],
                "strategy":
                    group[
                        "strategy"
                    ],
                "dose_count":
                    len(
                        group[
                            "linked_doses"
                        ]
                    ),
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

    rejected_by_gate = {
        "CARB_DISTANCE": 0,
        "GLUCOSE_DISTANCE": 0,
        "ACTIVE_INSULIN_DISTANCE": 0,
    }

    for reference in historical_snapshots:
        (
            gate_ok,
            gate_reason,
        ) = (
            _passes_meal_gates(
                current=
                    current_situation,
                reference=
                    reference[
                        "situation"
                    ],
            )
        )

        if not gate_ok:
            rejected_by_gate[
                gate_reason
            ] += 1

            continue

        context = (
            _meal_context_score(
                current=
                    current_situation,
                reference=
                    reference[
                        "situation"
                    ],
            )
        )

        if (
            context[
                "coverage"
            ]
            < MIN_MEAL_CONTEXT_COVERAGE
        ):
            continue

        recency = (
            _recency_factor(
                target_t0=
                    decision_t0,
                reference_t0=
                    reference[
                        "decision_t0"
                    ],
            )
        )

        context_rank = (
            context[
                "score"
            ]
            * recency
        )

        comparisons.append(
            {
                **reference,
                "similarity":
                    context[
                        "score"
                    ],
                "coverage":
                    context[
                        "coverage"
                    ],
                "context_rank":
                    round(
                        context_rank,
                        2,
                    ),
                "context_components":
                    context[
                        "components"
                    ],
                "recency_factor":
                    recency,
            }
        )

    local_comparisons = (
        _select_local_neighborhood(
            comparisons
        )
    )

    top_matches = (
        _select_diverse_top_k(
            local_comparisons
        )
    )

    evidence_cases = []
    evidence_snapshot_matches = []

    for match in top_matches:
        evidence_score = (
            _meal_evidence_score(
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
                recency_factor=
                    match[
                        "recency_factor"
                    ],
            )
        )

        dose_units = float(
            match[
                "dose_units"
            ]
        )

        case = {
            "dose_units":
                dose_units,
            "evidence_score":
                evidence_score,
        }

        evidence_cases.append(
            case
        )

        if evidence_score is None:
            evidence_level = (
                "NO_DATA"
            )

        elif (
            evidence_score >= 60.0
        ):
            evidence_level = (
                "STRONG"
            )

        elif (
            evidence_score
            >= DEFAULT_MIN_EVIDENCE_SCORE
        ):
            evidence_level = (
                "MODERATE"
            )

        else:
            evidence_level = (
                "WEAK"
            )

        evidence_snapshot_matches.append(
            {
                "decision_at":
                    match[
                        "decision_t0"
                    ].isoformat(),

                "meal_carbohydrates_g":
                    float(
                        match[
                            "meal"
                        ].carbohydrates_g
                    ),

                "dose_units":
                    dose_units,

                "strategy":
                    match[
                        "strategy"
                    ],

                "dose_count":
                    match[
                        "dose_count"
                    ],

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

                "recency_factor":
                    match[
                        "recency_factor"
                    ],

                "context_components":
                    match[
                        "context_components"
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
                    evidence_level,

                "selected_for_estimate":
                    False,
            }
        )

    cluster = (
        _select_dominant_dose_cluster(
            evidence_cases
        )
    )

    selected_cases = (
        cluster[
            "selected_cases"
        ]
    )

    selected_ids = {
        id(
            case
        )
        for case
        in selected_cases
    }

    for (
        case,
        snapshot_match,
    ) in zip(
        evidence_cases,
        evidence_snapshot_matches,
    ):
        snapshot_match[
            "selected_for_estimate"
        ] = (
            id(
                case
            )
            in selected_ids
        )

    summary_cases = (
        selected_cases
        if selected_cases
        else evidence_cases
    )

    (
        strongest_evidence,
        average_evidence,
    ) = (
        _evidence_summary(
            summary_cases
        )
    )

    best_context_rank = (
        max(
            (
                float(
                    item[
                        "context_rank"
                    ]
                )
                for item
                in comparisons
            ),
            default=None,
        )
    )

    evidence_snapshot = {
        "engine_version":
            ENGINE_VERSION,

        "history_days":
            HISTORY_DAYS,

        "safety_hours":
            REFERENCE_SAFETY_HOURS,

        "top_k":
            TOP_K,

        "minimum_context_coverage":
            MIN_MEAL_CONTEXT_COVERAGE,

        "minimum_evidence_score":
            DEFAULT_MIN_EVIDENCE_SCORE,

        "minimum_support_cases":
            DEFAULT_MIN_SUPPORT_CASES,

        "reference_group":
            "MEAL_LINKED_TOTAL",

        "planned_meal_carbohydrates_g":
            float(
                planned_carbs
            ),

        "weights": {
            "carbs":
                CARB_WEIGHT,
            "glucose":
                GLUCOSE_WEIGHT,
            "trend":
                TREND_WEIGHT,
            "active_insulin":
                ACTIVE_INSULIN_WEIGHT,
            "time":
                TIME_WEIGHT,
            "basal":
                BASAL_WEIGHT,
        },

        "local_neighborhood": {
            "max_context_gap":
                LOCAL_CONTEXT_MAX_GAP,

            "min_context_ratio":
                LOCAL_CONTEXT_MIN_RATIO,

            "best_context_rank":
                best_context_rank,

            "before_local_filter":
                len(
                    comparisons
                ),

            "after_local_filter":
                len(
                    local_comparisons
                ),
        },

        "dose_cluster": {
            "status":
                cluster[
                    "status"
                ],

            "usable_count":
                cluster[
                    "usable_count"
                ],

            "selected_count":
                len(
                    selected_cases
                ),

            "dose_min":
                cluster[
                    "dose_min"
                ],

            "dose_max":
                cluster[
                    "dose_max"
                ],

            "dose_range":
                cluster[
                    "dose_range"
                ],

            "cluster_center":
                cluster[
                    "cluster_center"
                ],

            "cluster_count":
                cluster[
                    "cluster_count"
                ],

            "cluster_weight_share":
                cluster[
                    "cluster_weight_share"
                ],

            "window_units":
                DOMINANT_CLUSTER_WINDOW_U,

            "minimum_weight_share":
                DOMINANT_CLUSTER_MIN_WEIGHT_SHARE,

            "uncontested_range_units":
                UNCONTESTED_DOSE_RANGE_U,
        },

        "rejected_by_gate":
            rejected_by_gate,

        "historical_meal_count":
            len(
                historical_snapshots
            ),

        "candidate_count":
            len(
                comparisons
            ),

        "local_candidate_count":
            len(
                local_comparisons
            ),

        "top_match_count":
            len(
                top_matches
            ),

        "matches":
            evidence_snapshot_matches,
    }

    if (
        cluster[
            "status"
        ]
        == "DISAGREEMENT"
    ):
        usable_count = (
            cluster[
                "usable_count"
            ]
        )

        return _abstain(
            reason=
                "DOSE_DISAGREEMENT_V2_MEAL",

            evidence_snapshot=
                evidence_snapshot,

            support_count=
                usable_count,

            strongest_evidence=
                strongest_evidence,

            average_evidence=
                average_evidence,
        )

    estimate = (
        estimate_research_action(
            selected_cases
        )
    )

    if (
        estimate[
            "status"
        ]
        != "ESTIMATED"
    ):
        return _abstain(
            reason=
                "INSUFFICIENT_EVIDENCE_V2_MEAL",

            evidence_snapshot=
                evidence_snapshot,

            support_count=
                estimate[
                    "support_count"
                ],

            strongest_evidence=
                strongest_evidence,

            average_evidence=
                average_evidence,
        )

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

        "model_version":
            MODEL_VERSION,
    }