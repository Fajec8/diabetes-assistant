from __future__ import annotations

from threading import Lock

from sqlalchemy.orm import Session

import app.services.meal_shadow_engine_v2 as base_engine


MODEL_VERSION = "SHADOW_V2_5_MEAL_1"
ENGINE_VERSION = "PRE_DOSE_EVIDENCE_V2_5_MEAL_1"

DOMINANT_CLUSTER_WINDOW_U = 2.5

LOW_SUPPORT_MAX_CASES = 2
LOW_SUPPORT_MIN_STRONGEST = 60.0

TIMING_ACTIVE_TRIGGER_U = 2.0
TIMING_RECENT_MAX_MINUTES = 120.0
TIMING_RECENT_MIN_ACTIVE_U = 1.5

LAST_BOLUS_UNITS_FULL_PENALTY = 6.0
LAST_BOLUS_AGE_FULL_PENALTY_MINUTES = 240.0


_BASE_MEAL_CONTEXT_SCORE = (
    base_engine._meal_context_score
)

_ENGINE_LOCK = Lock()


def _should_use_timing(
    current: dict,
) -> bool:
    novorapid = (
        current.get(
            "novorapid"
        )
        or {}
    )

    active = novorapid.get(
        "estimated_active_units"
    )

    minutes = novorapid.get(
        "minutes_since_last_bolus"
    )

    active_value = (
        float(active)
        if active is not None
        else 0.0
    )

    if (
        active_value
        >= TIMING_ACTIVE_TRIGGER_U
    ):
        return True

    if minutes is None:
        return False

    return (
        float(minutes)
        <= TIMING_RECENT_MAX_MINUTES
        and active_value
        >= TIMING_RECENT_MIN_ACTIVE_U
    )


