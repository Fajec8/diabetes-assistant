from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models.meal import Meal
from app.models.meal_assessment import MealAssessment


INPUT_JSON = Path(
    "data/private/clarity/assessment_dry_run.json"
)

PDF_DRY_RUN_JSON = Path(
    "data/private/clarity/pdf_dry_run.json"
)

CLARITY_IMPORT_NOTE = (
    "Imported from Dexcom Clarity CSV"
)

ASSESSMENT_SOURCE = (
    "DEXCOM_CLARITY_PDF"
)

ACCEPTED_CONFIDENCE = {
    "HIGH",
    "MEDIUM",
}


@dataclass
class PendingAssessment:
    meal_id: uuid.UUID

    reported_prebolus_minutes: float | None = None
    prebolus_explicit_none: bool = False

    insulin_feedback: str | None = None
    reported_meal_type: str | None = None

    raw_notes: list[str] = field(
        default_factory=list
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import validated Dexcom Clarity PDF "
            "meal assessments into PostgreSQL."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_JSON,
    )

    parser.add_argument(
        "--commit",
        action="store_true",
        help=(
            "Actually write changes to the database. "
            "Without this flag the script performs a dry run."
        ),
    )

    return parser.parse_args()


def load_json(
    path: Path,
) -> dict:
    if not path.exists():
        raise SystemExit(
            "Required JSON does not exist:\n"
            f"{path.resolve()}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def values_equal(
    existing: MealAssessment,
    pending: PendingAssessment,
    raw_notes: str | None,
) -> bool:
    if (
        existing.reported_prebolus_minutes
        != pending.reported_prebolus_minutes
    ):
        return False

    if (
        existing.prebolus_explicit_none
        != pending.prebolus_explicit_none
    ):
        return False

    if (
        existing.insulin_feedback
        != pending.insulin_feedback
    ):
        return False

    if (
        existing.reported_meal_type
        != pending.reported_meal_type
    ):
        return False

    if (
        existing.timing_note
        is not None
    ):
        return False

    if (
        existing.source
        != ASSESSMENT_SOURCE
    ):
        return False

    existing_raw = (
        existing.raw_notes
        or ""
    ).strip()

    pending_raw = (
        raw_notes
        or ""
    ).strip()

    return (
        existing_raw
        == pending_raw
    )


def build_pending_assessments(
    data: dict,
) -> tuple[
    dict[
        uuid.UUID,
        PendingAssessment,
    ],
    int,
    int,
]:
    pending: dict[
        uuid.UUID,
        PendingAssessment,
    ] = {}

    skipped_prebolus = 0
    skipped_feedback = 0

    for item in data.get(
        "prebolus_matches",
        [],
    ):
        confidence = item.get(
            "confidence"
        )

        meal_id_raw = item.get(
            "meal_id"
        )

        if (
            confidence
            not in ACCEPTED_CONFIDENCE
            or not meal_id_raw
        ):
            skipped_prebolus += 1
            continue

        meal_id = uuid.UUID(
            meal_id_raw
        )

        assessment = pending.setdefault(
            meal_id,
            PendingAssessment(
                meal_id=meal_id
            ),
        )

        explicit_none = bool(
            item.get(
                "prebolus_explicit_none",
                False,
            )
        )

        prebolus_minutes = (
            item.get(
                "prebolus_minutes"
            )
        )

        if explicit_none:
            prebolus_minutes = None

        if (
            assessment.reported_prebolus_minutes
            is not None
            or assessment.prebolus_explicit_none
        ):
            existing_value = (
                assessment.reported_prebolus_minutes,
                assessment.prebolus_explicit_none,
            )

            new_value = (
                prebolus_minutes,
                explicit_none,
            )

            if (
                existing_value
                != new_value
            ):
                raise SystemExit(
                    "REFUSING IMPORT: "
                    "conflicting prebolus values "
                    f"for meal {meal_id}."
                )

        assessment.reported_prebolus_minutes = (
            prebolus_minutes
        )

        assessment.prebolus_explicit_none = (
            explicit_none
        )

        note_text = (
            item.get(
                "note_text"
            )
            or ""
        ).strip()

        assessment.raw_notes.append(
            (
                f"PREBOLUS "
                f"[{confidence}]: "
                f"{note_text}"
            )
        )

    for item in data.get(
        "feedback_matches",
        [],
    ):
        confidence = item.get(
            "confidence"
        )

        meal_id_raw = item.get(
            "meal_id"
        )

        if (
            confidence
            not in ACCEPTED_CONFIDENCE
            or not meal_id_raw
        ):
            skipped_feedback += 1
            continue

        meal_id = uuid.UUID(
            meal_id_raw
        )

        assessment = pending.setdefault(
            meal_id,
            PendingAssessment(
                meal_id=meal_id
            ),
        )

        feedback = item.get(
            "insulin_feedback"
        )

        meal_type = item.get(
            "reported_meal_type"
        )

        if (
            assessment.insulin_feedback
            is not None
        ):
            existing_value = (
                assessment.insulin_feedback,
                assessment.reported_meal_type,
            )

            new_value = (
                feedback,
                meal_type,
            )

            if (
                existing_value
                != new_value
            ):
                raise SystemExit(
                    "REFUSING IMPORT: "
                    "conflicting feedback values "
                    f"for meal {meal_id}."
                )

        assessment.insulin_feedback = (
            feedback
        )

        assessment.reported_meal_type = (
            meal_type
        )

        note_text = (
            item.get(
                "note_text"
            )
            or ""
        ).strip()

        assessment.raw_notes.append(
            (
                f"FEEDBACK "
                f"[{confidence}]: "
                f"{note_text}"
            )
        )

    return (
        pending,
        skipped_prebolus,
        skipped_feedback,
    )


