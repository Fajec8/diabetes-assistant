from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models.meal import Meal
from app.models.meal_assessment import MealAssessment


INPUT_JSON = Path(
    "data/private/clarity/pdf_dry_run.json"
)

OUTPUT_JSON = Path(
    "data/private/clarity/assessment_dry_run.json"
)

PRAGUE = ZoneInfo(
    "Europe/Prague"
)

CLARITY_IMPORT_NOTE = (
    "Imported from Dexcom Clarity CSV"
)

PREBOLUS_WINDOW_MINUTES = 45

# Feedback "inzulínu bylo málo / akorát / moc"
# nemůže rozumně hodnotit jídlo právě snědené.
FEEDBACK_MIN_LAG_MINUTES = 60

# Běžný feedback ve stejný den.
FEEDBACK_MAX_LAG_MINUTES = 10 * 60

# Večeře může být vyhodnocena až následující ráno.
PREVIOUS_DINNER_MAX_LAG_MINUTES = 18 * 60

# Pokud existuje více kandidátů, považujeme nejlepší
# za MEDIUM pouze tehdy, když je proti druhému
# časově výrazně lepší.
FEEDBACK_MEDIUM_MARGIN_MINUTES = 90


@dataclass(frozen=True)
class MealRef:
    meal_id: uuid.UUID
    local_datetime: datetime
    carbohydrates_g: float
    description: str | None


@dataclass(frozen=True)
class AssessmentMatch:
    kind: str

    note_datetime: str
    note_text: str

    meal_id: str | None
    meal_datetime: str | None
    meal_description: str | None
    meal_carbohydrates_g: float | None

    confidence: str

    difference_minutes: float | None
    candidate_count: int = 0

    prebolus_minutes: float | None = None
    prebolus_explicit_none: bool = False

    insulin_feedback: str | None = None
    reported_meal_type: str | None = None


def load_json() -> dict:
    if not INPUT_JSON.exists():
        raise SystemExit(
            "Input JSON does not exist:\n"
            f"{INPUT_JSON.resolve()}"
        )

    return json.loads(
        INPUT_JSON.read_text(
            encoding="utf-8"
        )
    )


def parse_datetime(
    value: str,
) -> datetime:
    parsed = datetime.fromisoformat(
        value
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=PRAGUE
        )

    return parsed.astimezone(
        PRAGUE
    )


def load_all_clarity_meals(
    data: dict,
) -> list[MealRef]:
    """
    Load ALL meals created by our Clarity CSV importer.

    Important:
    Feedback must not be restricted only to the 2,254 meals
    that received a PDF description. A correct target may be
    one of the remaining Clarity meals without PDF enrichment.
    """
    user_id = uuid.UUID(
        data["user_id"]
    )

    db = SessionLocal()

    try:
        rows = db.execute(
            select(
                Meal.id,
                Meal.eaten_at,
                Meal.carbohydrates_g,
                Meal.description,
            ).where(
                Meal.user_id
                == user_id,
                Meal.note
                == CLARITY_IMPORT_NOTE,
            )
        ).all()

        result = []

        for (
            meal_id,
            eaten_at,
            carbs,
            description,
        ) in rows:
            if eaten_at.tzinfo is None:
                local_datetime = (
                    eaten_at.replace(
                        tzinfo=PRAGUE
                    )
                )

            else:
                local_datetime = (
                    eaten_at.astimezone(
                        PRAGUE
                    )
                )

            result.append(
                MealRef(
                    meal_id=meal_id,
                    local_datetime=(
                        local_datetime
                    ),
                    carbohydrates_g=float(
                        carbs
                    ),
                    description=description,
                )
            )

        return sorted(
            result,
            key=lambda item: (
                item.local_datetime
            ),
        )

    finally:
        db.close()


def group_meals_by_date(
    meals: list[MealRef],
) -> dict[
    date,
    list[MealRef],
]:
    result = defaultdict(
        list
    )

    for meal in meals:
        result[
            meal.local_datetime.date()
        ].append(
            meal
        )

    return result


def meal_type_time_window(
    meal_type: str,
) -> tuple[
    time,
    time,
] | None:
    if meal_type == "BREAKFAST":
        return (
            time(4, 0),
            time(11, 30),
        )

    if meal_type == "LUNCH":
        return (
            time(10, 30),
            time(16, 30),
        )

    if meal_type == "DINNER":
        return (
            time(16, 0),
            time(23, 59, 59),
        )

    return None


