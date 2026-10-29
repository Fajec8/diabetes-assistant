from datetime import (
    datetime,
    timedelta,
    timezone,
)
from types import SimpleNamespace

from app.services.meal_shadow_engine_v2 import (
    MODEL_VERSION,
    _meal_context_score,
    _meal_reference_groups,
    _passes_meal_gates,
    _select_dominant_dose_cluster,
    _select_local_neighborhood,
)
from app.services.shadow_v1 import (
    classify_shadow_v1,
    classify_shadow_v2,
)


def _situation(
    carbs=60.0,
    glucose=7.0,
    delta_15=0.0,
    delta_30=0.0,
    delta_60=0.0,
    active_insulin=0.0,
    time_minutes=720,
    basal_units=20.0,
):
    return {
        "meal": {
            "last_meal_carbs":
                carbs,
        },

        "glucose": {
            "current":
                glucose,

            "delta_15m":
                delta_15,

            "delta_30m":
                delta_30,

            "delta_60m":
                delta_60,
        },

        "novorapid": {
            "estimated_active_units":
                active_insulin,
        },

        "time": {
            "minutes_from_midnight":
                time_minutes,
        },

        "tresiba": {
            "last_basal_units":
                basal_units,
        },
    }


def test_v1_remains_frozen_for_meal_context():
    result = classify_shadow_v1(
        {
            "planned_meal": {
                "carbohydrates_g":
                    60.0,
            }
        }
    )

    assert (
        result[
            "action"
        ]
        == "ABSTAIN"
    )

    assert (
        result[
            "abstain_reason"
        ]
        == "MEAL_CONTEXT_NOT_SUPPORTED_V1"
    )


def test_v2_routes_meal_context_to_meal_estimator():
    result = classify_shadow_v2(
        {
            "planned_meal": {
                "carbohydrates_g":
                    60.0,
            }
        }
    )

    assert (
        result[
            "action"
        ]
        == "RUN_MEAL_ESTIMATOR"
    )

    assert (
        result[
            "model_version"
        ]
        == MODEL_VERSION
    )

    assert (
        MODEL_VERSION
        == "SHADOW_V2_MEAL_4"
    )


def test_v2_routes_no_meal_context_to_frozen_v1_estimator():
    result = classify_shadow_v2(
        {
            "planned_meal":
                None,
        }
    )

    assert (
        result[
            "action"
        ]
        == "RUN_UNLINKED_ESTIMATOR"
    )

    assert (
        result[
            "model_version"
        ]
        == "SHADOW_V1_1"
    )


def test_meal_reference_group_uses_total_linked_bolus():
    meal_id = "meal-1"

    eaten_at = datetime(
        2026,
        10,
        1,
        12,
        0,
        tzinfo=
            timezone.utc,
    )

    meal = SimpleNamespace(
        id=meal_id,
        eaten_at=eaten_at,
        carbohydrates_g=70.0,
    )

    first = SimpleNamespace(
        id="dose-1",
        administered_at=(
            eaten_at
            - timedelta(
                minutes=10
            )
        ),
        units=4.0,
    )

    second = SimpleNamespace(
        id="dose-2",
        administered_at=(
            eaten_at
            + timedelta(
                minutes=45
            )
        ),
        units=2.0,
    )

    too_late = SimpleNamespace(
        id="dose-3",
        administered_at=(
            eaten_at
            + timedelta(
                minutes=240
            )
        ),
        units=3.0,
    )

    cache = SimpleNamespace(
        meals=[
            meal
        ],
        novorapid_doses_by_meal={
            meal_id: [
                first,
                second,
                too_late,
            ]
        },
    )

    groups = (
        _meal_reference_groups(
            cache=cache,

            candidate_start=(
                eaten_at
                - timedelta(
                    days=1
                )
            ),

            candidate_end=(
                eaten_at
                + timedelta(
                    days=1
                )
            ),
        )
    )

    assert (
        len(
            groups
        )
        == 1
    )

    assert (
        groups[
            0
        ][
            "total_units"
        ]
        == 6.0
    )

    assert (
        groups[
            0
        ][
            "strategy"
        ]
        == "SPLIT"
    )

    assert (
        len(
            groups[
                0
            ][
                "linked_doses"
            ]
        )
        == 2
    )


def test_meal_gate_rejects_large_carb_difference():
    current = _situation(
        carbs=30.0,
    )

    reference = _situation(
        carbs=70.0,
    )

    (
        allowed,
        reason,
    ) = _passes_meal_gates(
        current,
        reference,
    )

    assert allowed is False
    assert reason == "CARB_DISTANCE"


def test_meal_gate_rejects_large_active_insulin_difference():
    current = _situation(
        carbs=30.0,
        active_insulin=6.7,
    )

    reference = _situation(
        carbs=30.0,
        active_insulin=0.1,
    )

    (
        allowed,
        reason,
    ) = _passes_meal_gates(
        current,
        reference,
    )

    assert allowed is False

    assert (
        reason
        == "ACTIVE_INSULIN_DISTANCE"
    )


