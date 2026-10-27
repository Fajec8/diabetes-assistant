from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


INPUT_JSON = Path(
    "data/private/clarity/assessment_dry_run.json"
)

ACCEPTED_CONFIDENCE = {
    "HIGH",
    "MEDIUM",
}


def main() -> None:
    if not INPUT_JSON.exists():
        raise SystemExit(
            f"Missing file: {INPUT_JSON.resolve()}"
        )

    data = json.loads(
        INPUT_JSON.read_text(
            encoding="utf-8"
        )
    )

    prebolus = data.get(
        "prebolus_matches",
        [],
    )

    feedback = data.get(
        "feedback_matches",
        [],
    )

    accepted_prebolus = [
        item
        for item in prebolus
        if (
            item.get("meal_id")
            and item.get("confidence")
            in ACCEPTED_CONFIDENCE
        )
    ]

    accepted_feedback = [
        item
        for item in feedback
        if (
            item.get("meal_id")
            and item.get("confidence")
            in ACCEPTED_CONFIDENCE
        )
    ]

    by_meal = defaultdict(
        lambda: {
            "prebolus": [],
            "feedback": [],
        }
    )

    for item in accepted_prebolus:
        by_meal[
            item["meal_id"]
        ][
            "prebolus"
        ].append(
            item
        )

    for item in accepted_feedback:
        by_meal[
            item["meal_id"]
        ][
            "feedback"
        ].append(
            item
        )

    both_types = 0

    duplicate_same_prebolus = 0
    duplicate_same_feedback = 0

    prebolus_conflicts = []
    feedback_conflicts = []

    for meal_id, group in by_meal.items():
        pre_items = group[
            "prebolus"
        ]

        feedback_items = group[
            "feedback"
        ]

        if (
            pre_items
            and feedback_items
        ):
            both_types += 1

        if len(pre_items) > 1:
            values = {
                (
                    item.get(
                        "prebolus_minutes"
                    ),
                    bool(
                        item.get(
                            "prebolus_explicit_none"
                        )
                    ),
                )
                for item in pre_items
            }

            if len(values) == 1:
                duplicate_same_prebolus += (
                    len(pre_items) - 1
                )

            else:
                prebolus_conflicts.append(
                    (
                        meal_id,
                        pre_items,
                    )
                )

        if len(feedback_items) > 1:
            values = {
                (
                    item.get(
                        "insulin_feedback"
                    ),
                    item.get(
                        "reported_meal_type"
                    ),
                )
                for item in feedback_items
            }

            if len(values) == 1:
                duplicate_same_feedback += (
                    len(feedback_items) - 1
                )

            else:
                feedback_conflicts.append(
                    (
                        meal_id,
                        feedback_items,
                    )
                )

    unresolved_prebolus = [
        item
        for item in prebolus
        if item.get(
            "confidence"
        )
        in {
            "AMBIGUOUS",
            "UNMATCHED",
        }
    ]

    unresolved_feedback = [
        item
        for item in feedback
        if item.get(
            "confidence"
        )
        in {
            "AMBIGUOUS",
            "UNMATCHED",
        }
    ]

    medium_feedback = [
        item
        for item in feedback
        if item.get(
            "confidence"
        )
        == "MEDIUM"
    ]

    print()
    print("=" * 72)
    print(
        "DEXCOM CLARITY ASSESSMENT AUDIT"
    )
    print("=" * 72)

    print(
        f"Accepted prebolus:       "
        f"{len(accepted_prebolus):,}"
    )

    print(
        f"Accepted feedback:       "
        f"{len(accepted_feedback):,}"
    )

    print(
        f"Unique meals:            "
        f"{len(by_meal):,}"
    )

    print(
        f"Meals with both types:   "
        f"{both_types:,}"
    )

    print()

    print("DUPLICATES / CONFLICTS")
    print("-" * 72)

    print(
        f"Duplicate same prebolus: "
        f"{duplicate_same_prebolus:,}"
    )

    print(
        f"Duplicate same feedback: "
        f"{duplicate_same_feedback:,}"
    )

    print(
        f"Prebolus conflicts:      "
        f"{len(prebolus_conflicts):,}"
    )

    print(
        f"Feedback conflicts:      "
        f"{len(feedback_conflicts):,}"
    )

    print()

    print("UNRESOLVED")
    print("-" * 72)

    print(
        f"Prebolus unresolved:     "
        f"{len(unresolved_prebolus):,}"
    )

    print(
        f"Feedback unresolved:     "
        f"{len(unresolved_feedback):,}"
    )

    if prebolus_conflicts:
        print()
        print("PREBOLUS CONFLICTS")
        print("-" * 72)

        for meal_id, items in (
            prebolus_conflicts
        ):
            print(
                f"MEAL {meal_id}"
            )

            for item in items:
                print(
                    "  ",
                    item.get(
                        "note_datetime"
                    ),
                    "|",
                    item.get(
                        "prebolus_minutes"
                    ),
                    "| none:",
                    item.get(
                        "prebolus_explicit_none"
                    ),
                    "|",
                    item.get(
                        "note_text"
                    ),
                )

    if feedback_conflicts:
        print()
        print("FEEDBACK CONFLICTS")
        print("-" * 72)

        for meal_id, items in (
            feedback_conflicts
        ):
            print(
                f"MEAL {meal_id}"
            )

            for item in items:
                print(
                    "  ",
                    item.get(
                        "note_datetime"
                    ),
                    "|",
                    item.get(
                        "insulin_feedback"
                    ),
                    "|",
                    item.get(
                        "reported_meal_type"
                    ),
                    "|",
                    item.get(
                        "note_text"
                    ),
                )

    print()
    print("UNRESOLVED PREBOLUS")
    print("-" * 72)

    for item in unresolved_prebolus:
        print(
            item.get(
                "note_datetime"
            ),
            "|",
            item.get(
                "confidence"
            ),
            "|",
            item.get(
                "note_text"
            ),
        )

    print()
    print("UNRESOLVED FEEDBACK")
    print("-" * 72)

    for item in unresolved_feedback:
        print(
            item.get(
                "note_datetime"
            ),
            "|",
            item.get(
                "confidence"
            ),
            "|",
            item.get(
                "note_text"
            ),
        )

    print()
    print(
        "MEDIUM FEEDBACK EXAMPLES"
    )
    print("-" * 72)

    for item in medium_feedback[:15]:
        print(
            item.get(
                "note_datetime"
            ),
            "|",
            item.get(
                "note_text"
            ),
        )

        print(
            "   ->",
            item.get(
                "meal_datetime"
            ),
            "|",
            item.get(
                "meal_carbohydrates_g"
            ),
            "g |",
            item.get(
                "meal_description"
            ),
        )

    print()
    print(
        "DATABASE CHANGED: NO"
    )
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()