def make_unmatched(
    *,
    kind: str,
    event: dict,
    prebolus_minutes: float | None = None,
    explicit_none: bool = False,
    feedback: str | None = None,
    meal_type: str | None = None,
    candidate_count: int = 0,
) -> AssessmentMatch:
    note_dt = parse_datetime(
        event["local_datetime"]
    )

    return AssessmentMatch(
        kind=kind,

        note_datetime=(
            note_dt.isoformat()
        ),

        note_text=(
            event["detail"]
        ),

        meal_id=None,
        meal_datetime=None,
        meal_description=None,
        meal_carbohydrates_g=None,

        confidence="UNMATCHED",

        difference_minutes=None,
        candidate_count=(
            candidate_count
        ),

        prebolus_minutes=(
            prebolus_minutes
        ),

        prebolus_explicit_none=(
            explicit_none
        ),

        insulin_feedback=(
            feedback
        ),

        reported_meal_type=(
            meal_type
        ),
    )


def match_prebolus(
    event: dict,
    date_meals: list[MealRef],
) -> AssessmentMatch:
    note_dt = parse_datetime(
        event["local_datetime"]
    )

    prebolus = event.get(
        "prebolus_minutes"
    )

    explicit_none = bool(
        event.get(
            "prebolus_explicit_none",
            False,
        )
    )

    candidates = []

    for meal in date_meals:
        difference = abs(
            (
                meal.local_datetime
                - note_dt
            ).total_seconds()
        ) / 60.0

        if (
            difference
            <= PREBOLUS_WINDOW_MINUTES
        ):
            candidates.append(
                (
                    difference,
                    meal,
                )
            )

    candidates.sort(
        key=lambda item: (
            item[0]
        )
    )

    if not candidates:
        return make_unmatched(
            kind="PREBOLUS",
            event=event,

            prebolus_minutes=(
                None
                if explicit_none
                else prebolus
            ),

            explicit_none=(
                explicit_none
            ),
        )

    best_score, best_meal = (
        candidates[0]
    )

    if len(candidates) == 1:
        confidence = "HIGH"

    else:
        second_score = (
            candidates[1][0]
        )

        margin = (
            second_score
            - best_score
        )

        if margin >= 10:
            confidence = "MEDIUM"

        else:
            confidence = (
                "AMBIGUOUS"
            )

    return AssessmentMatch(
        kind="PREBOLUS",

        note_datetime=(
            note_dt.isoformat()
        ),

        note_text=(
            event["detail"]
        ),

        meal_id=str(
            best_meal.meal_id
        ),

        meal_datetime=(
            best_meal
            .local_datetime
            .isoformat()
        ),

        meal_description=(
            best_meal.description
        ),

        meal_carbohydrates_g=(
            best_meal
            .carbohydrates_g
        ),

        confidence=confidence,

        difference_minutes=round(
            best_score,
            2,
        ),

        candidate_count=len(
            candidates
        ),

        prebolus_minutes=(
            None
            if explicit_none
            else prebolus
        ),

        prebolus_explicit_none=(
            explicit_none
        ),
    )


def feedback_candidate_dates(
    note_dt: datetime,
    meal_type: str,
) -> list[date]:
    result = [
        note_dt.date()
    ]

    # A note about dinner entered during the next morning
    # very plausibly refers to yesterday's dinner.
    if (
        meal_type == "DINNER"
        and note_dt.time()
        <= time(12, 0)
    ):
        result.append(
            (
                note_dt
                - timedelta(days=1)
            ).date()
        )

    return result


def feedback_max_lag(
    note_dt: datetime,
    meal: MealRef,
    meal_type: str,
) -> int:
    if (
        meal_type == "DINNER"
        and meal.local_datetime.date()
        != note_dt.date()
    ):
        return (
            PREVIOUS_DINNER_MAX_LAG_MINUTES
        )

    return (
        FEEDBACK_MAX_LAG_MINUTES
    )


