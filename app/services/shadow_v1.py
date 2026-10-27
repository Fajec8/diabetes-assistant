from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_plan import ActionPlan
from app.models.decision_session import (
    DecisionSession,
)
from app.services.predose_shadow_engine import (
    estimate_unlinked_shadow_action,
)


MODEL_VERSION = "SHADOW_V1_1"


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
        classify_shadow_v1(
            session.input_snapshot
        )
    )

    if (
        classification[
            "action"
        ]
        == "ABSTAIN"
    ):
        plan = ActionPlan(
            session_id=session.id,

            source="SYSTEM_SHADOW",
            status="ABSTAIN",

            strategy=None,

            total_novorapid_units=None,
            prebolus_minutes=None,

            first_dose_units=None,
            second_dose_units=None,

            second_dose_delay_minutes=None,

            model_version=
                MODEL_VERSION,

            confidence_score=None,
            confidence_level=None,

            support_count=0,

            strongest_evidence=None,
            average_evidence=None,

            evidence_snapshot=None,

            abstain_reason=
                classification[
                    "abstain_reason"
                ],

            revealed_at=None,
        )

        db.add(
            plan
        )

        return plan

    result = (
        estimate_unlinked_shadow_action(
            db=db,
            user_id=session.user_id,
            input_snapshot=
                session.input_snapshot,
        )
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

        plan = ActionPlan(
            session_id=session.id,

            source="SYSTEM_SHADOW",
            status="PLAN",

            strategy="SINGLE",

            total_novorapid_units=
                estimated_units,

            prebolus_minutes=None,

            first_dose_units=
                estimated_units,

            second_dose_units=None,
            second_dose_delay_minutes=None,

            model_version=
                MODEL_VERSION,

            confidence_score=None,
            confidence_level=None,

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

            abstain_reason=None,

            revealed_at=None,
        )

    else:
        plan = ActionPlan(
            session_id=session.id,

            source="SYSTEM_SHADOW",
            status="ABSTAIN",

            strategy=None,

            total_novorapid_units=None,
            prebolus_minutes=None,

            first_dose_units=None,
            second_dose_units=None,

            second_dose_delay_minutes=None,

            model_version=
                MODEL_VERSION,

            confidence_score=None,
            confidence_level=None,

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

            revealed_at=None,
        )

    db.add(
        plan
    )

    return plan