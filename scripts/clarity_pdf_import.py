from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models.meal import Meal


DEFAULT_INPUT = Path(
    "data/private/clarity/pdf_dry_run.json"
)

CLARITY_IMPORT_NOTE = (
    "Imported from Dexcom Clarity CSV"
)

MAX_DESCRIPTION_LENGTH = 255


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import meal descriptions extracted from "
            "Dexcom Clarity Daily PDFs."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
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


def clean_description(
    value: str,
) -> tuple[str, bool]:
    """
    Conservative cleanup only.

    We do NOT try to correct OCR spelling because that could
    silently invent information.

    We only remove obvious formatting artefacts.
    """
    value = value.strip()

    # Some OCR output contains literal "\n".
    value = value.replace(
        "\\n",
        " ",
    )

    # OCR sometimes turns a line break before the next VJ item
    # into a literal "n", for example:
    #
    #   čokoládan1VJ pistacie
    #       ->
    #   čokoláda 1VJ pistacie
    #
    # We only apply this when "n" is directly followed by
    # another numeric VJ item.
    value = re.sub(
        (
            r"(?<=[^\W\d_])"
            r"n"
            r"(?=\d+(?:[.,]\d+)?\s*VJ\b)"
        ),
        " ",
        value,
        flags=re.IGNORECASE,
    )

    # And some contains real line breaks.
    value = value.replace(
        "\r",
        " ",
    )

    value = value.replace(
        "\n",
        " ",
    )

    # Remove leading OCR markers.
    value = re.sub(
        r"^\s*[*•]+\s*",
        "",
        value,
    )

    # Remove obvious trailing OCR symbols.
    value = re.sub(
        r"\s*[=©®]+\s*$",
        "",
        value,
    )

    # Example OCR contamination:
    #
    #   Rýže vařená Stav glukózy - 8
    #
    # This is not part of the food description.
    value = re.sub(
        (
            r"\s+stav\s+gluk[oó]zy"
            r"\s*[-:]\s*"
            r"\d+(?:[.,]\d+)?"
            r"\s*$"
        ),
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    truncated = False

    if len(value) > MAX_DESCRIPTION_LENGTH:
        value = value[
            :MAX_DESCRIPTION_LENGTH
        ].rstrip()

        truncated = True

    return (
        value,
        truncated,
    )


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        raise SystemExit(
            "Input JSON does not exist:\n"
            f"{args.input.resolve()}"
        )

    data = json.loads(
        args.input.read_text(
            encoding="utf-8"
        )
    )

    statistics = data.get(
        "statistics",
        {},
    )

    unmatched = int(
        statistics.get(
            "unmatched_pdf_meals",
            0,
        )
    )

    ambiguous = int(
        statistics.get(
            "ambiguous_pdf_meals",
            0,
        )
    )

    if unmatched != 0:
        raise SystemExit(
            "REFUSING IMPORT: "
            f"dry-run JSON contains {unmatched} "
            "unmatched PDF meal(s)."
        )

    if ambiguous != 0:
        raise SystemExit(
            "REFUSING IMPORT: "
            f"dry-run JSON contains {ambiguous} "
            "ambiguous PDF meal(s)."
        )

    matched_meals = data.get(
        "matched_meals",
        [],
    )

    if not matched_meals:
        raise SystemExit(
            "REFUSING IMPORT: "
            "matched_meals is empty."
        )

    expected_user_id = uuid.UUID(
        data["user_id"]
    )

    db_meal_ids = []

    seen_ids: set[uuid.UUID] = set()

    duplicate_json_ids = 0

    for item in matched_meals:
        meal_id = uuid.UUID(
            item["db_meal_id"]
        )

        if meal_id in seen_ids:
            duplicate_json_ids += 1
            continue

        seen_ids.add(
            meal_id
        )

        db_meal_ids.append(
            meal_id
        )

    print()
    print("=" * 72)
    print(
        "DEXCOM CLARITY PDF MEAL DESCRIPTION IMPORT"
    )
    print("=" * 72)

    print(
        f"Mode:                 "
        f"{'COMMIT' if args.commit else 'DRY RUN'}"
    )

    print(
        f"Input JSON:           "
        f"{args.input.resolve()}"
    )

    print(
        f"User ID:              "
        f"{expected_user_id}"
    )

    print(
        f"Matched JSON meals:   "
        f"{len(matched_meals):,}"
    )

    print(
        f"Unique DB meal IDs:   "
        f"{len(db_meal_ids):,}"
    )

    print(
        f"Duplicate JSON IDs:   "
        f"{duplicate_json_ids:,}"
    )

    db = SessionLocal()

    try:
        meals = db.execute(
            select(
                Meal
            ).where(
                Meal.id.in_(
                    db_meal_ids
                )
            )
        ).scalars().all()

        meals_by_id = {
            meal.id: meal
            for meal in meals
        }

        would_update = 0
        already_same = 0
        skipped_nonempty = 0
        skipped_wrong_user = 0
        skipped_wrong_source = 0
        skipped_empty = 0
        missing_db = 0
        truncated = 0

        examples = []

        for item in matched_meals:
            meal_id = uuid.UUID(
                item["db_meal_id"]
            )

            meal = meals_by_id.get(
                meal_id
            )

            if meal is None:
                missing_db += 1
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

            raw_description = (
                item.get(
                    "description"
                )
                or ""
            )

            (
                description,
                was_truncated,
            ) = clean_description(
                raw_description
            )

            if was_truncated:
                truncated += 1

            if not description:
                skipped_empty += 1
                continue

            current_description = (
                meal.description
                or ""
            ).strip()

            if (
                current_description
                == description
            ):
                already_same += 1
                continue

            # Do not silently overwrite anything that was
            # already entered by the application/user.
            if current_description:
                skipped_nonempty += 1
                continue

            would_update += 1

            if len(examples) < 10:
                examples.append(
                    (
                        meal.eaten_at,
                        meal.carbohydrates_g,
                        description,
                    )
                )

            meal.description = (
                description
            )

        print()
        print("RESULTS")
        print("-" * 72)

        print(
            f"Would update:         "
            f"{would_update:,}"
        )

        print(
            f"Already same:         "
            f"{already_same:,}"
        )

        print(
            f"Skipped non-empty:    "
            f"{skipped_nonempty:,}"
        )

        print(
            f"Skipped wrong user:   "
            f"{skipped_wrong_user:,}"
        )

        print(
            f"Skipped wrong source: "
            f"{skipped_wrong_source:,}"
        )

        print(
            f"Skipped empty:        "
            f"{skipped_empty:,}"
        )

        print(
            f"Missing DB row:       "
            f"{missing_db:,}"
        )

        print(
            f"Descriptions cut at "
            f"{MAX_DESCRIPTION_LENGTH}: "
            f"{truncated:,}"
        )

        print()
        print("EXAMPLES")
        print("-" * 72)

        if not examples:
            print("(none)")

        else:
            for (
                eaten_at,
                carbs,
                description,
            ) in examples:
                print(
                    f"{eaten_at} | "
                    f"{carbs} g | "
                    f"{description}"
                )

        print()

        if args.commit:
            db.commit()

            print(
                f"UPDATED DESCRIPTIONS: "
                f"{would_update:,}"
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