def match_feedback(
    event: dict,
    by_date: dict[
        date,
        list[MealRef],
    ],
) -> AssessmentMatch:
    note_dt = parse_datetime(
        event["local_datetime"]
    )

    feedback = event.get(
        "feedback_result"
    )

    meal_type = event.get(
        "feedback_meal"
    )

    time_window = (
        meal_type_time_window(
            meal_type
        )
    )

    if time_window is None:
        return make_unmatched(
            kind="FEEDBACK",
            event=event,
            feedback=feedback,
            meal_type=meal_type,
        )

    start_time, end_time = (
        time_window
    )

    candidate_dates = (
        feedback_candidate_dates(
            note_dt=note_dt,
            meal_type=meal_type,
        )
    )

    candidates = []

    for candidate_date in (
        candidate_dates
    ):
        for meal in by_date.get(
            candidate_date,
            [],
        ):
            meal_time = (
                meal
                .local_datetime
                .time()
            )

            if not (
                start_time
                <= meal_time
                <= end_time
            ):
                continue

            lag_minutes = (
                note_dt
                - meal.local_datetime
            ).total_seconds() / 60.0

            # A feedback note saying insulin "was" too much /
            # too little / correct should not be assigned to
            # a meal that happened only moments earlier.
            if (
                lag_minutes
                < FEEDBACK_MIN_LAG_MINUTES
            ):
                continue

            max_lag = (
                feedback_max_lag(
                    note_dt=note_dt,
                    meal=meal,
                    meal_type=meal_type,
                )
            )

            if lag_minutes > max_lag:
                continue

            candidates.append(
                (
                    lag_minutes,
                    meal,
                )
            )

    candidates.sort(
        key=lambda item: (
            item[0]
        )
    )

    if not candidates:
        return make_unmatched(
            kind="FEEDBACK",
            event=event,
            feedback=feedback,
            meal_type=meal_type,
        )

    best_score, best_meal = (
        candidates[0]
    )

    if len(candidates) == 1:
        confidence = "HIGH"

    else:
        second_score = (
            candidates[1][0]
        )

        margin = (
            second_score
            - best_score
        )

        if (
            margin
            >= FEEDBACK_MEDIUM_MARGIN_MINUTES
        ):
            confidence = "MEDIUM"

        else:
            confidence = (
                "AMBIGUOUS"
            )

    return AssessmentMatch(
        kind="FEEDBACK",

        note_datetime=(
            note_dt.isoformat()
        ),

        note_text=(
            event["detail"]
        ),

        meal_id=str(
            best_meal.meal_id
        ),

        meal_datetime=(
            best_meal
            .local_datetime
            .isoformat()
        ),

        meal_description=(
            best_meal.description
        ),

        meal_carbohydrates_g=(
            best_meal
            .carbohydrates_g
        ),

        confidence=confidence,

        difference_minutes=round(
            best_score,
            2,
        ),

        candidate_count=len(
            candidates
        ),

        insulin_feedback=(
            feedback
        ),

        reported_meal_type=(
            meal_type
        ),
    )


def print_examples(
    title: str,
    matches: list[
        AssessmentMatch
    ],
    limit: int = 8,
) -> None:
    print()
    print(title)
    print("-" * 72)

    if not matches:
        print("(none)")
        return

    for match in matches[
        :limit
    ]:
        print(
            f"{match.note_datetime} | "
            f"{match.confidence:<9} | "
            f"candidates="
            f"{match.candidate_count} | "
            f"{match.note_text}"
        )

        print(
            "    -> "
            f"{match.meal_datetime} | "
            f"{match.meal_carbohydrates_g} g | "
            f"{match.meal_description}"
        )


