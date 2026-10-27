from __future__ import annotations

import uuid
from datetime import (
    datetime,
    timezone,
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_plan import ActionPlan
from app.models.decision_outcome import (
    DecisionOutcome,
)
from app.models.decision_session import (
    DecisionSession,
)
from app.models.user import User

from app.schemas.decision import (
    ActionPlanCreate,
    DecisionOutcomeCreate,
    DecisionSessionCreate,
)
from app.services.outcome_quality import (
    evaluate_outcome_quality,
)
from app.services.shadow_v1 import (
    create_system_shadow_plan,
)


def _serialize_action_plan(
    plan: ActionPlan | None,
) -> dict | None:
    if plan is None:
        return None

    return {
        "id":
            str(
                plan.id
            ),

        "source":
            plan.source,

        "status":
            plan.status,

        "strategy":
            plan.strategy,

        "total_novorapid_units":
            plan.total_novorapid_units,

        "prebolus_minutes":
            plan.prebolus_minutes,

        "first_dose_units":
            plan.first_dose_units,

        "second_dose_units":
            plan.second_dose_units,

        "second_dose_delay_minutes":
            plan.second_dose_delay_minutes,

        "model_version":
            plan.model_version,

        "confidence_score":
            plan.confidence_score,

        "confidence_level":
            plan.confidence_level,

        "support_count":
            plan.support_count,

        "strongest_evidence":
            plan.strongest_evidence,

        "average_evidence":
            plan.average_evidence,

        "abstain_reason":
            plan.abstain_reason,

        "revealed_at":
            plan.revealed_at,

        "created_at":
            plan.created_at,
    }


def _serialize_outcome(
    outcome: DecisionOutcome | None,
) -> dict | None:
    if outcome is None:
        return None

    return {
        "id":
            str(
                outcome.id
            ),

        "baseline_glucose":
            outcome.baseline_glucose,

        "glucose_30m":
            outcome.glucose_30m,

        "glucose_60m":
            outcome.glucose_60m,

        "glucose_90m":
            outcome.glucose_90m,

        "glucose_120m":
            outcome.glucose_120m,

        "glucose_180m":
            outcome.glucose_180m,

        "quality_score":
            outcome.quality_score,

        "quality_status":
            outcome.quality_status,

        "confidence":
            outcome.confidence,

        "confidence_level":
            outcome.confidence_level,

        "low_detected":
            outcome.low_detected,

        "high_detected":
            outcome.high_detected,

        "evaluated_at":
            outcome.evaluated_at,

        "created_at":
            outcome.created_at,
    }


def build_decision_comparison(
    user_plan: ActionPlan | None,
    system_plan: ActionPlan | None,
    outcome: DecisionOutcome | None,
) -> dict | None:
    if outcome is None:
        return None

    comparison = {
        "user": {
            "status":
                (
                    user_plan.status
                    if user_plan
                    else None
                ),

            "strategy":
                (
                    user_plan.strategy
                    if user_plan
                    else None
                ),

            "total_novorapid_units":
                (
                    user_plan.total_novorapid_units
                    if user_plan
                    else None
                ),
        },

        "system": {
            "status":
                (
                    system_plan.status
                    if system_plan
                    else None
                ),

            "strategy":
                (
                    system_plan.strategy
                    if system_plan
                    else None
                ),

            "total_novorapid_units":
                (
                    system_plan.total_novorapid_units
                    if system_plan
                    else None
                ),

            "model_version":
                (
                    system_plan.model_version
                    if system_plan
                    else None
                ),

            "support_count":
                (
                    system_plan.support_count
                    if system_plan
                    else None
                ),

            "strongest_evidence":
                (
                    system_plan.strongest_evidence
                    if system_plan
                    else None
                ),
        },

        "outcome": {
            "quality_score":
                outcome.quality_score,

            "quality_status":
                outcome.quality_status,

            "confidence":
                outcome.confidence,

            "confidence_level":
                outcome.confidence_level,

            "low_detected":
                outcome.low_detected,

            "high_detected":
                outcome.high_detected,
        },

        "dose_difference_system_minus_user":
            None,

        "absolute_dose_difference":
            None,

        "same_strategy":
            None,
    }

    if (
        user_plan is not None
        and system_plan is not None
        and user_plan.status == "PLAN"
        and system_plan.status == "PLAN"
        and user_plan.total_novorapid_units
        is not None
        and system_plan.total_novorapid_units
        is not None
    ):
        signed_difference = round(
            float(
                system_plan
                .total_novorapid_units
            )
            - float(
                user_plan
                .total_novorapid_units
            ),
            2,
        )

        comparison[
            "dose_difference_system_minus_user"
        ] = signed_difference

        comparison[
            "absolute_dose_difference"
        ] = round(
            abs(
                signed_difference
            ),
            2,
        )

        comparison[
            "same_strategy"
        ] = (
            user_plan.strategy
            == system_plan.strategy
        )

    return comparison


def create_decision_session(
    db: Session,
    payload: DecisionSessionCreate,
):
    user = db.get(
        User,
        payload.user_id,
    )

    if user is None:
        raise ValueError(
            "User not found"
        )

    snapshot = {
        "schema_version":
            "1.0",

        "decision_at":
            payload.decision_at
            .isoformat(),

        "glucose":
            payload.glucose
            .model_dump(
                mode="json"
            ),

        "planned_meal":
            (
                payload.planned_meal
                .model_dump(
                    mode="json"
                )
                if payload.planned_meal
                is not None
                else None
            ),

        "recent_novorapid": [
            dose.model_dump(
                mode="json"
            )
            for dose
            in payload.recent_novorapid
        ],

        "tresiba":
            (
                payload.tresiba
                .model_dump(
                    mode="json"
                )
                if payload.tresiba
                is not None
                else None
            ),

        "activities": [
            activity.model_dump(
                mode="json"
            )
            for activity
            in payload.activities
        ],

        "note":
            payload.note,
    }

    session = DecisionSession(
        user_id=
            payload.user_id,

        decision_at=
            payload.decision_at,

        status=
            "WAITING_USER_PLAN",

        input_snapshot=
            snapshot,
    )

    db.add(
        session
    )

    # Potřebujeme session.id,
    # ale zatím nic necommitujeme.
    db.flush()

    # Shadow musí vzniknout ještě
    # PŘED user plánem.
    create_system_shadow_plan(
        db=db,
        session=session,
    )

    db.commit()

    db.refresh(
        session
    )

    return session


def create_user_action_plan(
    db: Session,
    session_id: uuid.UUID,
    payload: ActionPlanCreate,
):
    session = db.get(
        DecisionSession,
        session_id,
    )

    if session is None:
        raise KeyError(
            "Decision session not found"
        )

    if (
        session.status
        != "WAITING_USER_PLAN"
    ):
        raise RuntimeError(
            "Session is not waiting "
            "for a user plan"
        )

    existing_user = db.scalar(
        select(
            ActionPlan
        )
        .where(
            ActionPlan.session_id
            == session_id,

            ActionPlan.source
            == "USER",
        )
    )

    if existing_user is not None:
        raise RuntimeError(
            "User plan already exists "
            "for this session"
        )

    system_shadow = db.scalar(
        select(
            ActionPlan
        )
        .where(
            ActionPlan.session_id
            == session_id,

            ActionPlan.source
            == "SYSTEM_SHADOW",
        )
    )

    if system_shadow is None:
        raise RuntimeError(
            "SYSTEM_SHADOW is missing. "
            "User plan cannot be stored "
            "because blindness cannot be "
            "guaranteed."
        )

    plan = ActionPlan(
        session_id=
            session_id,

        source=
            "USER",

        status=
            "PLAN",

        strategy=
            payload.strategy,

        total_novorapid_units=
            payload.total_novorapid_units,

        prebolus_minutes=
            payload.prebolus_minutes,

        first_dose_units=
            payload.first_dose_units,

        second_dose_units=
            payload.second_dose_units,

        second_dose_delay_minutes=
            payload.second_dose_delay_minutes,

        revealed_at=
            None,
    )

    db.add(
        plan
    )

    session.status = (
        "WAITING_OUTCOME"
    )

    db.commit()

    db.refresh(
        plan
    )

    return plan


def create_decision_outcome(
    db: Session,
    session_id: uuid.UUID,
    payload: DecisionOutcomeCreate,
):
    session = db.get(
        DecisionSession,
        session_id,
    )

    if session is None:
        raise KeyError(
            "Decision session not found"
        )

    if (
        session.status
        != "WAITING_OUTCOME"
    ):
        raise RuntimeError(
            "Session is not waiting "
            "for an outcome"
        )

    existing_outcome = db.scalar(
        select(
            DecisionOutcome
        )
        .where(
            DecisionOutcome.session_id
            == session_id
        )
    )

    if existing_outcome is not None:
        raise RuntimeError(
            "Outcome already exists "
            "for this session"
        )

    user_plan = db.scalar(
        select(
            ActionPlan
        )
        .where(
            ActionPlan.session_id
            == session_id,

            ActionPlan.source
            == "USER",
        )
    )

    if user_plan is None:
        raise RuntimeError(
            "USER plan is missing"
        )

    system_shadow = db.scalar(
        select(
            ActionPlan
        )
        .where(
            ActionPlan.session_id
            == session_id,

            ActionPlan.source
            == "SYSTEM_SHADOW",
        )
    )

    if system_shadow is None:
        raise RuntimeError(
            "SYSTEM_SHADOW is missing"
        )

    raw_outcome = {
        "baseline_glucose":
            payload.baseline_glucose,

        "glucose_30m":
            payload.glucose_30m,

        "glucose_60m":
            payload.glucose_60m,

        "glucose_90m":
            payload.glucose_90m,

        "glucose_120m":
            payload.glucose_120m,

        "glucose_180m":
            payload.glucose_180m,
    }

    quality = (
        evaluate_outcome_quality(
            raw_outcome
        )
    )

    evaluated_at = (
        payload.evaluated_at
        if payload.evaluated_at
        is not None
        else datetime.now(
            timezone.utc
        )
    )

    outcome_snapshot = {
        "schema_version":
            "1.0",

        **raw_outcome,

        "note":
            payload.note,
    }

    outcome = DecisionOutcome(
        session_id=
            session_id,

        baseline_glucose=
            payload.baseline_glucose,

        glucose_30m=
            payload.glucose_30m,

        glucose_60m=
            payload.glucose_60m,

        glucose_90m=
            payload.glucose_90m,

        glucose_120m=
            payload.glucose_120m,

        glucose_180m=
            payload.glucose_180m,

        quality_score=
            quality[
                "quality_score"
            ],

        quality_status=
            quality[
                "status"
            ],

        confidence=
            quality[
                "confidence"
            ],

        confidence_level=
            quality[
                "confidence_level"
            ],

        low_detected=
            quality[
                "low_detected"
            ],

        high_detected=
            quality[
                "high_detected"
            ],

        outcome_snapshot=
            outcome_snapshot,

        evaluated_at=
            evaluated_at,
    )

    db.add(
        outcome
    )

    # Teprve tady končí blind fáze.
    system_shadow.revealed_at = (
        evaluated_at
    )

    session.status = (
        "COMPLETED"
    )

    db.commit()

    db.refresh(
        outcome
    )

    return outcome


def get_decision_session(
    db: Session,
    session_id: uuid.UUID,
):
    session = db.get(
        DecisionSession,
        session_id,
    )

    if session is None:
        raise KeyError(
            "Decision session not found"
        )

    plans = (
        db.scalars(
            select(
                ActionPlan
            )
            .where(
                ActionPlan.session_id
                == session_id
            )
            .order_by(
                ActionPlan.created_at
            )
        )
        .all()
    )

    user_plan = None
    system_plan = None

    for plan in plans:
        if (
            plan.source
            == "USER"
        ):
            user_plan = plan

        elif (
            plan.source
            == "SYSTEM_SHADOW"
        ):
            system_plan = plan

    outcome = db.scalar(
        select(
            DecisionOutcome
        )
        .where(
            DecisionOutcome.session_id
            == session_id
        )
    )

    system_shadow_available = (
        system_plan is not None
    )

    # Systémový výsledek zůstane
    # absolutně skrytý, dokud není
    # explicitně revealed.
    visible_system_shadow = None

    if (
        system_plan is not None
        and system_plan.revealed_at
        is not None
    ):
        visible_system_shadow = (
            _serialize_action_plan(
                system_plan
            )
        )

    comparison = None

    if (
        session.status
        == "COMPLETED"
        and system_plan is not None
        and system_plan.revealed_at
        is not None
        and outcome is not None
    ):
        comparison = (
            build_decision_comparison(
                user_plan=
                    user_plan,

                system_plan=
                    system_plan,

                outcome=
                    outcome,
            )
        )

    return {
        "id":
            str(
                session.id
            ),

        "user_id":
            str(
                session.user_id
            ),

        "decision_at":
            session.decision_at,

        "status":
            session.status,

        "input_snapshot":
            session.input_snapshot,

        "user_plan":
            _serialize_action_plan(
                user_plan
            ),

        "system_shadow_available":
            system_shadow_available,

        "system_shadow":
            visible_system_shadow,

        "outcome":
            _serialize_outcome(
                outcome
            ),

        "comparison":
            comparison,

        "created_at":
            session.created_at,
    }