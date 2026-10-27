from __future__ import annotations

import sys
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.action_plan import ActionPlan
from app.models.decision_session import (
    DecisionSession,
)


def main():
    if len(sys.argv) != 2:
        print(
            "Usage:"
        )
        print(
            "python -m scripts.inspect_shadow_session "
            "<session_id>"
        )
        return

    try:
        session_id = uuid.UUID(
            sys.argv[1]
        )

    except ValueError:
        print(
            "Invalid session UUID."
        )
        return

    db = SessionLocal()

    try:
        session = db.get(
            DecisionSession,
            session_id,
        )

        if session is None:
            print(
                "DecisionSession not found."
            )
            return

        shadow = db.scalar(
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

        print()
        print("=" * 80)
        print(
            "SYSTEM SHADOW TECHNICAL INSPECTION"
        )
        print("=" * 80)

        print(
            "session_id:",
            session.id,
        )

        print(
            "session_status:",
            session.status,
        )

        if shadow is None:
            print()
            print(
                "SYSTEM_SHADOW: NOT FOUND"
            )
            return

        print()
        print(
            "shadow_exists: True"
        )

        print(
            "model_version:",
            shadow.model_version,
        )

        print(
            "status:",
            shadow.status,
        )

        print(
            "support_count:",
            shadow.support_count,
        )

        print(
            "strongest_evidence:",
            shadow.strongest_evidence,
        )

        print(
            "average_evidence:",
            shadow.average_evidence,
        )

        print(
            "abstain_reason:",
            shadow.abstain_reason,
        )

        print(
            "has_hidden_estimate:",
            (
                shadow.total_novorapid_units
                is not None
            ),
        )

        print(
            "revealed:",
            (
                shadow.revealed_at
                is not None
            ),
        )

        evidence = (
            shadow.evidence_snapshot
            or {}
        )

        print()
        print(
            "historical_dose_count:",
            evidence.get(
                "historical_dose_count"
            ),
        )

        print(
            "candidate_count:",
            evidence.get(
                "candidate_count"
            ),
        )

        print(
            "top_match_count:",
            evidence.get(
                "top_match_count"
            ),
        )

        print()
        print(
            "Hidden estimate value is "
            "intentionally NOT displayed."
        )

        print("=" * 80)

    finally:
        db.close()


if __name__ == "__main__":
    main()