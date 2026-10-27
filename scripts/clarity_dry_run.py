from __future__ import annotations

import csv
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


CSV_DIR = Path("data/private/clarity/csv")

TIMESTAMP_COLUMN = "Časové razítko (RRRR-MM-DDThh:mm:ss)"
EVENT_TYPE_COLUMN = "Typ události"
EVENT_SUBTYPE_COLUMN = "Podtyp události"
GLUCOSE_COLUMN = "Hodnota glukózy (mmol/L)"
INSULIN_COLUMN = "Hodnota inzulinu (j)"
CARBS_COLUMN = "Hodnota sacharidů (gramů)"
DURATION_COLUMN = "Trvání (hh:mm:ss)"
GLUCOSE_RATE_COLUMN = "Rychlost změny glukózy (mmol/L/min)"


@dataclass(frozen=True)
class ClarityEvent:
    timestamp: datetime
    event_type: str
    subtype: str

    glucose_raw: str
    glucose: float | None

    insulin_units: float | None
    carbohydrates_g: float | None

    duration: str
    glucose_rate: float | None

    @property
    def fingerprint(self) -> tuple:
        """
        Identita události napříč překrývajícími se Clarity exporty.

        Záměrně nepoužíváme sloupec "Obsah", protože jde pouze
        o pořadové číslo řádku konkrétního exportu.
        """
        return (
            self.timestamp.isoformat(),
            self.event_type,
            self.subtype,
            self.glucose_raw,
            self.insulin_units,
            self.carbohydrates_g,
            self.duration,
            self.glucose_rate,
        )


def clean(value: str | None) -> str:
    return (value or "").strip()


def parse_float(value: str | None) -> float | None:
    value = clean(value)

    if not value:
        return None

    value = value.replace(",", ".")

    try:
        return float(value)
    except ValueError:
        return None


def parse_timestamp(value: str | None) -> datetime | None:
    value = clean(value)

    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_events(csv_files: list[Path]) -> tuple[list[ClarityEvent], int, int]:
    events: list[ClarityEvent] = []

    metadata_rows = 0
    invalid_timestamp_rows = 0

    for csv_file in csv_files:
        with csv_file.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(
                handle,
                delimiter=";",
            )

            for row in reader:
                timestamp_raw = clean(
                    row.get(TIMESTAMP_COLUMN)
                )

                timestamp = parse_timestamp(
                    timestamp_raw
                )

                if timestamp is None:
                    if timestamp_raw:
                        invalid_timestamp_rows += 1
                    else:
                        metadata_rows += 1

                    continue

                event = ClarityEvent(
                    timestamp=timestamp,
                    event_type=clean(
                        row.get(EVENT_TYPE_COLUMN)
                    ),
                    subtype=clean(
                        row.get(EVENT_SUBTYPE_COLUMN)
                    ),
                    glucose_raw=clean(
                        row.get(GLUCOSE_COLUMN)
                    ),
                    glucose=parse_float(
                        row.get(GLUCOSE_COLUMN)
                    ),
                    insulin_units=parse_float(
                        row.get(INSULIN_COLUMN)
                    ),
                    carbohydrates_g=parse_float(
                        row.get(CARBS_COLUMN)
                    ),
                    duration=clean(
                        row.get(DURATION_COLUMN)
                    ),
                    glucose_rate=parse_float(
                        row.get(GLUCOSE_RATE_COLUMN)
                    ),
                )

                events.append(event)

    return (
        events,
        metadata_rows,
        invalid_timestamp_rows,
    )


def deduplicate_events(
    events: list[ClarityEvent],
) -> tuple[list[ClarityEvent], int]:
    unique_events: list[ClarityEvent] = []

    seen: set[tuple] = set()

    duplicates = 0

    for event in sorted(
        events,
        key=lambda item: item.timestamp,
    ):
        fingerprint = event.fingerprint

        if fingerprint in seen:
            duplicates += 1
            continue

        seen.add(fingerprint)

        unique_events.append(event)

    return unique_events, duplicates


