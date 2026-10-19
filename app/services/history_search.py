from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from math import sqrt
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.activity import Activity
from app.models.glucose import GlucoseReading
from app.models.insulin import InsulinDose
from app.models.meal import Meal
from app.models.user import User

from app.services.evidence import (
    build_evidence,
)
from app.services.meal_bolus_analysis import (
    build_meal_bolus_analysis,
)
from app.services.outcome_interpretation import (
    build_outcome_interpretation,
)
from app.services.outcome_summary import (
    summarize_outcomes,
)
from app.services.similarity import (
    compare_situations,
)
from app.services.situation_builder import (
    ACTIVITY_HISTORY_HOURS,
    CGM_EXPECTED_INTERVAL_MINUTES,
    CGM_QUALITY_WINDOW_MINUTES,
    MAX_GLUCOSE_GAP,
    NOVORAPID_ACTIVE_DURATION_MINUTES,
)
from app.services.situation_outcome import (
    build_situation_outcome,
)


MIN_CANDIDATE_SEPARATION = timedelta(
    hours=4
)

HISTORY_SEARCH_DAYS = 90
HISTORY_SAFETY_HOURS = 6


class _HistorySituationCache:
    def __init__(
        self,
        db: Session,
        user_id,
        search_t0: datetime
    ):
        self.db = db
        self.user_id = user_id
        self.search_t0 = search_t0

        glucose_start = (
            search_t0
            - timedelta(
                days=HISTORY_SEARCH_DAYS,
                hours=2
            )
        )

        activity_start = (
            search_t0
            - timedelta(
                days=HISTORY_SEARCH_DAYS,
                hours=ACTIVITY_HISTORY_HOURS
            )
        )

        # -------------------------------------------------
        # GLUCOSE
        # -------------------------------------------------

        self.glucose_readings = (
            db.scalars(
                select(
                    GlucoseReading
                )
                .where(
                    GlucoseReading.user_id
                    == user_id,

                    GlucoseReading.measured_at
                    >= glucose_start,

                    GlucoseReading.measured_at
                    <= search_t0
                )
                .order_by(
                    GlucoseReading.measured_at
                )
            ).all()
        )

        self.glucose_times = [
            reading.measured_at
            for reading
            in self.glucose_readings
        ]

        # -------------------------------------------------
        # MEALS
        #
        # Meal.items nacitame hromadne.
        #
        # Tim nevznika extra SQL dotaz
        # pri kazdem historickem kandidatovi.
        # -------------------------------------------------

        self.meals = (
            db.scalars(
                select(
                    Meal
                )
                .options(
                    selectinload(
                        Meal.items
                    )
                )
                .where(
                    Meal.user_id
                    == user_id,

                    Meal.eaten_at
                    <= search_t0
                )
                .order_by(
                    Meal.eaten_at
                )
            ).all()
        )

        self.meal_times = [
            meal.eaten_at
            for meal
            in self.meals
        ]

        self.meal_carbs_prefix = (
            self._build_prefix(
                self.meals,
                "carbohydrates_g"
            )
        )

        # -------------------------------------------------
        # INSULIN
        # -------------------------------------------------

        insulin_doses = (
            db.scalars(
                select(
                    InsulinDose
                )
                .where(
                    InsulinDose.user_id
                    == user_id,

                    InsulinDose.administered_at
                    <= search_t0
                )
                .order_by(
                    InsulinDose.administered_at
                )
            ).all()
        )

        self.novorapid_doses = [
            dose
            for dose
            in insulin_doses
            if (
                dose.insulin_type
                == "NOVORAPID"
            )
        ]

        self.tresiba_doses = [
            dose
            for dose
            in insulin_doses
            if (
                dose.insulin_type
                == "TRESIBA"
            )
        ]

        self.novorapid_times = [
            dose.administered_at
            for dose
            in self.novorapid_doses
        ]

        self.tresiba_times = [
            dose.administered_at
            for dose
            in self.tresiba_doses
        ]

        self.novorapid_units_prefix = (
            self._build_prefix(
                self.novorapid_doses,
                "units"
            )
        )

        # -------------------------------------------------
        # NovoRapid davky seskupene podle jidla.
        #
        # Diky tomu muzeme linked bolus sestavit
        # pouze v pameti.
        # -------------------------------------------------

        self.novorapid_doses_by_meal = {}

        for dose in self.novorapid_doses:
            if dose.meal_id is None:
                continue

            self.novorapid_doses_by_meal.setdefault(
                dose.meal_id,
                []
            ).append(
                dose
            )

        # -------------------------------------------------
        # ACTIVITIES
        # -------------------------------------------------

        self.activities = (
            db.scalars(
                select(
                    Activity
                )
                .where(
                    Activity.user_id
                    == user_id,

                    Activity.started_at
                    < search_t0,

                    Activity.ended_at
                    > activity_start
                )
                .order_by(
                    Activity.ended_at
                )
            ).all()
        )

        self.activity_end_times = [
            activity.ended_at
            for activity
            in self.activities
        ]

    @staticmethod
    def _build_prefix(
        rows,
        attribute
    ):
        prefix = [
            0.0
        ]

        running_total = 0.0

        for row in rows:
            value = getattr(
                row,
                attribute
            )

            running_total += float(
                value
            )

            prefix.append(
                running_total
            )

        return prefix

    @staticmethod
    def _sum_window(
        times,
        prefix,
        window_start,
        window_end
    ):
        left = bisect_right(
            times,
            window_start
        )

        right = bisect_right(
            times,
            window_end
        )

        return float(
            prefix[right]
            - prefix[left]
        )

    # -----------------------------------------------------
    # GLUCOSE
    # -----------------------------------------------------

    def _latest_glucose(
        self,
        timestamp
    ):
        index = (
            bisect_right(
                self.glucose_times,
                timestamp
            )
            - 1
        )

        if index < 0:
            return None

        reading = (
            self.glucose_readings[
                index
            ]
        )

        if (
            timestamp
            - reading.measured_at
            > MAX_GLUCOSE_GAP
        ):
            return None

        return reading

    def _glucose_delta(
        self,
        t0,
        minutes
    ):
        current = (
            self._latest_glucose(
                t0
            )
        )

        previous = (
            self._latest_glucose(
                t0
                - timedelta(
                    minutes=minutes
                )
            )
        )

        if (
            current is None
            or previous is None
        ):
            return None

        return round(
            current.value_mmol_l
            - previous.value_mmol_l,
            2
        )

    def _glucose_data_quality(
        self,
        t0
    ):
        window_start = (
            t0
            - timedelta(
                minutes=
                    CGM_QUALITY_WINDOW_MINUTES
            )
        )

        left = bisect_left(
            self.glucose_times,
            window_start
        )

        right = bisect_right(
            self.glucose_times,
            t0
        )

        readings = (
            self.glucose_readings[
                left:right
            ]
        )

        expected_readings = (
            CGM_QUALITY_WINDOW_MINUTES
            // CGM_EXPECTED_INTERVAL_MINUTES
            + 1
        )

        actual_readings = len(
            readings
        )

        coverage_percent = min(
            actual_readings
            / expected_readings
            * 100,
            100.0
        )

        if not readings:
            max_gap_minutes = float(
                CGM_QUALITY_WINDOW_MINUTES
            )

        else:
            timestamps = [
                window_start
            ]

            timestamps.extend(
                reading.measured_at
                for reading
                in readings
            )

            timestamps.append(
                t0
            )

            max_gap_minutes = 0.0

            for index in range(
                len(
                    timestamps
                ) - 1
            ):
                gap = (
                    timestamps[
                        index + 1
                    ]
                    - timestamps[
                        index
                    ]
                ).total_seconds() / 60

                max_gap_minutes = max(
                    max_gap_minutes,
                    gap
                )

        return {
            "window_minutes":
                CGM_QUALITY_WINDOW_MINUTES,

            "expected_interval_minutes":
                CGM_EXPECTED_INTERVAL_MINUTES,

            "expected_readings":
                expected_readings,

            "actual_readings":
                actual_readings,

            "coverage_percent":
                round(
                    coverage_percent,
                    1
                ),

            "max_gap_minutes":
                round(
                    max_gap_minutes,
                    1
                )
        }

    # -----------------------------------------------------
    # MEALS
    # -----------------------------------------------------

    def _last_meal(
        self,
        t0
    ):
        index = (
            bisect_right(
                self.meal_times,
                t0
            )
            - 1
        )

        if index < 0:
            return None

        return self.meals[
            index
        ]

    def _sum_carbs(
        self,
        t0,
        hours
    ):
        return (
            self._sum_window(
                times=
                    self.meal_times,

                prefix=
                    self.meal_carbs_prefix,

                window_start=(
                    t0
                    - timedelta(
                        hours=hours
                    )
                ),

                window_end=t0
            )
        )

    @staticmethod
    def _meal_items(
        meal
    ):
        if meal is None:
            return []

        return [
            {
                "id":
                    item.id,

                "food_name":
                    item.food_name,

                "preparation":
                    item.preparation,

                "variant":
                    item.variant,

                "amount_g":
                    item.amount_g,

                "carbohydrates_g":
                    item.carbohydrates_g,

                "note":
                    item.note
            }
            for item
            in meal.items
        ]

    def _linked_meal_bolus(
        self,
        meal,
        t0
    ):
        if meal is None:
            return None

        doses = (
            self.novorapid_doses_by_meal.get(
                meal.id,
                []
            )
        )

        # build_meal_bolus_analysis umi filtrovat
        # davky podle as_of=t0.
        #
        # Davka z budoucnosti se tak nikdy
        # nedostane do historicke Situation.
        return (
            build_meal_bolus_analysis(
                meal=meal,
                doses=doses,
                as_of=t0
            )
        )

    # -----------------------------------------------------
    # NOVORAPID
    # -----------------------------------------------------

    def _last_novorapid(
        self,
        t0
    ):
        index = (
            bisect_right(
                self.novorapid_times,
                t0
            )
            - 1
        )

        if index < 0:
            return None

        return self.novorapid_doses[
            index
        ]

    def _sum_novorapid(
        self,
        t0,
        hours
    ):
        return (
            self._sum_window(
                times=
                    self.novorapid_times,

                prefix=
                    self.novorapid_units_prefix,

                window_start=(
                    t0
                    - timedelta(
                        hours=hours
                    )
                ),

                window_end=t0
            )
        )

    def _estimate_active_novorapid(
        self,
        t0
    ):
        window_start = (
            t0
            - timedelta(
                minutes=
                    NOVORAPID_ACTIVE_DURATION_MINUTES
            )
        )

        left = bisect_right(
            self.novorapid_times,
            window_start
        )

        right = bisect_right(
            self.novorapid_times,
            t0
        )

        active_units = 0.0

        for dose in (
            self.novorapid_doses[
                left:right
            ]
        ):
            minutes_since_dose = (
                t0
                - dose.administered_at
            ).total_seconds() / 60

            if (
                minutes_since_dose
                < 0
                or minutes_since_dose
                >= NOVORAPID_ACTIVE_DURATION_MINUTES
            ):
                continue

            remaining_fraction = (
                1.0
                - (
                    minutes_since_dose
                    / NOVORAPID_ACTIVE_DURATION_MINUTES
                )
            )

            active_units += (
                dose.units
                * remaining_fraction
            )

        return round(
            active_units,
            2
        )

    # -----------------------------------------------------
    # TRESIBA
    # -----------------------------------------------------

    def _last_tresiba(
        self,
        t0
    ):
        index = (
            bisect_right(
                self.tresiba_times,
                t0
            )
            - 1
        )

        if index < 0:
            return None

        return self.tresiba_doses[
            index
        ]

    # -----------------------------------------------------
    # ACTIVITY
    # -----------------------------------------------------

    def _last_activity(
        self,
        t0
    ):
        index = (
            bisect_right(
                self.activity_end_times,
                t0
            )
            - 1
        )

        if index < 0:
            return None

        activity = (
            self.activities[
                index
            ]
        )

        history_start = (
            t0
            - timedelta(
                hours=
                    ACTIVITY_HISTORY_HOURS
            )
        )

        if (
            activity.ended_at
            <= history_start
        ):
            return None

        return activity

    def _activity_minutes_in_window(
        self,
        t0,
        older_hours,
        newer_hours
    ):
        window_start = (
            t0
            - timedelta(
                hours=older_hours
            )
        )

        window_end = (
            t0
            - timedelta(
                hours=newer_hours
            )
        )

        total_minutes = 0.0

        for activity in self.activities:
            if (
                activity.started_at
                >= window_end
            ):
                continue

            if (
                activity.ended_at
                <= window_start
            ):
                continue

            overlap_start = max(
                activity.started_at,
                window_start
            )

            overlap_end = min(
                activity.ended_at,
                window_end
            )

            if (
                overlap_end
                > overlap_start
            ):
                total_minutes += (
                    overlap_end
                    - overlap_start
                ).total_seconds() / 60

        return round(
            total_minutes
        )

    # -----------------------------------------------------
    # SITUATION
    # -----------------------------------------------------

    def build_situation(
        self,
        t0,
        timezone
    ):
        local_t0 = (
            t0.astimezone(
                timezone
            )
        )

        current_glucose = (
            self._latest_glucose(
                t0
            )
        )

        last_meal = (
            self._last_meal(
                t0
            )
        )

        last_meal_bolus = (
            self._linked_meal_bolus(
                last_meal,
                t0
            )
        )

        last_bolus = (
            self._last_novorapid(
                t0
            )
        )

        last_basal = (
            self._last_tresiba(
                t0
            )
        )

        last_activity = (
            self._last_activity(
                t0
            )
        )

        return {
            "timestamp":
                local_t0.isoformat(),

            "glucose": {
                "current": (
                    current_glucose.value_mmol_l
                    if current_glucose
                    else None
                ),

                "delta_15m":
                    self._glucose_delta(
                        t0,
                        15
                    ),

                "delta_30m":
                    self._glucose_delta(
                        t0,
                        30
                    ),

                "delta_60m":
                    self._glucose_delta(
                        t0,
                        60
                    ),

                "data_quality":
                    self._glucose_data_quality(
                        t0
                    )
            },

            "meal": {
                # -----------------------------------------
                # Puvodni features pouzivane similarity.
                # -----------------------------------------

                "last_meal_carbs": (
                    last_meal.carbohydrates_g
                    if last_meal
                    else None
                ),

                "minutes_since_last_meal": (
                    round(
                        (
                            t0
                            - last_meal.eaten_at
                        ).total_seconds()
                        / 60
                    )
                    if last_meal
                    else None
                ),

                "carbs_last_2h":
                    self._sum_carbs(
                        t0,
                        2
                    ),

                "carbs_last_4h":
                    self._sum_carbs(
                        t0,
                        4
                    ),

                # -----------------------------------------
                # Nove kontextove informace.
                #
                # Zatim nevstupuji do similarity score.
                # -----------------------------------------

                "last_meal_id": (
                    last_meal.id
                    if last_meal
                    else None
                ),

                "last_meal_description": (
                    last_meal.description
                    if last_meal
                    else None
                ),

                "last_meal_note": (
                    last_meal.note
                    if last_meal
                    else None
                ),

                "items":
                    self._meal_items(
                        last_meal
                    ),

                "linked_bolus":
                    last_meal_bolus
            },

            "novorapid": {
                "last_bolus_units": (
                    last_bolus.units
                    if last_bolus
                    else None
                ),

                "minutes_since_last_bolus": (
                    round(
                        (
                            t0
                            - last_bolus.administered_at
                        ).total_seconds()
                        / 60
                    )
                    if last_bolus
                    else None
                ),

                "units_last_2h":
                    self._sum_novorapid(
                        t0,
                        2
                    ),

                "units_last_4h":
                    self._sum_novorapid(
                        t0,
                        4
                    ),

                "units_last_6h":
                    self._sum_novorapid(
                        t0,
                        6
                    ),

                "estimated_active_units":
                    self._estimate_active_novorapid(
                        t0
                    ),

                "active_duration_minutes":
                    NOVORAPID_ACTIVE_DURATION_MINUTES
            },

            "activity": {
                "type": (
                    last_activity.activity_type
                    if last_activity
                    else None
                ),

                "intensity": (
                    last_activity.intensity
                    if last_activity
                    else None
                ),

                "duration_minutes": (
                    round(
                        (
                            last_activity.ended_at
                            - last_activity.started_at
                        ).total_seconds()
                        / 60
                    )
                    if last_activity
                    else None
                ),

                "minutes_since_end": (
                    round(
                        (
                            t0
                            - last_activity.ended_at
                        ).total_seconds()
                        / 60
                    )
                    if last_activity
                    else None
                ),

                "minutes_last_6h":
                    self._activity_minutes_in_window(
                        t0=t0,
                        older_hours=6,
                        newer_hours=0
                    ),

                "minutes_6_24h":
                    self._activity_minutes_in_window(
                        t0=t0,
                        older_hours=24,
                        newer_hours=6
                    ),

                "minutes_24_48h":
                    self._activity_minutes_in_window(
                        t0=t0,
                        older_hours=48,
                        newer_hours=24
                    ),

                "history_window_hours":
                    ACTIVITY_HISTORY_HOURS
            },

            "tresiba": {
                "last_basal_units": (
                    last_basal.units
                    if last_basal
                    else None
                ),

                "minutes_since_last_basal": (
                    round(
                        (
                            t0
                            - last_basal.administered_at
                        ).total_seconds()
                        / 60
                    )
                    if last_basal
                    else None
                )
            },

            "time": {
                "hour":
                    local_t0.hour,

                "minute":
                    local_t0.minute,

                "minutes_from_midnight": (
                    local_t0.hour * 60
                    + local_t0.minute
                )
            }
        }


