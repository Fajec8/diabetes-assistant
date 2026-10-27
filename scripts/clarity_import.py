from __future__ import annotations

import argparse
import uuid
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, update

from app.database import SessionLocal
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.meal import Meal
from app.models.user import User

from scripts.clarity_dry_run import (
    CSV_DIR,
    ClarityEvent,
    deduplicate_events,
    load_events,
)


PRAGUE = ZoneInfo("Europe/Prague")
UTC = timezone.utc

SOURCE_CGM = "DEXCOM_CLARITY"
SOURCE_INSULIN = "DEXCOM_CLARITY"

DEFAULT_USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

DEFAULT_PAIR_WINDOW_MINUTES = 15
BATCH_SIZE = 5000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import Dexcom Clarity CSV data "
            "into the local Diabetes Assistant database."
        )
    )

    parser.add_argument(
        "--user-id",
        type=uuid.UUID,
        default=DEFAULT_USER_ID,
        help="Target user UUID.",
    )

    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=CSV_DIR,
        help="Directory containing Clarity CSV exports.",
    )

    parser.add_argument(
        "--pair-window-minutes",
        type=int,
        default=DEFAULT_PAIR_WINDOW_MINUTES,
        help=(
            "Maximum absolute distance between Meal and "
            "Rapid insulin for automatic linking."
        ),
    )

    parser.add_argument(
        "--commit",
        action="store_true",
        help=(
            "Actually write changes. "
            "Without this flag the script is dry-run only."
        ),
    )

    return parser.parse_args()