def _v25_context_score(
    current: dict,
    reference: dict,
) -> dict:
    if not _should_use_timing(
        current
    ):
        return (
            _BASE_MEAL_CONTEXT_SCORE(
                current,
                reference,
            )
        )

    components = []

    def add_component(
        name: str,
        score,
        weight: float,
    ):
        if (
            score is None
            or weight <= 0
        ):
            return

        components.append(
            {
                "name":
                    name,

                "score":
                    float(
                        score
                    ),

                "weight":
                    float(
                        weight
                    ),
            }
        )

    add_component(
        "carbs",

        base_engine._linear_similarity(
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

            base_engine
            .CARB_FULL_PENALTY_G,
        ),

        base_engine.CARB_WEIGHT,
    )

    add_component(
        "glucose",

        base_engine._linear_similarity(
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

            base_engine
            .GLUCOSE_FULL_PENALTY_MMOL,
        ),

        base_engine.GLUCOSE_WEIGHT,
    )

    add_component(
        "trend",

        base_engine._trend_similarity(
            current[
                "glucose"
            ],

            reference[
                "glucose"
            ],
        ),

        base_engine.TREND_WEIGHT,
    )

    # Frozen V2.5 HYBRID_1_5:
    #
    # Original 20 points for active insulin
    # become:
    #
    # 10 points estimated active insulin
    #  5 points last bolus units
    #  5 points minutes since last bolus

    add_component(
        "active_insulin",

        base_engine._linear_similarity(
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

            base_engine
            .ACTIVE_INSULIN_FULL_PENALTY_U,
        ),

        10.0,
    )

    add_component(
        "last_bolus_units",

        base_engine._linear_similarity(
            current[
                "novorapid"
            ].get(
                "last_bolus_units"
            ),

            reference[
                "novorapid"
            ].get(
                "last_bolus_units"
            ),

            LAST_BOLUS_UNITS_FULL_PENALTY,
        ),

        5.0,
    )

    add_component(
        "minutes_since_last_bolus",

        base_engine._linear_similarity(
            current[
                "novorapid"
            ].get(
                "minutes_since_last_bolus"
            ),

            reference[
                "novorapid"
            ].get(
                "minutes_since_last_bolus"
            ),

            LAST_BOLUS_AGE_FULL_PENALTY_MINUTES,
        ),

        5.0,
    )

    add_component(
        "time",

        base_engine._time_similarity(
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

        base_engine.TIME_WEIGHT,
    )

    add_component(
        "basal",

        base_engine._linear_similarity(
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

            base_engine
            .BASAL_FULL_PENALTY_U,
        ),

        base_engine.BASAL_WEIGHT,
    )

    available_weight = sum(
        item[
            "weight"
        ]
        for item
        in components
    )

    total_weight = (
        base_engine.CARB_WEIGHT
        + base_engine.GLUCOSE_WEIGHT
        + base_engine.TREND_WEIGHT
        + 10.0
        + 5.0
        + 5.0
        + base_engine.TIME_WEIGHT
        + base_engine.BASAL_WEIGHT
    )

    if available_weight <= 0:
        return {
            "score":
                0.0,

            "coverage":
                0.0,

            "components":
                components,
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
        "score":
            round(
                score,
                2,
            ),

        "coverage":
            round(
                coverage,
                2,
            ),

        "components":
            components,
    }


def _should_low_support_abstain(
    result: dict,
) -> bool:
    if (
        result.get(
            "status"
        )
        != "ESTIMATED"
    ):
        return False

    support = (
        result.get(
            "support_count"
        )
        or 0
    )

    strongest = result.get(
        "strongest_evidence"
    )

    if strongest is None:
        return False

    return (
        support
        <= LOW_SUPPORT_MAX_CASES
        and float(
            strongest
        )
        < LOW_SUPPORT_MIN_STRONGEST
    )


def _add_v25_metadata(
    result: dict,
    *,
    low_support_guard_applied: bool,
) -> dict:
    result = dict(
        result
    )

    base_model_version = (
        result.get(
            "model_version"
        )
    )

    result[
        "model_version"
    ] = MODEL_VERSION

    evidence_snapshot = (
        result.get(
            "evidence_snapshot"
        )
    )

    if isinstance(
        evidence_snapshot,
        dict,
    ):
        evidence_snapshot = dict(
            evidence_snapshot
        )

        evidence_snapshot[
            "engine_version"
        ] = ENGINE_VERSION

        evidence_snapshot[
            "v25_configuration"
        ] = {
            "base_model_version":
                base_model_version,

            "dominant_cluster_window_u":
                DOMINANT_CLUSTER_WINDOW_U,

            "low_support_max_cases":
                LOW_SUPPORT_MAX_CASES,

            "low_support_min_strongest":
                LOW_SUPPORT_MIN_STRONGEST,

            "timing_active_trigger_u":
                TIMING_ACTIVE_TRIGGER_U,

            "timing_recent_max_minutes":
                TIMING_RECENT_MAX_MINUTES,

            "timing_recent_min_active_u":
                TIMING_RECENT_MIN_ACTIVE_U,

            "timing_weights": {
                "active_insulin":
                    10.0,

                "last_bolus_units":
                    5.0,

                "minutes_since_last_bolus":
                    5.0,
            },

            "low_support_guard_applied":
                low_support_guard_applied,
        }

        result[
            "evidence_snapshot"
        ] = evidence_snapshot

    return result


def estimate_meal_linked_shadow_action(
    db: Session,
    user_id,
    input_snapshot: dict,
) -> dict:
    # meal_shadow_engine_v2 contains the frozen
    # V2.4 implementation. V2.5 changes only:
    #
    # - dominant cluster window 1.5 -> 2.5 U
    # - conditional bolus timing similarity
    # - low-support guard
    #
    # The underlying engine is temporarily configured
    # inside a process-wide lock and immediately restored.
    #
    # The production Shadow route is the only web path
    # that calls this V2.5 wrapper.

    with _ENGINE_LOCK:
        original_window = (
            base_engine
            .DOMINANT_CLUSTER_WINDOW_U
        )

        original_context_score = (
            base_engine
            ._meal_context_score
        )

        try:
            base_engine.DOMINANT_CLUSTER_WINDOW_U = (
                DOMINANT_CLUSTER_WINDOW_U
            )

            base_engine._meal_context_score = (
                _v25_context_score
            )

            result = (
                base_engine
                .estimate_meal_linked_shadow_action(
                    db=db,
                    user_id=user_id,
                    input_snapshot=
                        input_snapshot,
                )
            )

        finally:
            base_engine.DOMINANT_CLUSTER_WINDOW_U = (
                original_window
            )

            base_engine._meal_context_score = (
                original_context_score
            )

    guard_applied = (
        _should_low_support_abstain(
            result
        )
    )

    result = _add_v25_metadata(
        result,
        low_support_guard_applied=
            guard_applied,
    )

    if guard_applied:
        result[
            "status"
        ] = "ABSTAIN"

        result[
            "estimated_units"
        ] = None

        result[
            "abstain_reason"
        ] = (
            "LOW_SUPPORT_GUARD_V25"
        )

    return result