def calculate_ranking_score(
    similarity_score,
    data_coverage
):
    coverage_factor = sqrt(
        data_coverage
        / 100
    )

    return round(
        similarity_score
        * coverage_factor,
        1
    )


def select_diverse_candidates(
    candidates,
    limit=10
):
    selected = []

    candidates = sorted(
        candidates,
        key=lambda item:
            item[
                "ranking_score"
            ],
        reverse=True
    )

    for candidate in candidates:
        candidate_time = (
            datetime.fromisoformat(
                candidate[
                    "timestamp"
                ]
            )
        )

        too_close = False

        for selected_item in selected:
            selected_time = (
                datetime.fromisoformat(
                    selected_item[
                        "timestamp"
                    ]
                )
            )

            difference = abs(
                candidate_time
                - selected_time
            )

            if (
                difference
                < MIN_CANDIDATE_SEPARATION
            ):
                too_close = True
                break

        if too_close:
            continue

        selected.append(
            candidate
        )

        if (
            len(
                selected
            )
            >= limit
        ):
            break

    return selected


def find_similar_situations(
    db: Session,
    user_id,
    t0,
    limit=10
):
    user = db.get(
        User,
        user_id
    )

    if user is None:
        raise ValueError(
            "User not found"
        )

    timezone = ZoneInfo(
        user.timezone
    )

    cache = (
        _HistorySituationCache(
            db=db,
            user_id=user_id,
            search_t0=t0
        )
    )

    current = (
        cache.build_situation(
            t0=t0,
            timezone=timezone
        )
    )

    current_local_date = (
        t0
        .astimezone(
            timezone
        )
        .date()
    )

    candidate_start = (
        t0
        - timedelta(
            days=
                HISTORY_SEARCH_DAYS
        )
    )

    candidate_end = (
        t0
        - timedelta(
            hours=
                HISTORY_SAFETY_HOURS
        )
    )

    candidates = []

    for reading in (
        cache.glucose_readings
    ):
        if (
            reading.measured_at
            < candidate_start
        ):
            continue

        if (
            reading.measured_at
            >= candidate_end
        ):
            continue

        local_time = (
            reading.measured_at
            .astimezone(
                timezone
            )
        )

        if (
            local_time.minute
            % 15
            != 0
        ):
            continue

        if (
            local_time.date()
            == current_local_date
        ):
            continue

        historical = (
            cache.build_situation(
                t0=
                    reading.measured_at,

                timezone=
                    timezone
            )
        )

        result = (
            compare_situations(
                current,
                historical
            )
        )

        ranking_score = (
            calculate_ranking_score(
                result[
                    "similarity_score"
                ],

                result[
                    "data_coverage"
                ]
            )
        )

        candidates.append({
            "timestamp":
                local_time.isoformat(),

            "similarity_score":
                result[
                    "similarity_score"
                ],

            "data_coverage":
                result[
                    "data_coverage"
                ],

            "ranking_score":
                ranking_score,

            "components":
                result[
                    "components"
                ],

            "component_coverage":
                result[
                    "component_coverage"
                ]
        })

    top_results = (
        select_diverse_candidates(
            candidates,
            limit=limit
        )
    )

    for item in top_results:
        historical_t0 = (
            datetime.fromisoformat(
                item[
                    "timestamp"
                ]
            )
        )

        item[
            "outcome"
        ] = (
            build_situation_outcome(
                db=db,
                user_id=user_id,
                t0=historical_t0
            )
        )

    evidence = (
        build_evidence(
            top_results
        )
    )

    outcome_summary = (
        summarize_outcomes(
            top_results
        )
    )

    outcome_interpretation = (
        build_outcome_interpretation(
            outcome_summary
        )
    )

    return {
        "current_timestamp": (
            t0
            .astimezone(
                timezone
            )
            .isoformat()
        ),

        "candidate_count":
            len(
                candidates
            ),

        "found":
            len(
                top_results
            ),

        "evidence":
            evidence,

        "outcome_summary":
            outcome_summary,

        "outcome_interpretation":
            outcome_interpretation,

        "similar_situations":
            top_results
    }