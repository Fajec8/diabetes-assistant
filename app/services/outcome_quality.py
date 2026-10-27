TARGET_GLUCOSE = 8.0

TARGET_RANGE_MIN = 4.0
TARGET_RANGE_MAX = 10.0

LOW_GLUCOSE_SCORE_CAP = 35.0

HORIZON_WEIGHTS = {
    30: 0.05,
    60: 0.15,
    90: 0.20,
    120: 0.25,
    180: 0.35,
}

TOTAL_HORIZON_WEIGHT = sum(
    HORIZON_WEIGHTS.values()
)


def score_glucose_value(
    glucose: float,
) -> float:
    glucose = float(glucose)

    # Cílové rozmezí 4–10 mmol/l.
    # Ideální hodnota je 8 mmol/l.
    if (
        TARGET_RANGE_MIN
        <= glucose
        <= TARGET_RANGE_MAX
    ):
        score = (
            100.0
            - 10.0
            * abs(
                glucose
                - TARGET_GLUCOSE
            )
        )

        return round(
            max(score, 0.0),
            2,
        )

    # Hypoglykémii penalizujeme výrazně
    # silněji než hyperglykémii.
    if glucose < TARGET_RANGE_MIN:
        score = (
            60.0
            - 40.0
            * (
                TARGET_RANGE_MIN
                - glucose
            )
        )

        return round(
            max(score, 0.0),
            2,
        )

    # Hodnoty nad 10 mmol/l jsou nežádoucí,
    # ale penalizace je mírnější než u hypo.
    score = (
        80.0
        - 10.0
        * (
            glucose
            - TARGET_RANGE_MAX
        )
    )

    return round(
        max(score, 0.0),
        2,
    )


def _status_from_score(
    score: float,
) -> str:
    if score >= 90:
        return "EXCELLENT"

    if score >= 75:
        return "GOOD"

    if score >= 60:
        return "ACCEPTABLE"

    return "POOR"


def _confidence_level(
    confidence: float,
) -> str:
    if confidence >= 80:
        return "HIGH"

    if confidence >= 50:
        return "MEDIUM"

    if confidence > 0:
        return "LOW"

    return "NO_DATA"


def evaluate_outcome_quality(
    outcome: dict,
) -> dict:
    weighted_sum = 0.0
    used_weight = 0.0

    horizon_scores = {}
    glucose_values = {}

    low_detected = False
    high_detected = False

    available_horizons = []

    for (
        minutes,
        weight,
    ) in HORIZON_WEIGHTS.items():
        key = (
            f"glucose_{minutes}m"
        )

        value = outcome.get(
            key
        )

        if value is None:
            horizon_scores[
                minutes
            ] = None

            glucose_values[
                minutes
            ] = None

            continue

        value = float(value)

        glucose_values[
            minutes
        ] = value

        available_horizons.append(
            minutes
        )

        point_score = (
            score_glucose_value(
                value
            )
        )

        horizon_scores[
            minutes
        ] = point_score

        weighted_sum += (
            point_score
            * weight
        )

        used_weight += weight

        if (
            value
            < TARGET_RANGE_MIN
        ):
            low_detected = True

        if (
            value
            > TARGET_RANGE_MAX
        ):
            high_detected = True

    confidence = round(
        (
            used_weight
            / TOTAL_HORIZON_WEIGHT
        )
        * 100.0,
        2,
    )

    confidence_level = (
        _confidence_level(
            confidence
        )
    )

    if used_weight == 0:
        return {
            "quality_score": None,
            "raw_quality_score": None,

            "status": "NO_DATA",

            "confidence":
                0.0,

            "confidence_level":
                "NO_DATA",

            "available_horizons":
                [],

            "target_glucose":
                TARGET_GLUCOSE,

            "target_range": {
                "min":
                    TARGET_RANGE_MIN,
                "max":
                    TARGET_RANGE_MAX,
            },

            "latest_glucose":
                None,

            "latest_horizon_minutes":
                None,

            "distance_from_target":
                None,

            "low_detected":
                False,

            "high_detected":
                False,

            "horizon_scores":
                horizon_scores,

            "glucose_values":
                glucose_values,
        }

    raw_score = round(
        weighted_sum
        / used_weight,
        2,
    )

    quality_score = raw_score

    # Pokud se kdykoliv objeví hodnota
    # pod 4 mmol/l, trajectory nesmí
    # dostat dobré celkové hodnocení.
    if low_detected:
        quality_score = min(
            quality_score,
            LOW_GLUCOSE_SCORE_CAP,
        )

    quality_score = round(
        quality_score,
        2,
    )

    latest_horizon = max(
        available_horizons
    )

    latest_glucose = (
        glucose_values[
            latest_horizon
        ]
    )

    distance_from_target = round(
        abs(
            latest_glucose
            - TARGET_GLUCOSE
        ),
        2,
    )

    return {
        "quality_score":
            quality_score,

        "raw_quality_score":
            raw_score,

        "status":
            _status_from_score(
                quality_score
            ),

        "confidence":
            confidence,

        "confidence_level":
            confidence_level,

        "available_horizons":
            available_horizons,

        "target_glucose":
            TARGET_GLUCOSE,

        "target_range": {
            "min":
                TARGET_RANGE_MIN,
            "max":
                TARGET_RANGE_MAX,
        },

        "latest_glucose":
            latest_glucose,

        "latest_horizon_minutes":
            latest_horizon,

        "distance_from_target":
            distance_from_target,

        "low_detected":
            low_detected,

        "high_detected":
            high_detected,

        "horizon_scores":
            horizon_scores,

        "glucose_values":
            glucose_values,
    }