from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pymupdf as fitz
from sqlalchemy import select

from app.database import SessionLocal
from app.models.meal import Meal


PDF_DIR = Path("data/private/clarity/pdf")
TESSDATA_DIR = Path("data/private/tessdata")
OCR_CACHE_DIR = Path("data/private/clarity/ocr_cache")

OUTPUT_JSON = Path(
    "data/private/clarity/pdf_dry_run.json"
)

DEFAULT_USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

PRAGUE = ZoneInfo("Europe/Prague")

DEFAULT_ZOOM = 2.5
DEFAULT_WORKERS = 4

DEFAULT_MEAL_WINDOW_MINUTES = 3
DEFAULT_CARB_TOLERANCE_G = 1.0

CLARITY_IMPORT_NOTE = (
    "Imported from Dexcom Clarity CSV"
)

OCR_CACHE_VERSION = "clarity-ocr-v1"


MONTHS = {
    "led": 1,
    "ledna": 1,

    "uno": 2,
    "unor": 2,

    "bre": 3,
    "brezen": 3,

    "dub": 4,
    "duben": 4,

    "kve": 5,
    "kveten": 5,

    "cer": 6,
    "cerven": 6,
    "cvn": 6,

    "cvc": 7,
    "cervenec": 7,

    "srp": 8,
    "srpen": 8,

    "zar": 9,
    "zari": 9,

    "rij": 10,
    "rijen": 10,
    "fij": 10,

    "lis": 11,
    "listopad": 11,

    "pro": 12,
    "prosinec": 12,
}


@dataclass(frozen=True)
class PdfEvent:
    event_date: date
    event_time: time

    event_type: str
    detail: str

    carbohydrates_g: float | None = None

    insulin_units: float | None = None
    insulin_kind: str | None = None

    prebolus_minutes: float | None = None
    prebolus_explicit_none: bool = False

    feedback_meal: str | None = None
    feedback_result: str | None = None

    activity_minutes: int | None = None
    activity_intensity: str | None = None

    source_file: str = ""
    source_page: int = 0

    @property
    def local_datetime(self) -> datetime:
        return datetime.combine(
            self.event_date,
            self.event_time,
            tzinfo=PRAGUE,
        )

    @property
    def fingerprint(self) -> tuple:
        if self.event_type == "MEAL":
            normalized_carbs = (
                self.carbohydrates_g
            )

            if normalized_carbs is not None:
                rounded = int(
                    round(
                        normalized_carbs
                    )
                )

                # OCR sometimes reads:
                #   70g -> 709
                #   75g -> 759
                #
                # Normalize this known OCR artifact already
                # for duplicate detection.
                if (
                        rounded >= 500
                        and rounded % 10 == 9
                ):
                    normalized_carbs = float(
                        rounded // 10
                    )

            return (
                self.event_date.isoformat(),
                self.event_time.strftime("%H:%M"),
                self.event_type,
                (
                    round(
                        normalized_carbs,
                        2,
                    )
                    if normalized_carbs is not None
                    else None
                ),
            )

        if self.event_type == "INSULIN":
            return (
                self.event_date.isoformat(),
                self.event_time.strftime("%H:%M"),
                self.event_type,
                self.insulin_kind,
                (
                    round(
                        self.insulin_units,
                        2,
                    )
                    if self.insulin_units is not None
                    else None
                ),
            )

        return (
            self.event_date.isoformat(),
            self.event_time.strftime("%H:%M"),
            self.event_type,
            normalize_for_key(
                self.detail
            ),
        )


@dataclass(frozen=True)
class OcrPageResult:
    page_number: int
    text: str
    cache_hit: bool
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fast OCR dry-run for Dexcom Clarity Daily PDFs. "
            "Does NOT write to the database."
        )
    )

    parser.add_argument(
        "--user-id",
        type=uuid.UUID,
        default=DEFAULT_USER_ID,
    )

    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=PDF_DIR,
    )

    parser.add_argument(
        "--tessdata-dir",
        type=Path,
        default=TESSDATA_DIR,
    )

    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=OCR_CACHE_DIR,
    )

    parser.add_argument(
        "--zoom",
        type=float,
        default=DEFAULT_ZOOM,
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=(
            "Number of pages OCR'd in parallel. "
            "Default: 4."
        ),
    )

    parser.add_argument(
        "--meal-window-minutes",
        type=float,
        default=DEFAULT_MEAL_WINDOW_MINUTES,
    )

    parser.add_argument(
        "--carb-tolerance-g",
        type=float,
        default=DEFAULT_CARB_TOLERANCE_G,
    )

    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help=(
            "Ignore existing OCR cache and OCR pages again."
        ),
    )

    parser.add_argument(
        "--output-json",
        type=Path,
        default=OUTPUT_JSON,
    )

    return parser.parse_args()