def main() -> None:
    data = load_json()

    meals = (
        load_all_clarity_meals(
            data
        )
    )

    by_date = (
        group_meals_by_date(
            meals
        )
    )

    events = data.get(
        "events",
        [],
    )

    prebolus_events = []

    feedback_events = []

    for event in events:
        if (
            event.get(
                "event_type"
            )
            != "NOTE"
        ):
            continue

        if (
            event.get(
                "prebolus_minutes"
            )
            is not None
            or event.get(
                "prebolus_explicit_none"
            )
        ):
            prebolus_events.append(
                event
            )

        if (
            event.get(
                "feedback_result"
            )
            is not None
        ):
            feedback_events.append(
                event
            )

    prebolus_matches = []

    for event in (
        prebolus_events
    ):
        note_dt = parse_datetime(
            event["local_datetime"]
        )

        result = match_prebolus(
            event=event,

            date_meals=by_date.get(
                note_dt.date(),
                [],
            ),
        )

        prebolus_matches.append(
            result
        )

    feedback_matches = []

    for event in (
        feedback_events
    ):
        result = match_feedback(
            event=event,
            by_date=by_date,
        )

        feedback_matches.append(
            result
        )

    prebolus_confidence = Counter(
        item.confidence
        for item in (
            prebolus_matches
        )
    )

    feedback_confidence = Counter(
        item.confidence
        for item in (
            feedback_matches
        )
    )

    feedback_values = Counter(
        item.insulin_feedback
        for item in (
            feedback_matches
        )
    )

    candidate_meal_ids = {
        item.meal_id
        for item in (
            prebolus_matches
            + feedback_matches
        )
        if (
            item.meal_id
            is not None
            and item.confidence
            in {
                "HIGH",
                "MEDIUM",
            }
        )
    }

    high_meal_ids = {
        item.meal_id
        for item in (
            prebolus_matches
            + feedback_matches
        )
        if (
            item.meal_id
            is not None
            and item.confidence
            == "HIGH"
        )
    }

    db = SessionLocal()

    try:
        existing_assessments = (
            db.execute(
                select(
                    MealAssessment.id
                )
            )
            .scalars()
            .all()
        )

    finally:
        db.close()

    output = {
        "generated_at": (
            datetime.now(
                tz=PRAGUE
            ).isoformat()
        ),

        "input_json": str(
            INPUT_JSON.resolve()
        ),

        "statistics": {
            "clarity_db_meals": len(
                meals
            ),

            "prebolus_events": len(
                prebolus_events
            ),

            "feedback_events": len(
                feedback_events
            ),

            "prebolus_confidence": dict(
                prebolus_confidence
            ),

            "feedback_confidence": dict(
                feedback_confidence
            ),

            "feedback_values": dict(
                feedback_values
            ),

            "high_candidate_meals": len(
                high_meal_ids
            ),

            "high_medium_candidate_meals": len(
                candidate_meal_ids
            ),

            "existing_assessments": len(
                existing_assessments
            ),
        },

        "prebolus_matches": [
            asdict(
                item
            )
            for item in (
                prebolus_matches
            )
        ],

        "feedback_matches": [
            asdict(
                item
            )
            for item in (
                feedback_matches
            )
        ],
    }

    OUTPUT_JSON.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_JSON.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print(
        "DEXCOM CLARITY MEAL ASSESSMENT DRY RUN V2"
    )
    print("=" * 72)

    print(
        f"Clarity DB meals:       "
        f"{len(meals):,}"
    )

    print(
        f"Existing assessments:   "
        f"{len(existing_assessments):,}"
    )

    print()

    print("PREBOLUS")
    print("-" * 72)

    print(
        f"Events:                 "
        f"{len(prebolus_events):,}"
    )

    print(
        f"HIGH:                   "
        f"{prebolus_confidence['HIGH']:,}"
    )

    print(
        f"MEDIUM:                 "
        f"{prebolus_confidence['MEDIUM']:,}"
    )

    print(
        f"AMBIGUOUS:              "
        f"{prebolus_confidence['AMBIGUOUS']:,}"
    )

    print(
        f"UNMATCHED:              "
        f"{prebolus_confidence['UNMATCHED']:,}"
    )

    print()

    print("FEEDBACK")
    print("-" * 72)

    print(
        f"Events:                 "
        f"{len(feedback_events):,}"
    )

    print(
        f"HIGH:                   "
        f"{feedback_confidence['HIGH']:,}"
    )

    print(
        f"MEDIUM:                 "
        f"{feedback_confidence['MEDIUM']:,}"
    )

    print(
        f"AMBIGUOUS:              "
        f"{feedback_confidence['AMBIGUOUS']:,}"
    )

    print(
        f"UNMATCHED:              "
        f"{feedback_confidence['UNMATCHED']:,}"
    )

    print()

    print(
        f"TOO_LITTLE:             "
        f"{feedback_values['TOO_LITTLE']:,}"
    )

    print(
        f"OK:                     "
        f"{feedback_values['OK']:,}"
    )

    print(
        f"TOO_MUCH:               "
        f"{feedback_values['TOO_MUCH']:,}"
    )

    print()

    print(
        f"HIGH candidate meals:   "
        f"{len(high_meal_ids):,}"
    )

    print(
        f"HIGH+MEDIUM meals:      "
        f"{len(candidate_meal_ids):,}"
    )

    print_examples(
        "PREBOLUS HIGH EXAMPLES",
        [
            item
            for item in prebolus_matches
            if item.confidence
            == "HIGH"
        ],
    )

    print_examples(
        "PREBOLUS UNRESOLVED EXAMPLES",
        [
            item
            for item in prebolus_matches
            if item.confidence
            in {
                "AMBIGUOUS",
                "UNMATCHED",
            }
        ],
    )

    print_examples(
        "FEEDBACK HIGH EXAMPLES",
        [
            item
            for item in feedback_matches
            if item.confidence
            == "HIGH"
        ],
    )

    print_examples(
        "FEEDBACK MEDIUM EXAMPLES",
        [
            item
            for item in feedback_matches
            if item.confidence
            == "MEDIUM"
        ],
    )

    print_examples(
        "FEEDBACK UNRESOLVED EXAMPLES",
        [
            item
            for item in feedback_matches
            if item.confidence
            in {
                "AMBIGUOUS",
                "UNMATCHED",
            }
        ],
    )

    print()
    print(
        "Private JSON saved to:"
    )

    print(
        OUTPUT_JSON.resolve()
    )

    print()
    print(
        "DATABASE CHANGED: NO"
    )

    print("=" * 72)
    print()


if __name__ == "__main__":
    main()