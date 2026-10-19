def _numeric_similarity(
    a,
    b,
    scale
):
    if a is None or b is None:
        return None

    difference = abs(
        a - b
    )

    return max(
        0.0,
        1.0 - difference / scale
    )


def _categorical_similarity(
    a,
    b
):
    if a is None or b is None:
        return None

    return (
        1.0
        if a == b
        else 0.0
    )


def _activity_intensity_similarity(
    a,
    b
):
    if a is None or b is None:
        return None

    intensity_values = {
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3
    }

    value_a = (
        intensity_values.get(a)
    )

    value_b = (
        intensity_values.get(b)
    )

    if (
        value_a is None
        or value_b is None
    ):
        return None

    return _numeric_similarity(
        value_a,
        value_b,
        2.0
    )


def _average_with_coverage(
    values
):
    available = [
        value
        for value in values
        if value is not None
    ]

    if not available:
        return None, 0.0

    score = (
        sum(available)
        / len(available)
    )

    coverage = (
        len(available)
        / len(values)
    )

    return (
        score,
        coverage
    )


def _weighted_score_with_coverage(
    parts
):
    weighted_sum = 0.0
    used_weight = 0.0
    total_weight = 0.0

    for (
        score,
        coverage,
        weight
    ) in parts:
        total_weight += weight

        if score is None:
            continue

        effective_weight = (
            weight
            * coverage
        )

        weighted_sum += (
            score
            * effective_weight
        )

        used_weight += (
            effective_weight
        )

    if used_weight == 0:
        return None, 0.0

    score = (
        weighted_sum
        / used_weight
    )

    coverage = (
        used_weight
        / total_weight
        if total_weight > 0
        else 0.0
    )

    return (
        score,
        coverage
    )


def _time_similarity(
    minutes_a,
    minutes_b
):
    if (
        minutes_a is None
        or minutes_b is None
    ):
        return None

    difference = abs(
        minutes_a
        - minutes_b
    )

    difference = min(
        difference,
        1440 - difference
    )

    return max(
        0.0,
        1.0 - difference / 360
    )


def _gap_quality_factor(
    max_gap_minutes
):
    if max_gap_minutes is None:
        return 1.0

    if max_gap_minutes <= 10:
        return 1.0

    if max_gap_minutes >= 60:
        return 0.0

    return (
        1.0
        - (
            max_gap_minutes - 10
        ) / 50
    )


def _glucose_quality_factor(
    situation
):
    quality = (
        situation
        .get(
            "glucose",
            {}
        )
        .get(
            "data_quality"
        )
    )

    if quality is None:
        return 1.0

    coverage_percent = (
        quality.get(
            "coverage_percent"
        )
    )

    max_gap_minutes = (
        quality.get(
            "max_gap_minutes"
        )
    )

    coverage_factor = (
        coverage_percent / 100
        if coverage_percent is not None
        else 1.0
    )

    coverage_factor = max(
        0.0,
        min(
            coverage_factor,
            1.0
        )
    )

    gap_factor = (
        _gap_quality_factor(
            max_gap_minutes
        )
    )

    return min(
        coverage_factor,
        gap_factor
    )