def ascii_text(
    value: str,
) -> str:
    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(
            char
        )
    )

    value = value.lower()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_for_key(
    value: str,
) -> str:
    value = ascii_text(
        value
    )

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def clean_ocr_detail(
    value: str,
) -> str:
    value = value.strip()

    value = re.sub(
        r"\s*[=©®]+\s*$",
        "",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def parse_decimal(
    value: str | None,
) -> float | None:
    if value is None:
        return None

    value = value.strip()

    if not value:
        return None

    value = value.replace(
        ",",
        ".",
    )

    try:
        return float(
            value
        )

    except ValueError:
        return None


def find_tesseract() -> Path:
    discovered = shutil.which(
        "tesseract"
    )

    if discovered:
        return Path(
            discovered
        )

    windows_default = Path(
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )

    if windows_default.exists():
        return windows_default

    raise SystemExit(
        "Tesseract nebyl nalezen."
    )


def sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as handle:
        while True:
            block = handle.read(
                1024 * 1024
            )

            if not block:
                break

            digest.update(
                block
            )

    return digest.hexdigest()


def run_tesseract(
    tesseract: Path,
    tessdata_dir: Path,
    png_bytes: bytes,
) -> str:
    command = [
        str(tesseract),
        "stdin",
        "stdout",
        "--tessdata-dir",
        str(
            tessdata_dir.resolve()
        ),
        "-l",
        "ces+eng",
        "--psm",
        "6",
        "--dpi",
        "300",
    ]

    result = subprocess.run(
        command,
        input=png_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:
        stderr = (
            result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

        raise RuntimeError(
            "Tesseract failed:\n"
            f"{stderr}"
        )

    return result.stdout.decode(
        "utf-8",
        errors="replace",
    )


def render_page_png(
    page,
    zoom: float,
) -> bytes:
    matrix = fitz.Matrix(
        zoom,
        zoom,
    )

    pixmap = page.get_pixmap(
        matrix=matrix,
        alpha=False,
        colorspace=fitz.csGRAY,
    )

    return pixmap.tobytes(
        "png"
    )


def make_cache_path(
    cache_dir: Path,
    file_hash: str,
    page_number: int,
    zoom: float,
) -> Path:
    cache_identity = (
        f"{OCR_CACHE_VERSION}|"
        f"{file_hash}|"
        f"page={page_number}|"
        f"zoom={zoom:.3f}|"
        f"lang=ces+eng|"
        f"psm=6"
    )

    cache_hash = hashlib.sha256(
        cache_identity.encode(
            "utf-8"
        )
    ).hexdigest()

    return (
        cache_dir
        / f"{cache_hash}.txt"
    )


def ocr_page_with_cache(
    pdf_file: Path,
    file_hash: str,
    page_number: int,
    zoom: float,
    tesseract: Path,
    tessdata_dir: Path,
    cache_dir: Path,
    refresh_cache: bool,
) -> OcrPageResult:
    cache_file = make_cache_path(
        cache_dir=cache_dir,
        file_hash=file_hash,
        page_number=page_number,
        zoom=zoom,
    )

    if (
        cache_file.exists()
        and not refresh_cache
    ):
        try:
            text = cache_file.read_text(
                encoding="utf-8"
            )

            return OcrPageResult(
                page_number=page_number,
                text=text,
                cache_hit=True,
            )

        except Exception:
            # Broken cache should never prevent OCR.
            pass

    document = None

    try:
        # Each worker opens its own document.
        # We deliberately do not share one PyMuPDF
        # Document between threads.
        document = fitz.open(
            pdf_file
        )

        page = document.load_page(
            page_number - 1
        )

        png_bytes = render_page_png(
            page=page,
            zoom=zoom,
        )

        text = run_tesseract(
            tesseract=tesseract,
            tessdata_dir=tessdata_dir,
            png_bytes=png_bytes,
        )

        cache_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        cache_file.write_text(
            text,
            encoding="utf-8",
        )

        return OcrPageResult(
            page_number=page_number,
            text=text,
            cache_hit=False,
        )

    except Exception as exc:
        return OcrPageResult(
            page_number=page_number,
            text="",
            cache_hit=False,
            error=str(
                exc
            ),
        )

    finally:
        if document is not None:
            document.close()


def parse_month(
    token: str,
) -> int | None:
    token = normalize_for_key(
        token
    )

    if token in MONTHS:
        return MONTHS[
            token
        ]

    for key, month in (
        MONTHS.items()
    ):
        if token.startswith(
            key
        ):
            return month

    return None


def extract_daily_dates(
    text: str,
) -> list[date]:
    """
    Extract actual daily headings such as:

        út 1. zář 2026
        po 31. srp 2026

    Ignore the report range in the main header and
    the generated/export date in the footer.
    """
    result: list[date] = []
    seen: set[date] = set()

    lines = text.splitlines()

    candidate_lines: list[str] = []

    for line in lines[:40]:
        normalized = ascii_text(
            line
        ).strip()

        if (
            "cas" in normalized
            and "zarizeni" in normalized
            and "udalost" in normalized
        ):
            break

        candidate_lines.append(
            normalized
        )

    for normalized in candidate_lines:
        if not normalized:
            continue

        match = re.match(
            (
                r"^\s*"
                r"(?:po|ut|st|ct|pa|so|ne)"
                r"\s+"
                r"(\d{1,2})"
                r"\.\s*"
                r"([a-z]{2,15})"
                r"\s+"
                r"(20\d{2})"
                r"\b"
            ),
            normalized,
        )

        if match is None:
            continue

        day = int(
            match.group(1)
        )

        month = parse_month(
            match.group(2)
        )

        year = int(
            match.group(3)
        )

        if month is None:
            continue

        try:
            parsed = date(
                year,
                month,
                day,
            )

        except ValueError:
            continue

        if parsed not in seen:
            seen.add(
                parsed
            )

            result.append(
                parsed
            )

    return result


def strip_glucose_suffix(
    value: str,
) -> str:
    value = value.strip()

    value = re.sub(
        (
            r"\s+(?:[-–—|]\s*)?"
            r"\d{1,2}[.,]\d+\s*"
            r"mmol\s*/?\s*l\.?\s*$"
        ),
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value.strip(
        " |-"
    )


def classify_event_type(
    raw_tail: str,
) -> tuple[str | None, str]:
    normalized = ascii_text(
        raw_tail
    )

    choices = [
        (
            "MEAL",
            (
                "jidlo",
                "jidio",
            ),
        ),
        (
            "NOTE",
            (
                "poznamka",
                "poznarnka",
            ),
        ),
        (
            "ACTIVITY",
            (
                "aktivita",
            ),
        ),
        (
            "INSULIN",
            (
                "inzulin",
            ),
        ),
        (
            "CALIBRATION",
            (
                "kalibrace",
            ),
        ),
        (
            "GLUCOSE",
            (
                "glykemie",
                "glukoza",
            ),
        ),
    ]

    for (
        event_type,
        aliases,
    ) in choices:
        for alias in aliases:
            match = re.match(
                rf"^\s*{re.escape(alias)}\b",
                normalized,
            )

            if match is None:
                continue

            parts = (
                raw_tail
                .strip()
                .split(
                    maxsplit=1
                )
            )

            if len(parts) == 1:
                detail = ""

            else:
                detail = parts[1]

            return (
                event_type,
                detail,
            )

    return (
        None,
        raw_tail,
    )


def extract_prebolus(
    detail: str,
) -> tuple[
    float | None,
    bool,
]:
    normalized = ascii_text(
        detail
    )

    if "prebolus" not in normalized:
        return (
            None,
            False,
        )

    if any(
        phrase in normalized
        for phrase in (
            "zadny",
            "zadnej",
            "zadne",
            "bez prebolusu",
        )
    ):
        return (
            0.0,
            True,
        )

    match = re.search(
        (
            r"prebolus\s*"
            r"(\d+(?:[.,]\d+)?)"
        ),
        normalized,
    )

    if match is None:
        return (
            None,
            False,
        )

    return (
        parse_decimal(
            match.group(1)
        ),
        False,
    )


def extract_feedback(
    detail: str,
) -> tuple[
    str | None,
    str | None,
]:
    normalized = ascii_text(
        detail
    )

    match = re.search(
        (
            r"inzulinu\s+k\s+"
            r"(snidani|obedu|veceri)"
            r"\s+bylo\s+"
            r"(malo|akorat|moc)"
        ),
        normalized,
    )

    if match is None:
        return (
            None,
            None,
        )

    meal_map = {
        "snidani": "BREAKFAST",
        "obedu": "LUNCH",
        "veceri": "DINNER",
    }

    result_map = {
        "malo": "TOO_LITTLE",
        "akorat": "OK",
        "moc": "TOO_MUCH",
    }

    return (
        meal_map.get(
            match.group(1)
        ),
        result_map.get(
            match.group(2)
        ),
    )


def extract_activity(
    detail: str,
) -> tuple[
    int | None,
    str | None,
]:
    normalized = ascii_text(
        detail
    )

    minutes = None

    hour_match = re.search(
        (
            r"(\d+)\s*h"
            r"[^\d]{0,8}"
            r"(\d+)?\s*min"
        ),
        normalized,
    )

    if hour_match is not None:
        hours = int(
            hour_match.group(1)
        )

        extra_minutes = int(
            hour_match.group(2)
            or 0
        )

        minutes = (
            hours * 60
            + extra_minutes
        )

    else:
        hour_only_match = re.search(
            r"(\d+)\s*h\b",
            normalized,
        )

        if hour_only_match is not None:
            minutes = (
                int(
                    hour_only_match.group(
                        1
                    )
                )
                * 60
            )

        else:
            minute_match = re.search(
                r"(\d+)\s*min",
                normalized,
            )

            if minute_match is not None:
                minutes = int(
                    minute_match.group(
                        1
                    )
                )

    intensity = None

    if any(
        word in normalized
        for word in (
            "tezka",
            "tezke",
            "vysoka",
        )
    ):
        intensity = "HIGH"

    elif any(
        word in normalized
        for word in (
            "stredni",
            "stredne",
        )
    ):
        intensity = "MEDIUM"

    elif any(
        word in normalized
        for word in (
            "lehka",
            "lehke",
            "nizka",
        )
    ):
        intensity = "LOW"

    return (
        minutes,
        intensity,
    )


def parse_ocr_event_line(
    line: str,
    page_date: date,
    source_file: str,
    source_page: int,
) -> PdfEvent | None:
    line = line.strip()

    match = re.match(
        (
            r"^\s*"
            r"(\d{1,2}:\d{2})"
            r"\s*(?:\||I|l)?"
            r"\s*CGM\s+"
            r"(.+)$"
        ),
        line,
        flags=re.IGNORECASE,
    )

    if match is None:
        return None

    try:
        event_time = (
            datetime.strptime(
                match.group(1),
                "%H:%M",
            )
            .time()
        )

    except ValueError:
        return None

    raw_tail = match.group(
        2
    )

    (
        event_type,
        detail,
    ) = classify_event_type(
        raw_tail
    )

    if event_type is None:
        return None

    detail = strip_glucose_suffix(
        detail
    )

    detail = clean_ocr_detail(
        detail
    )

    carbs = None

    insulin_units = None
    insulin_kind = None

    prebolus_minutes = None
    prebolus_explicit_none = False

    feedback_meal = None
    feedback_result = None

    activity_minutes = None
    activity_intensity = None

    if event_type == "MEAL":
        meal_match = re.match(
            (
                r"^\s*"
                r"(\d+(?:[.,]\d+)?)"
                r"\s*g\b"
                r"(.*)$"
            ),
            detail,
            flags=re.IGNORECASE,
        )

        if meal_match is not None:
            carbs = parse_decimal(
                meal_match.group(
                    1
                )
            )

            remainder = (
                meal_match.group(
                    2
                )
            )

            remainder = (
                remainder.lstrip(
                    " +-–—°:"
                )
            )

            if remainder:
                detail = (
                    clean_ocr_detail(
                        remainder
                    )
                )

    elif event_type == "NOTE":
        (
            prebolus_minutes,
            prebolus_explicit_none,
        ) = extract_prebolus(
            detail
        )

        (
            feedback_meal,
            feedback_result,
        ) = extract_feedback(
            detail
        )

    elif event_type == "ACTIVITY":
        (
            activity_minutes,
            activity_intensity,
        ) = extract_activity(
            detail
        )

    elif event_type == "INSULIN":
        normalized = ascii_text(
            detail
        )

        if "rychle" in normalized:
            insulin_kind = "RAPID"

        elif "dlouhodobe" in normalized:
            insulin_kind = "BASAL"

        units_match = re.search(
            (
                r"(\d+(?:[.,]\d+)?)"
                r"\s*j\b"
            ),
            normalized,
        )

        if units_match is not None:
            insulin_units = (
                parse_decimal(
                    units_match.group(
                        1
                    )
                )
            )

    return PdfEvent(
        event_date=page_date,
        event_time=event_time,
        event_type=event_type,
        detail=detail,

        carbohydrates_g=carbs,

        insulin_units=insulin_units,
        insulin_kind=insulin_kind,

        prebolus_minutes=(
            prebolus_minutes
        ),

        prebolus_explicit_none=(
            prebolus_explicit_none
        ),

        feedback_meal=(
            feedback_meal
        ),

        feedback_result=(
            feedback_result
        ),

        activity_minutes=(
            activity_minutes
        ),

        activity_intensity=(
            activity_intensity
        ),

        source_file=source_file,
        source_page=source_page,
    )


def looks_like_truncated_page(
    text: str,
) -> bool:
    normalized = ascii_text(
        text
    )

    return (
        "nektere udalosti nejsou zobrazeny"
        in normalized
    )


def deduplicate_events(
    events: list[PdfEvent],
) -> tuple[
    list[PdfEvent],
    int,
]:
    unique: list[PdfEvent] = []

    seen: set[tuple] = set()

    duplicates = 0

    for event in sorted(
        events,
        key=lambda item: (
            item.local_datetime,
            item.event_type,
        ),
    ):
        key = event.fingerprint

        if key in seen:
            duplicates += 1
            continue

        seen.add(
            key
        )

        unique.append(
            event
        )

    return (
        unique,
        duplicates,
    )


def load_database_meals(
    user_id: uuid.UUID,
) -> list[dict]:
    """
    Only meals created by the Clarity CSV importer
    are eligible for PDF enrichment.
    """
    db = SessionLocal()

    try:
        rows = db.execute(
            select(
                Meal.id,
                Meal.eaten_at,
                Meal.carbohydrates_g,
                Meal.description,
                Meal.note,
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
            note,
        ) in rows:
            if eaten_at.tzinfo is None:
                local_dt = (
                    eaten_at.replace(
                        tzinfo=PRAGUE
                    )
                )

            else:
                local_dt = (
                    eaten_at.astimezone(
                        PRAGUE
                    )
                )

            result.append(
                {
                    "id": meal_id,

                    "local_datetime": (
                        local_dt
                    ),

                    "carbohydrates_g": float(
                        carbs
                    ),

                    "description": (
                        description
                    ),

                    "note": note,
                }
            )

        return result

    finally:
        db.close()

def get_pdf_carb_candidates(
    carbohydrates_g: float,
) -> list[float]:
    candidates = [
        carbohydrates_g
    ]

    rounded = int(
        round(
            carbohydrates_g
        )
    )

    # OCR sometimes reads:
    #
    #   70g -> 709
    #   75g -> 759
    #
    # Only offer the repaired value as an alternative.
    # The database still has to confirm it by time + carbs.
    if (
        rounded >= 500
        and rounded % 10 == 9
    ):
        repaired = float(
            rounded // 10
        )

        candidates.append(
            repaired
        )

    return candidates

def match_pdf_meals_to_database(
    pdf_meals: list[PdfEvent],
    db_meals: list[dict],
    window_minutes: float,
    carb_tolerance_g: float,
) -> tuple[
    list[dict],
    list[PdfEvent],
    list[PdfEvent],
]:
    db_by_date: dict[
        date,
        list[dict],
    ] = defaultdict(
        list
    )

    for meal in db_meals:
        db_by_date[
            meal[
                "local_datetime"
            ].date()
        ].append(
            meal
        )

    used_db_ids: set[
        uuid.UUID
    ] = set()

    matched: list[dict] = []
    unmatched: list[PdfEvent] = []
    ambiguous: list[PdfEvent] = []

    for event in pdf_meals:
        if event.carbohydrates_g is None:
            unmatched.append(
                event
            )

            continue

        candidates = []

        for db_meal in db_by_date.get(
            event.event_date,
            [],
        ):
            if (
                db_meal["id"]
                in used_db_ids
            ):
                continue

            time_delta_minutes = abs(
                (
                    db_meal[
                        "local_datetime"
                    ]
                    - event.local_datetime
                ).total_seconds()
            ) / 60.0

            best_carb_delta = None
            matched_pdf_carbs = None

            for pdf_carbs in get_pdf_carb_candidates(
                    event.carbohydrates_g
            ):
                carb_delta = abs(
                    db_meal[
                        "carbohydrates_g"
                    ]
                    - pdf_carbs
                )

                if (
                        best_carb_delta is None
                        or carb_delta
                        < best_carb_delta
                ):
                    best_carb_delta = (
                        carb_delta
                    )

                    matched_pdf_carbs = (
                        pdf_carbs
                    )

            if (
                    time_delta_minutes
                    <= window_minutes
                    and best_carb_delta
                    is not None
                    and best_carb_delta
                    <= carb_tolerance_g
            ):
                candidates.append(
                    (
                        time_delta_minutes,
                        best_carb_delta,
                        db_meal,
                        matched_pdf_carbs,
                    )
                )

        if not candidates:
            unmatched.append(
                event
            )

            continue

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1],
            )
        )

        if len(candidates) >= 2:
            first = candidates[0]
            second = candidates[1]

            if (
                abs(
                    first[0]
                    - second[0]
                )
                < 0.01
                and abs(
                    first[1]
                    - second[1]
                )
                < 0.01
            ):
                ambiguous.append(
                    event
                )

                continue

        best = candidates[0][2]
        matched_pdf_carbs = (
            candidates[0][3]
        )

        used_db_ids.add(
            best["id"]
        )

        matched.append(
            {
                "db_meal_id": str(
                    best["id"]
                ),

                "pdf_datetime": (
                    event
                    .local_datetime
                    .isoformat()
                ),

                "db_datetime": (
                    best[
                        "local_datetime"
                    ].isoformat()
                ),

                "time_delta_seconds": abs(
                    (
                        best[
                            "local_datetime"
                        ]
                        - event.local_datetime
                    ).total_seconds()
                ),

                "ocr_carbohydrates_g": (
    event.carbohydrates_g
),

"matched_carbohydrates_g": (
    matched_pdf_carbs
),

"db_carbohydrates_g": (
    best[
        "carbohydrates_g"
    ]
),

                "description": (
                    event.detail
                ),

                "source_file": (
                    event.source_file
                ),

                "source_page": (
                    event.source_page
                ),
            }
        )

    return (
        matched,
        unmatched,
        ambiguous,
    )


def serialize_event(
    event: PdfEvent,
) -> dict:
    data = asdict(
        event
    )

    data["event_date"] = (
        event
        .event_date
        .isoformat()
    )

    data["event_time"] = (
        event
        .event_time
        .strftime(
            "%H:%M"
        )
    )

    data["local_datetime"] = (
        event
        .local_datetime
        .isoformat()
    )

    return data


def print_examples(
    title: str,
    events: list[PdfEvent],
    limit: int = 8,
) -> None:
    print()
    print(title)
    print("-" * 72)

    if not events:
        print("(none)")
        return

    for event in events[:limit]:
        print(
            f"{event.event_date} "
            f"{event.event_time.strftime('%H:%M')} | "
            f"{event.event_type:<8} | "
            f"{event.detail}"
        )


def main() -> None:
    args = parse_args()

    if args.workers < 1:
        raise SystemExit(
            "--workers must be at least 1."
        )

    if not args.pdf_dir.exists():
        raise SystemExit(
            "PDF directory does not exist:\n"
            f"{args.pdf_dir.resolve()}"
        )

    if not args.tessdata_dir.exists():
        raise SystemExit(
            "Tessdata directory does not exist:\n"
            f"{args.tessdata_dir.resolve()}"
        )

    args.cache_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    tesseract = find_tesseract()

    pdf_files = sorted(
        args.pdf_dir.glob(
            "*.pdf"
        ),
        reverse=True,
    )

    if args.max_files is not None:
        pdf_files = pdf_files[
            :args.max_files
        ]

    if not pdf_files:
        raise SystemExit(
            "No PDF files found."
        )

    raw_events: list[
        PdfEvent
    ] = []

    exact_pdf_hashes: set[
        str
    ] = set()

    exact_duplicate_pdfs = 0
    short_non_daily_pdfs = 0

    pages_total = 0
    pages_processed = 0

    actual_ocr_pages = 0
    cache_hits = 0

    pages_without_date = 0
    pages_multi_day = 0
    pages_truncated = 0

    ocr_errors = 0

    print()
    print("=" * 72)
    print(
        "DEXCOM CLARITY PDF OCR DRY RUN - FAST V2"
    )
    print("=" * 72)

    print(
        f"PDF directory:       "
        f"{args.pdf_dir.resolve()}"
    )

    print(
        f"PDF files selected:  "
        f"{len(pdf_files)}"
    )

    print(
        f"Tesseract:           "
        f"{tesseract}"
    )

    print(
        f"Tessdata:            "
        f"{args.tessdata_dir.resolve()}"
    )

    print(
        f"OCR cache:           "
        f"{args.cache_dir.resolve()}"
    )

    print(
        f"Workers:             "
        f"{args.workers}"
    )

    print(
        f"Refresh cache:       "
        f"{'YES' if args.refresh_cache else 'NO'}"
    )

    print()

    with ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        for (
            file_index,
            pdf_file,
        ) in enumerate(
            pdf_files,
            start=1,
        ):
            file_hash = sha256_file(
                pdf_file
            )

            if (
                file_hash
                in exact_pdf_hashes
            ):
                exact_duplicate_pdfs += 1

                print(
                    f"[{file_index}/{len(pdf_files)}] "
                    f"SKIP duplicate: "
                    f"{pdf_file.name}"
                )

                continue

            exact_pdf_hashes.add(
                file_hash
            )

            try:
                document = fitz.open(
                    pdf_file
                )

                page_count = len(
                    document
                )

                document.close()

            except Exception as exc:
                print(
                    f"[{file_index}/{len(pdf_files)}] "
                    f"ERROR open: "
                    f"{pdf_file.name}: {exc}"
                )

                ocr_errors += 1
                continue

            pages_total += (
                page_count
            )

            if page_count <= 3:
                short_non_daily_pdfs += 1

                print(
                    f"[{file_index}/{len(pdf_files)}] "
                    f"SKIP likely overview "
                    f"({page_count} p): "
                    f"{pdf_file.name}"
                )

                continue

            print(
                f"[{file_index}/{len(pdf_files)}] "
                f"PROCESS {page_count:>2} p: "
                f"{pdf_file.name}"
            )

            futures = []

            for page_number in range(
                1,
                page_count + 1,
            ):
                future = executor.submit(
                    ocr_page_with_cache,
                    pdf_file,
                    file_hash,
                    page_number,
                    args.zoom,
                    tesseract,
                    args.tessdata_dir,
                    args.cache_dir,
                    args.refresh_cache,
                )

                futures.append(
                    future
                )

            page_results: list[
                OcrPageResult
            ] = []

            for future in as_completed(
                futures
            ):
                result = future.result()

                page_results.append(
                    result
                )

            page_results.sort(
                key=lambda item: (
                    item.page_number
                )
            )

            file_cache_hits = 0
            file_actual_ocr = 0
            file_errors = 0

            for result in page_results:
                if result.error is not None:
                    ocr_errors += 1
                    file_errors += 1

                    print(
                        f"    page "
                        f"{result.page_number}: "
                        f"OCR ERROR: "
                        f"{result.error}"
                    )

                    continue

                pages_processed += 1

                if result.cache_hit:
                    cache_hits += 1
                    file_cache_hits += 1

                else:
                    actual_ocr_pages += 1
                    file_actual_ocr += 1

                text = result.text

                daily_dates = (
                    extract_daily_dates(
                        text
                    )
                )

                if not daily_dates:
                    pages_without_date += 1
                    continue

                if len(daily_dates) != 1:
                    pages_multi_day += 1
                    continue

                page_date = (
                    daily_dates[0]
                )

                if looks_like_truncated_page(
                    text
                ):
                    pages_truncated += 1

                for line in (
                    text.splitlines()
                ):
                    event = (
                        parse_ocr_event_line(
                            line=line,
                            page_date=(
                                page_date
                            ),
                            source_file=(
                                pdf_file.name
                            ),
                            source_page=(
                                result.page_number
                            ),
                        )
                    )

                    if event is not None:
                        raw_events.append(
                            event
                        )

            print(
                f"    OCR: {file_actual_ocr}, "
                f"cache: {file_cache_hits}, "
                f"errors: {file_errors}"
            )

    (
        events,
        duplicate_events,
    ) = deduplicate_events(
        raw_events
    )

    event_counts = Counter(
        event.event_type
        for event in events
    )

    meals = [
        event
        for event in events
        if event.event_type
        == "MEAL"
    ]

    meal_descriptions = [
        event
        for event in meals
        if event.detail.strip()
    ]

    notes = [
        event
        for event in events
        if event.event_type
        == "NOTE"
    ]

    prebolus_numeric = [
        event
        for event in notes
        if (
            event.prebolus_minutes
            is not None
            and not (
                event.prebolus_explicit_none
            )
        )
    ]

    prebolus_none = [
        event
        for event in notes
        if (
            event
            .prebolus_explicit_none
        )
    ]

    feedback = [
        event
        for event in notes
        if (
            event.feedback_result
            is not None
        )
    ]

    timing_notes = [
        event
        for event in notes
        if (
            "jidle"
            in ascii_text(
                event.detail
            )
            and (
                "pich"
                in ascii_text(
                    event.detail
                )
                or "inzulin"
                in ascii_text(
                    event.detail
                )
            )
        )
    ]

    activities = [
        event
        for event in events
        if event.event_type
        == "ACTIVITY"
    ]

    insulin_events = [
        event
        for event in events
        if event.event_type
        == "INSULIN"
    ]

    rapid_pdf_insulin = [
        event
        for event in insulin_events
        if event.insulin_kind
        == "RAPID"
    ]

    basal_pdf_insulin = [
        event
        for event in insulin_events
        if event.insulin_kind
        == "BASAL"
    ]

    feedback_counts = Counter(
        event.feedback_result
        for event in feedback
    )

    db_meals = (
        load_database_meals(
            args.user_id
        )
    )

    (
        matched_meals,
        unmatched_meals,
        ambiguous_meals,
    ) = (
        match_pdf_meals_to_database(
            pdf_meals=meals,
            db_meals=db_meals,
            window_minutes=(
                args.meal_window_minutes
            ),
            carb_tolerance_g=(
                args.carb_tolerance_g
            ),
        )
    )

    output = {
        "generated_at": (
            datetime.now(
                tz=PRAGUE
            ).isoformat()
        ),

        "user_id": str(
            args.user_id
        ),

        "pdf_directory": str(
            args.pdf_dir.resolve()
        ),

        "ocr": {
            "cache_directory": str(
                args.cache_dir.resolve()
            ),

            "cache_version": (
                OCR_CACHE_VERSION
            ),

            "workers": (
                args.workers
            ),

            "zoom": (
                args.zoom
            ),

            "actual_ocr_pages": (
                actual_ocr_pages
            ),

            "cache_hits": (
                cache_hits
            ),
        },

        "statistics": {
            "pdf_files_selected": (
                len(pdf_files)
            ),

            "exact_duplicate_pdfs": (
                exact_duplicate_pdfs
            ),

            "short_non_daily_pdfs": (
                short_non_daily_pdfs
            ),

            "pages_total": (
                pages_total
            ),

            "pages_processed": (
                pages_processed
            ),

            "pages_without_date": (
                pages_without_date
            ),

            "pages_multi_day": (
                pages_multi_day
            ),

            "pages_truncated": (
                pages_truncated
            ),

            "ocr_errors": (
                ocr_errors
            ),

            "raw_events": (
                len(raw_events)
            ),

            "duplicate_events": (
                duplicate_events
            ),

            "unique_events": (
                len(events)
            ),

            "event_counts": dict(
                event_counts
            ),

            "meals": (
                len(meals)
            ),

            "meal_descriptions": (
                len(
                    meal_descriptions
                )
            ),

            "notes": (
                len(notes)
            ),

            "prebolus_numeric": (
                len(
                    prebolus_numeric
                )
            ),

            "prebolus_none": (
                len(
                    prebolus_none
                )
            ),

            "feedback": (
                len(feedback)
            ),

            "activities": (
                len(activities)
            ),

            "rapid_pdf_insulin": (
                len(
                    rapid_pdf_insulin
                )
            ),

            "basal_pdf_insulin": (
                len(
                    basal_pdf_insulin
                )
            ),

            "db_clarity_meals": (
                len(db_meals)
            ),

            "matched_pdf_meals": (
                len(
                    matched_meals
                )
            ),

            "unmatched_pdf_meals": (
                len(
                    unmatched_meals
                )
            ),

            "ambiguous_pdf_meals": (
                len(
                    ambiguous_meals
                )
            ),
        },

        "feedback_counts": dict(
            feedback_counts
        ),

        "events": [
            serialize_event(
                event
            )
            for event in events
        ],

        "matched_meals": (
            matched_meals
        ),

        "unmatched_meals": [
            serialize_event(
                event
            )
            for event in unmatched_meals
        ],

        "ambiguous_meals": [
            serialize_event(
                event
            )
            for event in ambiguous_meals
        ],
    }

    args.output_json.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output_json.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("RESULTS")
    print("=" * 72)

    print(
        f"Exact duplicate PDFs:   "
        f"{exact_duplicate_pdfs:,}"
    )

    print(
        f"Overview PDFs skipped:  "
        f"{short_non_daily_pdfs:,}"
    )

    print(
        f"Pages total:            "
        f"{pages_total:,}"
    )

    print(
        f"Pages processed:        "
        f"{pages_processed:,}"
    )

    print(
        f"OCR actually executed:  "
        f"{actual_ocr_pages:,}"
    )

    print(
        f"OCR cache hits:         "
        f"{cache_hits:,}"
    )

    print(
        f"Pages without date:     "
        f"{pages_without_date:,}"
    )

    print(
        f"Multi-day pages skipped:"
        f" {pages_multi_day:,}"
    )

    print(
        f"Pages truncated:        "
        f"{pages_truncated:,}"
    )

    print(
        f"OCR errors:             "
        f"{ocr_errors:,}"
    )

    print()

    print(
        f"Raw OCR events:         "
        f"{len(raw_events):,}"
    )

    print(
        f"Duplicate events:       "
        f"{duplicate_events:,}"
    )

    print(
        f"Unique events:          "
        f"{len(events):,}"
    )

    print()
    print("EXTRACTED")
    print("-" * 72)

    print(
        f"Meals:                  "
        f"{len(meals):,}"
    )

    print(
        f"Meals with description: "
        f"{len(meal_descriptions):,}"
    )

    print(
        f"Notes:                  "
        f"{len(notes):,}"
    )

    print(
        f"Prebolus numeric:       "
        f"{len(prebolus_numeric):,}"
    )

    print(
        f"Prebolus none:          "
        f"{len(prebolus_none):,}"
    )

    print(
        f"Feedback total:         "
        f"{len(feedback):,}"
    )

    print(
        f"  TOO_LITTLE:           "
        f"{feedback_counts['TOO_LITTLE']:,}"
    )

    print(
        f"  OK:                   "
        f"{feedback_counts['OK']:,}"
    )

    print(
        f"  TOO_MUCH:             "
        f"{feedback_counts['TOO_MUCH']:,}"
    )

    print(
        f"Timing notes:           "
        f"{len(timing_notes):,}"
    )

    print(
        f"Activities:             "
        f"{len(activities):,}"
    )

    print(
        f"Rapid insulin rows:     "
        f"{len(rapid_pdf_insulin):,}"
    )

    print(
        f"Basal insulin rows:     "
        f"{len(basal_pdf_insulin):,}"
    )

    print()
    print(
        "PDF MEAL -> CLARITY DATABASE MEAL"
    )
    print("-" * 72)

    print(
        f"Clarity DB meals:       "
        f"{len(db_meals):,}"
    )

    print(
        f"Matched:                "
        f"{len(matched_meals):,}"
    )

    print(
        f"Unmatched:              "
        f"{len(unmatched_meals):,}"
    )

    print(
        f"Ambiguous:              "
        f"{len(ambiguous_meals):,}"
    )

    print_examples(
        "MEAL EXAMPLES",
        meal_descriptions,
    )

    print_examples(
        "PREBOLUS EXAMPLES",
        (
            prebolus_numeric
            + prebolus_none
        ),
    )

    print_examples(
        "FEEDBACK EXAMPLES",
        feedback,
    )

    print_examples(
        "ACTIVITY EXAMPLES",
        activities,
    )

    print()
    print(
        f"Private JSON saved to:\n"
        f"{args.output_json.resolve()}"
    )

    print()
    print("DATABASE CHANGED: NO")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()