def format_date_range(
    events: list[ClarityEvent],
) -> str:
    if not events:
        return "-"

    events = sorted(
        events,
        key=lambda item: item.timestamp,
    )

    return (
        f"{events[0].timestamp} "
        f"-> "
        f"{events[-1].timestamp}"
    )


def analyse_meal_rapid_pairing(
    meals: list[ClarityEvent],
    rapid_insulin: list[ClarityEvent],
) -> Counter:
    result = Counter()

    rapid_insulin = sorted(
        rapid_insulin,
        key=lambda item: item.timestamp,
    )

    rapid_times = [
        event.timestamp
        for event in rapid_insulin
    ]

    for meal in meals:
        index = bisect_left(
            rapid_times,
            meal.timestamp,
        )

        candidates: list[ClarityEvent] = []

        if index < len(rapid_insulin):
            candidates.append(
                rapid_insulin[index]
            )

        if index > 0:
            candidates.append(
                rapid_insulin[index - 1]
            )

        if not candidates:
            result["no_pair"] += 1
            continue

        nearest = min(
            candidates,
            key=lambda event: abs(
                (
                    event.timestamp
                    - meal.timestamp
                ).total_seconds()
            ),
        )

        delta_minutes = (
            nearest.timestamp
            - meal.timestamp
        ).total_seconds() / 60.0

        absolute_delta = abs(
            delta_minutes
        )

        if absolute_delta <= 2:
            result["0_2"] += 1

        elif absolute_delta <= 5:
            result["2_5"] += 1

        elif absolute_delta <= 15:
            result["5_15"] += 1

        elif absolute_delta <= 30:
            result["15_30"] += 1

        else:
            result["over_30"] += 1

    return result