def clarity_to_utc(value: datetime) -> datetime:
    """
    Dexcom timestamps are interpreted as local Europe/Prague time.

    The database receives timezone-aware UTC datetimes.
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC)

    local_value = value.replace(
        tzinfo=PRAGUE
    )

    return local_value.astimezone(UTC)


def normalize_db_datetime(
    value: datetime,
) -> datetime:
    """
    Normalize a datetime loaded from PostgreSQL to UTC so it can
    be compared with imported Dexcom timestamps.
    """
    if value.tzinfo is None:
        return value.replace(
            tzinfo=UTC
        )

    return value.astimezone(UTC)


def normalized_float(
    value: float,
) -> float:
    return round(
        float(value),
        6,
    )


def glucose_key(
    measured_at: datetime,
    value: float,
) -> tuple:
    return (
        normalize_db_datetime(
            measured_at
        ),
        normalized_float(
            value
        ),
    )


def meal_key(
    eaten_at: datetime,
    carbohydrates_g: float,
) -> tuple:
    return (
        normalize_db_datetime(
            eaten_at
        ),
        normalized_float(
            carbohydrates_g
        ),
    )


def insulin_key(
    administered_at: datetime,
    insulin_type: str,
    units: float,
) -> tuple:
    return (
        normalize_db_datetime(
            administered_at
        ),
        insulin_type,
        normalized_float(
            units
        ),
    )


def event_glucose_key(
    event: ClarityEvent,
) -> tuple:
    assert event.glucose is not None

    return glucose_key(
        clarity_to_utc(
            event.timestamp
        ),
        event.glucose,
    )


def event_meal_key(
    event: ClarityEvent,
) -> tuple:
    assert event.carbohydrates_g is not None

    return meal_key(
        clarity_to_utc(
            event.timestamp
        ),
        event.carbohydrates_g,
    )


def event_insulin_key(
    event: ClarityEvent,
    insulin_type: str,
) -> tuple:
    assert event.insulin_units is not None

    return insulin_key(
        clarity_to_utc(
            event.timestamp
        ),
        insulin_type,
        event.insulin_units,
    )


def build_meal_rapid_pairs(
    meals: list[ClarityEvent],
    rapid_insulin: list[ClarityEvent],
    window_minutes: int,
) -> dict[tuple, tuple]:
    """
    Build conservative one-to-one Meal -> Rapid insulin links.

    Only one closest rapid dose within the selected time window
    is linked automatically.

    Historical split doses are intentionally not inferred here.
    They can later be enriched using Daily PDF reports.
    """
    if not meals or not rapid_insulin:
        return {}

    rapid_sorted = sorted(
        rapid_insulin,
        key=lambda event: event.timestamp,
    )

    rapid_times = [
        event.timestamp
        for event in rapid_sorted
    ]

    window = timedelta(
        minutes=window_minutes
    )

    candidates: list[
        tuple[
            float,
            tuple,
            tuple,
        ]
    ] = []

    for meal in meals:
        start = meal.timestamp - window
        end = meal.timestamp + window

        left = bisect_left(
            rapid_times,
            start,
        )

        right = bisect_right(
            rapid_times,
            end,
        )

        for index in range(
            left,
            right,
        ):
            rapid = rapid_sorted[index]

            difference_seconds = abs(
                (
                    rapid.timestamp
                    - meal.timestamp
                ).total_seconds()
            )

            candidates.append(
                (
                    difference_seconds,
                    meal.fingerprint,
                    rapid.fingerprint,
                )
            )

    candidates.sort(
        key=lambda item: item[0]
    )

    used_meals: set[tuple] = set()
    used_rapid: set[tuple] = set()

    rapid_to_meal: dict[
        tuple,
        tuple,
    ] = {}

    for (
        _difference_seconds,
        meal_fingerprint,
        rapid_fingerprint,
    ) in candidates:
        if meal_fingerprint in used_meals:
            continue

        if rapid_fingerprint in used_rapid:
            continue

        used_meals.add(
            meal_fingerprint
        )

        used_rapid.add(
            rapid_fingerprint
        )

        rapid_to_meal[
            rapid_fingerprint
        ] = meal_fingerprint

    return rapid_to_meal


def insert_in_batches(
    db,
    model,
    rows: list[dict],
) -> None:
    if not rows:
        return

    for start in range(
        0,
        len(rows),
        BATCH_SIZE,
    ):
        batch = rows[
            start:start + BATCH_SIZE
        ]

        db.execute(
            insert(model),
            batch,
        )


def main() -> None:
    args = parse_args()

    if args.pair_window_minutes < 0:
        raise SystemExit(
            "--pair-window-minutes must be >= 0"
        )

    csv_files = sorted(
        args.csv_dir.glob(
            "*.csv"
        )
    )

    if not csv_files:
        raise SystemExit(
            "No Clarity CSV files found in:\n"
            f"{args.csv_dir.resolve()}"
        )

    (
        raw_events,
        metadata_rows,
        bad_timestamp_rows,
    ) = load_events(
        csv_files
    )

    (
        events,
        duplicate_rows,
    ) = deduplicate_events(
        raw_events
    )

    cgm_events = [
        event
        for event in events
        if (
            event.event_type
            == "Odhadovaná hodnota glukózy"
            and event.glucose is not None
        )
    ]

    cgm_censored = [
        event
        for event in events
        if (
            event.event_type
            == "Odhadovaná hodnota glukózy"
            and event.glucose is None
        )
    ]

    meal_events = [
        event
        for event in events
        if (
            event.event_type == "Jídlo"
            and event.carbohydrates_g
            is not None
        )
    ]

    rapid_events = [
        event
        for event in events
        if (
            event.event_type == "Inzulín"
            and event.subtype
            == "Rychle působící"
            and event.insulin_units
            is not None
        )
    ]

    basal_events = [
        event
        for event in events
        if (
            event.event_type == "Inzulín"
            and event.subtype
            == "Dlouhodobě působící"
            and event.insulin_units
            is not None
        )
    ]

    manual_glucose_events = [
        event
        for event in events
        if event.event_type
        == "Glykémie"
    ]

    calibration_events = [
        event
        for event in events
        if event.event_type
        == "Kalibrace"
    ]

    activity_events = [
        event
        for event in events
        if event.event_type
        == "Aktivita"
    ]

    rapid_to_meal = build_meal_rapid_pairs(
        meals=meal_events,
        rapid_insulin=rapid_events,
        window_minutes=(
            args.pair_window_minutes
        ),
    )

    meal_by_fingerprint = {
        event.fingerprint: event
        for event in meal_events
    }

    db = SessionLocal()

    try:
        user_exists = db.scalar(
            select(
                User.id
            ).where(
                User.id
                == args.user_id
            )
        )

        if user_exists is None:
            raise SystemExit(
                "\nTarget user does not exist "
                "in this database:\n"
                f"{args.user_id}\n"
            )

        existing_glucose_keys = {
            glucose_key(
                measured_at,
                value,
            )
            for (
                measured_at,
                value,
            ) in db.execute(
                select(
                    GlucoseReading.measured_at,
                    GlucoseReading.value_mmol_l,
                ).where(
                    GlucoseReading.user_id
                    == args.user_id,
                    GlucoseReading.source
                    == SOURCE_CGM,
                )
            )
        }

        existing_meals = {
            meal_key(
                eaten_at,
                carbohydrates_g,
            ): meal_id
            for (
                meal_id,
                eaten_at,
                carbohydrates_g,
            ) in db.execute(
                select(
                    Meal.id,
                    Meal.eaten_at,
                    Meal.carbohydrates_g,
                ).where(
                    Meal.user_id
                    == args.user_id
                )
            )
        }

        existing_insulin = {
            insulin_key(
                administered_at,
                insulin_type,
                units,
            ): (
                dose_id,
                meal_id,
                source,
            )
            for (
                dose_id,
                administered_at,
                insulin_type,
                units,
                meal_id,
                source,
            ) in db.execute(
                select(
                    InsulinDose.id,
                    InsulinDose.administered_at,
                    InsulinDose.insulin_type,
                    InsulinDose.units,
                    InsulinDose.meal_id,
                    InsulinDose.source,
                ).where(
                    InsulinDose.user_id
                    == args.user_id
                )
            )
        }

        glucose_rows: list[dict] = []
        meal_rows: list[dict] = []
        insulin_rows: list[dict] = []

        all_meal_ids = dict(
            existing_meals
        )

        skipped_existing_glucose = 0
        skipped_existing_meals = 0
        skipped_existing_insulin = 0

        for event in meal_events:
            key = event_meal_key(
                event
            )

            if key in all_meal_ids:
                skipped_existing_meals += 1
                continue

            meal_id = uuid.uuid4()

            all_meal_ids[
                key
            ] = meal_id

            meal_rows.append(
                {
                    "id": meal_id,
                    "user_id": args.user_id,
                    "eaten_at": clarity_to_utc(
                        event.timestamp
                    ),
                    "carbohydrates_g": (
                        event.carbohydrates_g
                    ),
                    "description": None,
                    "note": (
                        "Imported from "
                        "Dexcom Clarity CSV"
                    ),
                }
            )

        for event in cgm_events:
            key = event_glucose_key(
                event
            )

            if key in existing_glucose_keys:
                skipped_existing_glucose += 1
                continue

            existing_glucose_keys.add(
                key
            )

            glucose_rows.append(
                {
                    "id": uuid.uuid4(),
                    "user_id": args.user_id,
                    "measured_at": clarity_to_utc(
                        event.timestamp
                    ),
                    "value_mmol_l": (
                        event.glucose
                    ),
                    "source": SOURCE_CGM,
                }
            )

        imported_insulin_keys = set(
            existing_insulin.keys()
        )

        existing_link_updates: list[
            tuple[
                uuid.UUID,
                uuid.UUID,
            ]
        ] = []

        rapid_linked_count = 0

        def prepare_insulin_event(
            event: ClarityEvent,
            insulin_type: str,
        ) -> None:
            nonlocal skipped_existing_insulin
            nonlocal rapid_linked_count

            key = event_insulin_key(
                event,
                insulin_type,
            )

            meal_id = None

            if insulin_type == "NOVORAPID":
                meal_fingerprint = (
                    rapid_to_meal.get(
                        event.fingerprint
                    )
                )

                if meal_fingerprint is not None:
                    paired_meal = (
                        meal_by_fingerprint.get(
                            meal_fingerprint
                        )
                    )

                    if paired_meal is not None:
                        paired_key = (
                            event_meal_key(
                                paired_meal
                            )
                        )

                        meal_id = (
                            all_meal_ids.get(
                                paired_key
                            )
                        )

                        if meal_id is not None:
                            rapid_linked_count += 1

            if key in imported_insulin_keys:
                skipped_existing_insulin += 1

                existing = (
                    existing_insulin.get(
                        key
                    )
                )

                if (
                    existing is not None
                    and meal_id is not None
                ):
                    (
                        dose_id,
                        current_meal_id,
                        source,
                    ) = existing

                    if (
                        current_meal_id is None
                        and source
                        == SOURCE_INSULIN
                    ):
                        existing_link_updates.append(
                            (
                                dose_id,
                                meal_id,
                            )
                        )

                return

            imported_insulin_keys.add(
                key
            )

            insulin_rows.append(
                {
                    "id": uuid.uuid4(),
                    "user_id": args.user_id,
                    "meal_id": meal_id,
                    "insulin_type": insulin_type,
                    "units": (
                        event.insulin_units
                    ),
                    "administered_at": clarity_to_utc(
                        event.timestamp
                    ),
                    "source": SOURCE_INSULIN,
                    "note": None,
                }
            )

        for event in rapid_events:
            prepare_insulin_event(
                event,
                "NOVORAPID",
            )

        for event in basal_events:
            prepare_insulin_event(
                event,
                "TRESIBA",
            )

        print()
        print("=" * 72)
        print("DEXCOM CLARITY DATABASE IMPORT")
        print("=" * 72)

        print(
            f"Mode:                "
            f"{'COMMIT' if args.commit else 'DRY RUN'}"
        )

        print(
            f"User ID:             "
            f"{args.user_id}"
        )

        print(
            f"CSV files:           "
            f"{len(csv_files):,}"
        )

        print(
            f"Raw timed rows:      "
            f"{len(raw_events):,}"
        )

        print(
            f"Duplicates removed:  "
            f"{duplicate_rows:,}"
        )

        print(
            f"Unique timed rows:   "
            f"{len(events):,}"
        )

        print(
            f"Metadata rows:       "
            f"{metadata_rows:,}"
        )

        print(
            f"Bad timestamps:      "
            f"{bad_timestamp_rows:,}"
        )

        print()
        print("WOULD INSERT")
        print("-" * 72)

        print(
            f"CGM readings:        "
            f"{len(glucose_rows):,}"
        )

        print(
            f"Meals:               "
            f"{len(meal_rows):,}"
        )

        print(
            f"Insulin doses:       "
            f"{len(insulin_rows):,}"
        )

        print()
        print("ALREADY PRESENT")
        print("-" * 72)

        print(
            f"CGM readings:        "
            f"{skipped_existing_glucose:,}"
        )

        print(
            f"Meals:               "
            f"{skipped_existing_meals:,}"
        )

        print(
            f"Insulin doses:       "
            f"{skipped_existing_insulin:,}"
        )

        print()
        print("MEAL LINKING")
        print("-" * 72)

        print(
            f"Pair window:         "
            f"±{args.pair_window_minutes} min"
        )

        print(
            f"Meal/Rapid pairs:    "
            f"{len(rapid_to_meal):,}"
        )

        print(
            f"Rapid linked:        "
            f"{rapid_linked_count:,}"
        )

        print(
            f"Existing link fixes: "
            f"{len(existing_link_updates):,}"
        )

        print()
        print("INTENTIONALLY SKIPPED")
        print("-" * 72)

        print(
            f"CGM LOW/HIGH:        "
            f"{len(cgm_censored):,}"
        )

        print(
            f"Manual glucose:      "
            f"{len(manual_glucose_events):,}"
        )

        print(
            f"Calibrations:        "
            f"{len(calibration_events):,}"
        )

        print(
            f"Activities:          "
            f"{len(activity_events):,}"
        )

        print()

        print(
            "NOTE: Manual glucose and calibrations "
            "are not mixed into the CGM time series."
        )

        print(
            "NOTE: LOW/HIGH censored readings are "
            "not converted into invented numeric values."
        )

        print(
            "NOTE: Activity import will be handled "
            "separately after inspecting its exact fields."
        )

        print(
            "NOTE: Meal/Rapid timestamp difference is "
            "NOT treated as true prebolus timing."
        )

        print(
            "NOTE: Historical split boluses are not "
            "inferred by this CSV importer."
        )

        if not args.commit:
            db.rollback()

            print()
            print("DATABASE CHANGED: NO")
            print("=" * 72)
            print()

            return

        print()
        print("WRITING TO DATABASE...")
        print("-" * 72)

        insert_in_batches(
            db,
            Meal,
            meal_rows,
        )

        insert_in_batches(
            db,
            GlucoseReading,
            glucose_rows,
        )

        insert_in_batches(
            db,
            InsulinDose,
            insulin_rows,
        )

        for (
            dose_id,
            meal_id,
        ) in existing_link_updates:
            db.execute(
                update(
                    InsulinDose
                )
                .where(
                    InsulinDose.id
                    == dose_id
                )
                .values(
                    meal_id=meal_id
                )
            )

        db.commit()

        print(
            f"Inserted CGM:        "
            f"{len(glucose_rows):,}"
        )

        print(
            f"Inserted meals:      "
            f"{len(meal_rows):,}"
        )

        print(
            f"Inserted insulin:    "
            f"{len(insulin_rows):,}"
        )

        print(
            f"Updated meal links:  "
            f"{len(existing_link_updates):,}"
        )

        print()

        print("DATABASE CHANGED: YES")
        print("=" * 72)
        print()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()