def main() -> None:
    args = parse_args()

    data = load_json(
        args.input
    )

    pdf_data = load_json(
        PDF_DRY_RUN_JSON
    )

    expected_user_id = uuid.UUID(
        pdf_data["user_id"]
    )

    (
        pending,
        skipped_prebolus,
        skipped_feedback,
    ) = build_pending_assessments(
        data
    )

    if not pending:
        raise SystemExit(
            "REFUSING IMPORT: "
            "no accepted assessments found."
        )

    meal_ids = list(
        pending.keys()
    )

    print()
    print("=" * 72)
    print(
        "DEXCOM CLARITY MEAL ASSESSMENT IMPORT"
    )
    print("=" * 72)

    print(
        f"Mode:                   "
        f"{'COMMIT' if args.commit else 'DRY RUN'}"
    )

    print(
        f"Input JSON:             "
        f"{args.input.resolve()}"
    )

    print(
        f"User ID:                "
        f"{expected_user_id}"
    )

    print()
    print("SOURCE DATA")
    print("-" * 72)

    print(
        f"Accepted meals:         "
        f"{len(pending):,}"
    )

    print(
        f"Skipped prebolus:       "
        f"{skipped_prebolus:,}"
    )

    print(
        f"Skipped feedback:       "
        f"{skipped_feedback:,}"
    )

    db = SessionLocal()

    try:
        meals = (
            db.execute(
                select(
                    Meal
                ).where(
                    Meal.id.in_(
                        meal_ids
                    )
                )
            )
            .scalars()
            .all()
        )

        meals_by_id = {
            meal.id: meal
            for meal in meals
        }

        existing_rows = (
            db.execute(
                select(
                    MealAssessment
                ).where(
                    MealAssessment.meal_id.in_(
                        meal_ids
                    )
                )
            )
            .scalars()
            .all()
        )

        existing_by_meal = {
            row.meal_id: row
            for row in existing_rows
        }

        would_insert = 0
        already_same = 0

        skipped_wrong_user = 0
        skipped_wrong_source = 0
        missing_meal = 0

        existing_conflicts = 0

        prebolus_count = 0
        feedback_count = 0
        both_count = 0

        examples = []

        for (
            meal_id,
            assessment,
        ) in sorted(
            pending.items(),
            key=lambda item: (
                str(
                    item[0]
                )
            ),
        ):
            meal = meals_by_id.get(
                meal_id
            )

            if meal is None:
                missing_meal += 1
                continue

            if (
                meal.user_id
                != expected_user_id
            ):
                skipped_wrong_user += 1
                continue

            if (
                meal.note
                != CLARITY_IMPORT_NOTE
            ):
                skipped_wrong_source += 1
                continue

            has_prebolus = (
                assessment.reported_prebolus_minutes
                is not None
                or assessment.prebolus_explicit_none
            )

            has_feedback = (
                assessment.insulin_feedback
                is not None
            )

            if has_prebolus:
                prebolus_count += 1

            if has_feedback:
                feedback_count += 1

            if (
                has_prebolus
                and has_feedback
            ):
                both_count += 1

            raw_notes = (
                "\n".join(
                    assessment.raw_notes
                )
                if assessment.raw_notes
                else None
            )

            existing = (
                existing_by_meal.get(
                    meal_id
                )
            )

            if existing is not None:
                if values_equal(
                    existing=existing,
                    pending=assessment,
                    raw_notes=raw_notes,
                ):
                    already_same += 1
                    continue

                existing_conflicts += 1
                continue

            would_insert += 1

            if len(examples) < 12:
                examples.append(
                    {
                        "meal_id": meal_id,
                        "eaten_at": meal.eaten_at,
                        "carbs": (
                            meal.carbohydrates_g
                        ),
                        "description": (
                            meal.description
                        ),
                        "prebolus": (
                            assessment
                            .reported_prebolus_minutes
                        ),
                        "prebolus_none": (
                            assessment
                            .prebolus_explicit_none
                        ),
                        "feedback": (
                            assessment
                            .insulin_feedback
                        ),
                        "meal_type": (
                            assessment
                            .reported_meal_type
                        ),
                        "raw_notes": (
                            raw_notes
                        ),
                    }
                )

            db.add(
                MealAssessment(
                    meal_id=meal_id,

                    reported_prebolus_minutes=(
                        assessment
                        .reported_prebolus_minutes
                    ),

                    prebolus_explicit_none=(
                        assessment
                        .prebolus_explicit_none
                    ),

                    insulin_feedback=(
                        assessment
                        .insulin_feedback
                    ),

                    reported_meal_type=(
                        assessment
                        .reported_meal_type
                    ),

                    timing_note=None,

                    raw_notes=(
                        raw_notes
                    ),

                    source=(
                        ASSESSMENT_SOURCE
                    ),
                )
            )

        print()
        print("RESULTS")
        print("-" * 72)

        print(
            f"Would insert:           "
            f"{would_insert:,}"
        )

        print(
            f"Already same:           "
            f"{already_same:,}"
        )

        print(
            f"Existing conflicts:     "
            f"{existing_conflicts:,}"
        )

        print(
            f"Missing meal:           "
            f"{missing_meal:,}"
        )

        print(
            f"Skipped wrong user:     "
            f"{skipped_wrong_user:,}"
        )

        print(
            f"Skipped wrong source:   "
            f"{skipped_wrong_source:,}"
        )

        print()
        print("ASSESSMENT CONTENT")
        print("-" * 72)

        print(
            f"With prebolus:          "
            f"{prebolus_count:,}"
        )

        print(
            f"With feedback:          "
            f"{feedback_count:,}"
        )

        print(
            f"With both:              "
            f"{both_count:,}"
        )

        print()
        print("EXAMPLES")
        print("-" * 72)

        if not examples:
            print("(none)")

        for example in examples:
            print(
                f"{example['eaten_at']} | "
                f"{example['carbs']} g | "
                f"{example['description']}"
            )

            print(
                "    prebolus: ",
                example[
                    "prebolus"
                ],
                "| none:",
                example[
                    "prebolus_none"
                ],
            )

            print(
                "    feedback: ",
                example[
                    "feedback"
                ],
                "| meal type:",
                example[
                    "meal_type"
                ],
            )

            print(
                "    notes: ",
                example[
                    "raw_notes"
                ],
            )

        print()

        if existing_conflicts:
            db.rollback()

            print(
                "REFUSING COMMIT: "
                "existing conflicting assessments found."
            )

            print(
                "DATABASE CHANGED: NO"
            )

        elif args.commit:
            db.commit()

            print(
                f"INSERTED ASSESSMENTS: "
                f"{would_insert:,}"
            )

            print(
                "DATABASE CHANGED: YES"
            )

        else:
            db.rollback()

            print(
                "DATABASE CHANGED: NO"
            )

        print("=" * 72)
        print()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()