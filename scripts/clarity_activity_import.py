from __future__ import annotations

import argparse
import csv
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models.activity import Activity


CSV_DIR = Path(
    "data/private/clarity/csv"
)

USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

PRAGUE = ZoneInfo(
    "Europe/Prague"
)

SOURCE_NOTE = (
    "Imported from Dexcom Clarity CSV"
)


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--commit",
        action="store_true",
    )

    return parser.parse_args()


def parse_duration(
    value: str,
) -> timedelta:
    hours, minutes, seconds = (
        int(part)
        for part in value.split(":")
    )

    return timedelta(
        hours=hours,
        minutes=minutes,
        seconds=seconds,
    )


def map_intensity(
    value: str,
) -> str | None:
    normalized = value.strip().lower()

    mapping = {
        "těžké": "HIGH",
        "tezke": "HIGH",
        "střední": "MEDIUM",
        "stredni": "MEDIUM",
        "lehké": "LOW",
        "lehke": "LOW",
    }

    return mapping.get(
        normalized
    )


def load_activities():
    unique = {}

    for path in sorted(
        CSV_DIR.glob("*.csv")
    ):
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(
                handle,
                delimiter=";",
            )

            for row in reader:
                event_type = (
                    row.get(
                        "Typ události"
                    )
                    or ""
                ).strip()

                if event_type != "Aktivita":
                    continue

                timestamp_raw = (
                    row.get(
                        "Časové razítko (RRRR-MM-DDThh:mm:ss)"
                    )
                    or ""
                ).strip()

                duration_raw = (
                    row.get(
                        "Trvání (hh:mm:ss)"
                    )
                    or ""
                ).strip()

                subtype = (
                    row.get(
                        "Podtyp události"
                    )
                    or ""
                ).strip()

                if (
                    not timestamp_raw
                    or not duration_raw
                ):
                    continue

                local_start = datetime.fromisoformat(
                    timestamp_raw
                ).replace(
                    tzinfo=PRAGUE
                )

                start = local_start.astimezone(
                    ZoneInfo("UTC")
                )

                duration = parse_duration(
                    duration_raw
                )

                end = (
                    start
                    + duration
                )

                intensity = map_intensity(
                    subtype
                )

                key = (
                    start,
                    end,
                    intensity,
                )

                unique[key] = {
                    "started_at": start,
                    "ended_at": end,
                    "intensity": intensity,
                }

    return list(
        unique.values()
    )


def main():
    args = parse_args()

    activities = load_activities()

    db = SessionLocal()

    try:
        existing = (
            db.execute(
                select(
                    Activity
                ).where(
                    Activity.user_id
                    == USER_ID
                )
            )
            .scalars()
            .all()
        )

        existing_keys = {
            (
                row.started_at,
                row.ended_at,
            )
            for row in existing
        }

        would_insert = 0
        already_present = 0

        print()
        print("=" * 60)
        print("CLARITY ACTIVITY IMPORT")
        print("=" * 60)

        print(
            "Mode:",
            "COMMIT"
            if args.commit
            else "DRY RUN",
        )

        print(
            "Unique CSV activities:",
            len(activities),
        )

        print()

        for item in activities:
            key = (
                item["started_at"],
                item["ended_at"],
            )

            if key in existing_keys:
                already_present += 1
                continue

            would_insert += 1

            print(
                item["started_at"],
                "->",
                item["ended_at"],
                "|",
                item["intensity"],
            )

            db.add(
                Activity(
                    user_id=USER_ID,
                    started_at=(
                        item["started_at"]
                    ),
                    ended_at=(
                        item["ended_at"]
                    ),
                    activity_type=(
                        "UNSPECIFIED"
                    ),
                    intensity=(
                        item["intensity"]
                    ),
                    note=SOURCE_NOTE,
                )
            )

        print()
        print(
            "Would insert:",
            would_insert,
        )

        print(
            "Already present:",
            already_present,
        )

        if args.commit:
            db.commit()

            print(
                "DATABASE CHANGED: YES"
            )

        else:
            db.rollback()

            print(
                "DATABASE CHANGED: NO"
            )

        print("=" * 60)

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()