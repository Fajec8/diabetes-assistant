from app.services.shadow_v1 import (
    MODEL_VERSION,
    classify_shadow_v1,
)


def test_shadow_v1_model_version():
    assert (
        MODEL_VERSION
        == "SHADOW_V1_1"
    )


def test_meal_context_abstains():
    snapshot = {
        "planned_meal": {
            "carbohydrates_g": 60,
        }
    }

    result = classify_shadow_v1(
        snapshot
    )

    assert (
        result["action"]
        == "ABSTAIN"
    )

    assert (
        result[
            "abstain_reason"
        ]
        == "MEAL_CONTEXT_NOT_SUPPORTED_V1"
    )


def test_no_meal_runs_estimator():
    snapshot = {
        "planned_meal": None
    }

    result = classify_shadow_v1(
        snapshot
    )

    assert (
        result["action"]
        == "RUN_ESTIMATOR"
    )

    assert (
        result[
            "abstain_reason"
        ]
        is None
    )