def compare_situations(
    a,
    b
):
    (
        glucose_score,
        glucose_field_coverage
    ) = _average_with_coverage([
        _numeric_similarity(
            a["glucose"]["current"],
            b["glucose"]["current"],
            5.0
        ),

        _numeric_similarity(
            a["glucose"]["delta_15m"],
            b["glucose"]["delta_15m"],
            3.0
        ),

        _numeric_similarity(
            a["glucose"]["delta_30m"],
            b["glucose"]["delta_30m"],
            3.0
        ),

        _numeric_similarity(
            a["glucose"]["delta_60m"],
            b["glucose"]["delta_60m"],
            4.0
        )
    ])

    glucose_quality = min(
        _glucose_quality_factor(a),
        _glucose_quality_factor(b)
    )

    glucose_coverage = (
        glucose_field_coverage
        * glucose_quality
    )

    (
        meal_score,
        meal_coverage
    ) = _average_with_coverage([
        _numeric_similarity(
            a["meal"]["last_meal_carbs"],
            b["meal"]["last_meal_carbs"],
            60.0
        ),

        _numeric_similarity(
            a["meal"]["minutes_since_last_meal"],
            b["meal"]["minutes_since_last_meal"],
            120.0
        ),

        _numeric_similarity(
            a["meal"]["carbs_last_2h"],
            b["meal"]["carbs_last_2h"],
            80.0
        ),

        _numeric_similarity(
            a["meal"]["carbs_last_4h"],
            b["meal"]["carbs_last_4h"],
            100.0
        )
    ])

    (
        novorapid_score,
        novorapid_coverage
    ) = _average_with_coverage([
        _numeric_similarity(
            a["novorapid"]["last_bolus_units"],
            b["novorapid"]["last_bolus_units"],
            6.0
        ),

        _numeric_similarity(
            a["novorapid"]["minutes_since_last_bolus"],
            b["novorapid"]["minutes_since_last_bolus"],
            120.0
        ),

        _numeric_similarity(
            a["novorapid"]["units_last_2h"],
            b["novorapid"]["units_last_2h"],
            8.0
        ),

        _numeric_similarity(
            a["novorapid"]["units_last_4h"],
            b["novorapid"]["units_last_4h"],
            10.0
        ),

        _numeric_similarity(
            a["novorapid"]["units_last_6h"],
            b["novorapid"]["units_last_6h"],
            12.0
        ),

        _numeric_similarity(
            a["novorapid"]["estimated_active_units"],
            b["novorapid"]["estimated_active_units"],
            5.0
        )
    ])

    (
        recent_activity_score,
        recent_activity_coverage
    ) = _average_with_coverage([
        _categorical_similarity(
            a["activity"]["type"],
            b["activity"]["type"]
        ),

        _activity_intensity_similarity(
            a["activity"]["intensity"],
            b["activity"]["intensity"]
        ),

        _numeric_similarity(
            a["activity"]["duration_minutes"],
            b["activity"]["duration_minutes"],
            120.0
        ),

        _numeric_similarity(
            a["activity"]["minutes_since_end"],
            b["activity"]["minutes_since_end"],
            180.0
        ),

        _numeric_similarity(
            a["activity"]["minutes_last_6h"],
            b["activity"]["minutes_last_6h"],
            180.0
        )
    ])

    activity_6_24h_score = (
        _numeric_similarity(
            a["activity"].get(
                "minutes_6_24h"
            ),
            b["activity"].get(
                "minutes_6_24h"
            ),
            240.0
        )
    )

    activity_24_48h_score = (
        _numeric_similarity(
            a["activity"].get(
                "minutes_24_48h"
            ),
            b["activity"].get(
                "minutes_24_48h"
            ),
            240.0
        )
    )

    (
        activity_score,
        activity_coverage
    ) = _weighted_score_with_coverage([
        (
            recent_activity_score,
            recent_activity_coverage,
            0.70
        ),

        (
            activity_6_24h_score,
            (
                1.0
                if activity_6_24h_score
                is not None
                else 0.0
            ),
            0.20
        ),

        (
            activity_24_48h_score,
            (
                1.0
                if activity_24_48h_score
                is not None
                else 0.0
            ),
            0.10
        )
    ])

    (
        tresiba_score,
        tresiba_coverage
    ) = _average_with_coverage([
        _numeric_similarity(
            a["tresiba"]["last_basal_units"],
            b["tresiba"]["last_basal_units"],
            10.0
        ),

        _numeric_similarity(
            a["tresiba"]["minutes_since_last_basal"],
            b["tresiba"]["minutes_since_last_basal"],
            720.0
        )
    ])

    time_score = (
        _time_similarity(
            a["time"][
                "minutes_from_midnight"
            ],
            b["time"][
                "minutes_from_midnight"
            ]
        )
    )

    time_coverage = (
        1.0
        if time_score is not None
        else 0.0
    )

    components = {
        "glucose":
            glucose_score,

        "meal":
            meal_score,

        "novorapid":
            novorapid_score,

        "activity":
            activity_score,

        "tresiba":
            tresiba_score,

        "time":
            time_score
    }

    component_coverage = {
        "glucose":
            glucose_coverage,

        "meal":
            meal_coverage,

        "novorapid":
            novorapid_coverage,

        "activity":
            activity_coverage,

        "tresiba":
            tresiba_coverage,

        "time":
            time_coverage
    }

    weights = {
        "glucose": 0.25,
        "meal": 0.15,
        "novorapid": 0.20,
        "activity": 0.10,
        "tresiba": 0.05,
        "time": 0.25
    }

    weighted_sum = 0.0
    used_weight = 0.0

    for (
        name,
        score
    ) in components.items():
        if score is None:
            continue

        effective_weight = (
            weights[name]
            * component_coverage[name]
        )

        weighted_sum += (
            score
            * effective_weight
        )

        used_weight += (
            effective_weight
        )

    overall = (
        weighted_sum
        / used_weight
        if used_weight > 0
        else 0.0
    )

    total_weight = sum(
        weights.values()
    )

    coverage = (
        used_weight
        / total_weight
        if total_weight > 0
        else 0.0
    )

    return {
        "similarity_score":
            round(
                overall * 100,
                1
            ),

        "data_coverage":
            round(
                coverage * 100,
                1
            ),

        "components": {
            name: (
                round(
                    score * 100,
                    1
                )
                if score is not None
                else None
            )
            for (
                name,
                score
            ) in components.items()
        },

        "component_coverage": {
            name:
                round(
                    value * 100,
                    1
                )
            for (
                name,
                value
            ) in component_coverage.items()
        }
    }