def test_meal_gate_accepts_close_active_insulin_context():
    current = _situation(
        carbs=30.0,
        active_insulin=6.7,
    )

    reference = _situation(
        carbs=30.0,
        active_insulin=4.3,
    )

    (
        allowed,
        reason,
    ) = _passes_meal_gates(
        current,
        reference,
    )

    assert allowed is True
    assert reason is None


def test_meal_context_prefers_closer_carbs_and_active_insulin():
    current = _situation(
        carbs=30.0,
        glucose=8.5,
        delta_15=-0.2,
        delta_30=-1.2,
        delta_60=-3.1,
        active_insulin=6.7,
        time_minutes=1221,
        basal_units=22.0,
    )

    close_reference = _situation(
        carbs=30.0,
        glucose=9.3,
        delta_15=-1.0,
        delta_30=-1.6,
        delta_60=-2.5,
        active_insulin=3.9,
        time_minutes=1331,
        basal_units=22.0,
    )

    bad_reference = _situation(
        carbs=70.0,
        glucose=10.0,
        delta_15=-0.5,
        delta_30=-1.1,
        delta_60=-2.2,
        active_insulin=0.09,
        time_minutes=1212,
        basal_units=19.0,
    )

    close_score = (
        _meal_context_score(
            current,
            close_reference,
        )[
            "score"
        ]
    )

    bad_score = (
        _meal_context_score(
            current,
            bad_reference,
        )[
            "score"
        ]
    )

    assert (
        close_score
        > bad_score
    )


def test_local_neighborhood_removes_distant_matches():
    comparisons = [
        {
            "context_rank":
                92.0,
        },
        {
            "context_rank":
                89.0,
        },
        {
            "context_rank":
                86.0,
        },
        {
            "context_rank":
                81.0,
        },
        {
            "context_rank":
                70.0,
        },
    ]

    selected = (
        _select_local_neighborhood(
            comparisons
        )
    )

    scores = [
        item[
            "context_rank"
        ]
        for item
        in selected
    ]

    assert 92.0 in scores
    assert 89.0 in scores
    assert 86.0 in scores
    assert 81.0 not in scores
    assert 70.0 not in scores


def test_dominant_cluster_ignores_single_high_dose_outlier():
    cases = [
        {
            "dose_units":
                4.0,
            "evidence_score":
                70.0,
        },
        {
            "dose_units":
                4.5,
            "evidence_score":
                65.0,
        },
        {
            "dose_units":
                5.0,
            "evidence_score":
                60.0,
        },
        {
            "dose_units":
                8.5,
            "evidence_score":
                45.0,
        },
    ]

    result = (
        _select_dominant_dose_cluster(
            cases
        )
    )

    assert (
        result[
            "status"
        ]
        == "DOMINANT_CLUSTER"
    )

    selected_doses = [
        case[
            "dose_units"
        ]
        for case
        in result[
            "selected_cases"
        ]
    ]

    assert 4.0 in selected_doses
    assert 4.5 in selected_doses
    assert 5.0 in selected_doses
    assert 8.5 not in selected_doses


def test_dominant_cluster_rejects_even_split_history():
    cases = [
        {
            "dose_units":
                3.0,
            "evidence_score":
                65.0,
        },
        {
            "dose_units":
                3.5,
            "evidence_score":
                60.0,
        },
        {
            "dose_units":
                8.0,
            "evidence_score":
                65.0,
        },
        {
            "dose_units":
                8.5,
            "evidence_score":
                60.0,
        },
    ]

    result = (
        _select_dominant_dose_cluster(
            cases
        )
    )

    assert (
        result[
            "status"
        ]
        == "DISAGREEMENT"
    )

    assert (
        result[
            "selected_cases"
        ]
        == []
    )


def test_close_doses_are_uncontested_without_clustering():
    cases = [
        {
            "dose_units":
                4.0,
            "evidence_score":
                55.0,
        },
        {
            "dose_units":
                5.0,
            "evidence_score":
                60.0,
        },
        {
            "dose_units":
                6.0,
            "evidence_score":
                65.0,
        },
    ]

    result = (
        _select_dominant_dose_cluster(
            cases
        )
    )

    assert (
        result[
            "status"
        ]
        == "UNCONTESTED"
    )

    assert (
        len(
            result[
                "selected_cases"
            ]
        )
        == 3
    )


def test_weak_evidence_does_not_control_dominant_cluster():
    cases = [
        {
            "dose_units":
                4.0,
            "evidence_score":
                70.0,
        },
        {
            "dose_units":
                4.5,
            "evidence_score":
                65.0,
        },
        {
            "dose_units":
                9.0,
            "evidence_score":
                20.0,
        },
        {
            "dose_units":
                10.0,
            "evidence_score":
                25.0,
        },
    ]

    result = (
        _select_dominant_dose_cluster(
            cases
        )
    )

    assert (
        result[
            "status"
        ]
        == "UNCONTESTED"
    )

    assert (
        len(
            result[
                "selected_cases"
            ]
        )
        == 2
    )