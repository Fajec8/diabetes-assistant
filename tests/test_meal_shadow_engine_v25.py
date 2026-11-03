from __future__ import annotations

import app.services.meal_shadow_engine_v2 as base_engine
import app.services.meal_shadow_engine_v25 as v25


def _current(
    *,
    active: float | None,
    minutes: float | None,
) -> dict:
    return {
        "novorapid": {
            "estimated_active_units":
                active,

            "minutes_since_last_bolus":
                minutes,
        }
    }


def test_timing_on_for_high_active_insulin():
    current = _current(
        active=2.0,
        minutes=200.0,
    )

    assert (
        v25._should_use_timing(
            current
        )
        is True
    )


def test_timing_on_for_recent_moderate_active():
    current = _current(
        active=1.5,
        minutes=120.0,
    )

    assert (
        v25._should_use_timing(
            current
        )
        is True
    )


def test_timing_off_below_moderate_active():
    current = _current(
        active=1.49,
        minutes=100.0,
    )

    assert (
        v25._should_use_timing(
            current
        )
        is False
    )


def test_timing_off_when_moderate_active_is_old():
    current = _current(
        active=1.5,
        minutes=121.0,
    )

    assert (
        v25._should_use_timing(
            current
        )
        is False
    )


def test_low_support_guard():
    result = {
        "status":
            "ESTIMATED",

        "support_count":
            2,

        "strongest_evidence":
            59.99,
    }

    assert (
        v25._should_low_support_abstain(
            result
        )
        is True
    )


def test_low_support_guard_keeps_strong_case():
    result = {
        "status":
            "ESTIMATED",

        "support_count":
            2,

        "strongest_evidence":
            60.0,
    }

    assert (
        v25._should_low_support_abstain(
            result
        )
        is False
    )


def test_wrapper_applies_v25_configuration_and_restores_base(
    monkeypatch,
):
    original_window = (
        base_engine
        .DOMINANT_CLUSTER_WINDOW_U
    )

    original_score = (
        base_engine
        ._meal_context_score
    )

    def fake_estimator(
        db,
        user_id,
        input_snapshot,
    ):
        assert (
            base_engine
            .DOMINANT_CLUSTER_WINDOW_U
            == 2.5
        )

        assert (
            base_engine
            ._meal_context_score
            is v25._v25_context_score
        )

        return {
            "status":
                "ESTIMATED",

            "estimated_units":
                5.5,

            "support_count":
                4,

            "strongest_evidence":
                72.0,

            "average_evidence":
                66.0,

            "abstain_reason":
                None,

            "evidence_snapshot": {
                "engine_version":
                    "PRE_DOSE_EVIDENCE_V2_MEAL_4",
            },

            "model_version":
                "SHADOW_V2_MEAL_4",
        }

    monkeypatch.setattr(
        base_engine,
        "estimate_meal_linked_shadow_action",
        fake_estimator,
    )

    result = (
        v25
        .estimate_meal_linked_shadow_action(
            db=object(),
            user_id="test-user",
            input_snapshot={},
        )
    )

    assert (
        result[
            "status"
        ]
        == "ESTIMATED"
    )

    assert (
        result[
            "estimated_units"
        ]
        == 5.5
    )

    assert (
        result[
            "model_version"
        ]
        == "SHADOW_V2_5_MEAL_1"
    )

    snapshot = result[
        "evidence_snapshot"
    ]

    assert (
        snapshot[
            "engine_version"
        ]
        == "PRE_DOSE_EVIDENCE_V2_5_MEAL_1"
    )

    config = snapshot[
        "v25_configuration"
    ]

    assert (
        config[
            "dominant_cluster_window_u"
        ]
        == 2.5
    )

    assert (
        config[
            "low_support_guard_applied"
        ]
        is False
    )

    assert (
        base_engine
        .DOMINANT_CLUSTER_WINDOW_U
        == original_window
    )

    assert (
        base_engine
        ._meal_context_score
        is original_score
    )


def test_wrapper_turns_low_support_result_into_abstain(
    monkeypatch,
):
    def fake_estimator(
        db,
        user_id,
        input_snapshot,
    ):
        return {
            "status":
                "ESTIMATED",

            "estimated_units":
                7.5,

            "support_count":
                2,

            "strongest_evidence":
                58.0,

            "average_evidence":
                55.0,

            "abstain_reason":
                None,

            "evidence_snapshot":
                {},

            "model_version":
                "SHADOW_V2_MEAL_4",
        }

    monkeypatch.setattr(
        base_engine,
        "estimate_meal_linked_shadow_action",
        fake_estimator,
    )

    result = (
        v25
        .estimate_meal_linked_shadow_action(
            db=object(),
            user_id="test-user",
            input_snapshot={},
        )
    )

    assert (
        result[
            "status"
        ]
        == "ABSTAIN"
    )

    assert (
        result[
            "estimated_units"
        ]
        is None
    )

    assert (
        result[
            "abstain_reason"
        ]
        == "LOW_SUPPORT_GUARD_V25"
    )

    assert (
        result[
            "model_version"
        ]
        == "SHADOW_V2_5_MEAL_1"
    )

    assert (
        result[
            "evidence_snapshot"
        ][
            "v25_configuration"
        ][
            "low_support_guard_applied"
        ]
        is True
    )