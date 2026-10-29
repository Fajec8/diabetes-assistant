from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_plan import ActionPlan
from app.models.decision_session import (
    DecisionSession,
)
from app.services.meal_shadow_engine_v2 import (
    estimate_meal_linked_shadow_action,
)
from app.services.predose_shadow_engine import (
    estimate_unlinked_shadow_action,
)


NO_MEAL_MODEL_VERSION = "SHADOW_V1_1"
MEAL_MODEL_VERSION = "SHADOW_V2_MEAL_4"
ROUTER_VERSION = "SHADOW_V2_FULL_CONTEXT_4"

MODEL_VERSION = NO_MEAL_MODEL_VERSION


def classify_shadow_v1(
    input_snapshot: dict,
) -> dict:
    planned_meal = input_snapshot.get(
        "planned_meal"
    )

    if planned_meal is not None:
        return {
            "action":
                "ABSTAIN",

            "abstain_reason":
                "MEAL_CONTEXT_NOT_SUPPORTED_V1",
        }

    return {
        "action":
            "RUN_ESTIMATOR",

        "abstain_reason":
            None,
    }


def classify_shadow_v2(
    input_snapshot: dict,
) -> dict:
    planned_meal = input_snapshot.get(
        "planned_meal"
    )

    if planned_meal is not None:
        return {
            "action":
                "RUN_MEAL_ESTIMATOR",

            "model_version":
                MEAL_MODEL_VERSION,

            "router_version":
                ROUTER_VERSION,

            "abstain_reason":
                None,
        }

    return {
        "action":
            "RUN_UNLINKED_ESTIMATOR",

        "model_version":
            NO_MEAL_MODEL_VERSION,

        "router_version":
            ROUTER_VERSION,

        "abstain_reason":
            None,
    }


def _create_action_plan_from_result(
    session: DecisionSession,
    result: dict,
    fallback_model_version: str,
) -> ActionPlan:
    model_version = (
        result.get(
            "model_version"
        )
        or fallback_model_version
    )

    if (
        result[
            "status"
        ]
        == "ESTIMATED"
    ):
        estimated_units = float(
            result[
                "estimated_units"
            ]
        )

        return ActionPlan(
            session_id=
                session.id,

            source=
                "SYSTEM_SHADOW",

            status=
                "PLAN",

            strategy=
                "SINGLE",

            total_novorapid_units=
                estimated_units,

            prebolus_minutes=
                None,

            first_dose_units=
                estimated_units,

            second_dose_units=
                None,

            second_dose_delay_minutes=
                None,

            model_version=
                model_version,

            confidence_score=
                None,

            confidence_level=
                None,

            support_count=
                result[
                    "support_count"
                ],

            strongest_evidence=
                result[
                    "strongest_evidence"
                ],

            average_evidence=
                result[
                    "average_evidence"
                ],

            evidence_snapshot=
                result[
                    "evidence_snapshot"
                ],

            abstain_reason=
                None,

            revealed_at=
                None,
        )

    return ActionPlan(
        session_id=
            session.id,

        source=
            "SYSTEM_SHADOW",

        status=
            "ABSTAIN",

        strategy=
            None,

        total_novorapid_units=
            None,

        prebolus_minutes=
            None,

        first_dose_units=
            None,

        second_dose_units=
            None,

        second_dose_delay_minutes=
            None,

        model_version=
            model_version,

        confidence_score=
            None,

        confidence_level=
            None,

        support_count=
            result[
                "support_count"
            ],

        strongest_evidence=
            result[
                "strongest_evidence"
            ],

        average_evidence=
            result[
                "average_evidence"
            ],

        evidence_snapshot=
            result[
                "evidence_snapshot"
            ],

        abstain_reason=
            result[
                "abstain_reason"
            ],

        revealed_at=
            None,
    )


def create_system_shadow_plan(
    db: Session,
    session: DecisionSession,
) -> ActionPlan:
    existing = db.scalar(
        select(
            ActionPlan
        )
        .where(
            ActionPlan.session_id
            == session.id,

            ActionPlan.source
            == "SYSTEM_SHADOW",
        )
    )

    if existing is not None:
        return existing

    classification = (
        classify_shadow_v2(
            session.input_snapshot
        )
    )

    if (
        classification[
            "action"
        ]
        == "RUN_MEAL_ESTIMATOR"
    ):
        result = (
            estimate_meal_linked_shadow_action(
                db=db,

                user_id=
                    session.user_id,

                input_snapshot=
                    session.input_snapshot,
            )
        )

    else:
        result = (
            estimate_unlinked_shadow_action(
                db=db,

                user_id=
                    session.user_id,

                input_snapshot=
                    session.input_snapshot,
            )
        )

    plan = (
        _create_action_plan_from_result(
            session=session,

            result=result,

            fallback_model_version=
                classification[
                    "model_version"
                ],
        )
    )

    db.add(
        plan
    )

    return plan