def main() -> None:
    csv_files = sorted(
        CSV_DIR.glob("*.csv")
    )

    if not csv_files:
        raise SystemExit(
            "Nebyly nalezeny žádné CSV soubory v:\n"
            f"{CSV_DIR.resolve()}"
        )

    (
        raw_events,
        metadata_rows,
        invalid_timestamp_rows,
    ) = load_events(
        csv_files
    )

    (
        events,
        duplicates,
    ) = deduplicate_events(
        raw_events
    )

    event_type_counts = Counter(
        event.event_type
        for event in events
    )

    cgm = [
        event
        for event in events
        if event.event_type
        == "Odhadovaná hodnota glukózy"
    ]

    cgm_numeric = [
        event
        for event in cgm
        if event.glucose is not None
    ]

    cgm_low = [
        event
        for event in cgm
        if event.glucose_raw.casefold()
        == "nízká"
    ]

    cgm_high = [
        event
        for event in cgm
        if event.glucose_raw.casefold()
        == "vysoká"
    ]

    cgm_other_non_numeric = [
        event
        for event in cgm
        if (
            event.glucose is None
            and event.glucose_raw.casefold()
            not in {
                "nízká",
                "vysoká",
            }
        )
    ]

    meals = [
        event
        for event in events
        if event.event_type == "Jídlo"
    ]

    rapid_insulin = [
        event
        for event in events
        if (
            event.event_type == "Inzulín"
            and event.subtype
            == "Rychle působící"
        )
    ]

    basal_insulin = [
        event
        for event in events
        if (
            event.event_type == "Inzulín"
            and event.subtype
            == "Dlouhodobě působící"
        )
    ]

    manual_glucose = [
        event
        for event in events
        if event.event_type == "Glykémie"
    ]

    calibrations = [
        event
        for event in events
        if event.event_type == "Kalibrace"
    ]

    activities = [
        event
        for event in events
        if event.event_type == "Aktivita"
    ]

    pairing = analyse_meal_rapid_pairing(
        meals,
        rapid_insulin,
    )

    paired_within_30 = (
        pairing["0_2"]
        + pairing["2_5"]
        + pairing["5_15"]
        + pairing["15_30"]
    )

    if meals:
        pairing_percentage = (
            paired_within_30
            / len(meals)
            * 100
        )
    else:
        pairing_percentage = 0.0

    print()
    print("=" * 72)
    print("DEXCOM CLARITY DRY RUN")
    print("=" * 72)

    print(
        f"CSV directory:       "
        f"{CSV_DIR.resolve()}"
    )

    print(
        f"CSV files:           "
        f"{len(csv_files)}"
    )

    print(
        f"Raw timed rows:      "
        f"{len(raw_events):,}"
    )

    print(
        f"Duplicates removed:  "
        f"{duplicates:,}"
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
        f"{invalid_timestamp_rows:,}"
    )

    print()

    print("UNIQUE DATA")
    print("-" * 72)

    print(
        f"CGM numeric:         "
        f"{len(cgm_numeric):,}"
    )

    print(
        f"CGM LOW (censored):  "
        f"{len(cgm_low):,}"
    )

    print(
        f"CGM HIGH (censored): "
        f"{len(cgm_high):,}"
    )

    print(
        f"CGM other nonnum.:   "
        f"{len(cgm_other_non_numeric):,}"
    )

    print(
        f"Manual glucose:      "
        f"{len(manual_glucose):,}"
    )

    print(
        f"Calibrations:        "
        f"{len(calibrations):,}"
    )

    print(
        f"Meals:               "
        f"{len(meals):,}"
    )

    print(
        f"Rapid insulin:       "
        f"{len(rapid_insulin):,}"
    )

    print(
        f"Basal insulin:       "
        f"{len(basal_insulin):,}"
    )

    print(
        f"Activities:          "
        f"{len(activities):,}"
    )

    print()

    print("DATE RANGES")
    print("-" * 72)

    print(
        f"All events:          "
        f"{format_date_range(events)}"
    )

    print(
        f"CGM:                 "
        f"{format_date_range(cgm)}"
    )

    print(
        f"Meals:               "
        f"{format_date_range(meals)}"
    )

    print(
        f"Rapid insulin:       "
        f"{format_date_range(rapid_insulin)}"
    )

    print(
        f"Basal insulin:       "
        f"{format_date_range(basal_insulin)}"
    )

    print(
        f"Activities:          "
        f"{format_date_range(activities)}"
    )

    print()

    print("MEAL <-> NEAREST RAPID INSULIN")
    print("-" * 72)

    print(
        f"Meals with rapid <= 30 min: "
        f"{paired_within_30:,} / "
        f"{len(meals):,} "
        f"({pairing_percentage:.1f}%)"
    )

    print(
        f"  <= 2 min:               "
        f"{pairing['0_2']:,}"
    )

    print(
        f"  >2 to 5 min:            "
        f"{pairing['2_5']:,}"
    )

    print(
        f"  >5 to 15 min:           "
        f"{pairing['5_15']:,}"
    )

    print(
        f"  >15 to 30 min:          "
        f"{pairing['15_30']:,}"
    )

    print(
        f"  >30 min / no pair:      "
        f"{pairing['over_30'] + pairing['no_pair']:,}"
    )

    print()

    print("EVENT TYPES")
    print("-" * 72)

    for event_type, count in (
        event_type_counts.most_common()
    ):
        print(
            f"{event_type:<35} "
            f"{count:>8,}"
        )

    print()
    print(
        "NOTE: CSV timestamps are zatím "
        "brány jako lokální časy."
    )

    print(
        "      Při skutečném importu je "
        "převedeme přes Europe/Prague,"
    )

    print(
        "      aby správně fungoval i "
        "letní/zimní čas."
    )

    print()

    print(
        "NOTE: rozdíl času Meal <-> Rapid "
        "NEPOVAŽUJEME za skutečný prebolus."
    )

    print(
        "      Prebolus budeme enrichmentovat "
        "z Denních PDF tam, kde je explicitně zapsaný."
    )

    print()
    print("DATABASE CHANGED: NO")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()