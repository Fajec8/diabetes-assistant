from statistics import median, quantiles


STABLE_DELTA_THRESHOLD = 0.2

OUTCOME_KEYS = [
    "delta_30m",
    "delta_60m",
    "delta_90m",
    "delta_120m",
    "delta_180m"
]


def _direction_summary(
    values
):
    decreased = 0
    stable = 0
    increased = 0

    for value in values:
        if (
            value
            < -STABLE_DELTA_THRESHOLD
        ):
            decreased += 1

        elif (
            value
            > STABLE_DELTA_THRESHOLD
        ):
            increased += 1

        else:
            stable += 1

    return {
        "decreased":
            decreased,

        "stable":
            stable,

        "increased":
            increased
    }


def _weighted_mean(
    weighted_values
):
    if not weighted_values:
        return None

    weighted_sum = 0.0
    total_weight = 0.0

    for value, weight in weighted_values:
        weight = max(
            float(weight),
            0.0
        )

        weighted_sum += (
            value
            * weight
        )

        total_weight += weight

    if total_weight == 0:
        normal_mean = (
            sum(
                value
                for value, _
                in weighted_values
            )
            / len(
                weighted_values
            )
        )

        return round(
            normal_mean,
            2
        )

    return round(
        weighted_sum
        / total_weight,
        2
    )


def _summarize(
    weighted_values
):
    available = [
        (
            value,
            weight
        )
        for value, weight
        in weighted_values
        if value is not None
    ]

    values = [
        value
        for value, _
        in available
    ]

    if not values:
        return {
            "count": 0,
            "median": None,
            "weighted_mean": None,
            "q1": None,
            "q3": None,

            "direction": {
                "decreased": 0,
                "stable": 0,
                "increased": 0
            }
        }

    result = {
        "count":
            len(values),

        "median":
            round(
                median(values),
                2
            ),

        "weighted_mean":
            _weighted_mean(
                available
            ),

        "q1":
            None,

        "q3":
            None,

        "direction":
            _direction_summary(
                values
            )
    }

    if len(values) >= 2:
        quartiles = quantiles(
            values,
            n=4,
            method="inclusive"
        )

        result["q1"] = round(
            quartiles[0],
            2
        )

        result["q3"] = round(
            quartiles[2],
            2
        )

    return result


def summarize_outcomes(
    items
):
    collected = {
        key: []
        for key
        in OUTCOME_KEYS
    }

    for item in items:
        outcome = item.get(
            "outcome"
        )

        if outcome is None:
            continue

        ranking_score = item.get(
            "ranking_score",
            1.0
        )

        if ranking_score is None:
            ranking_score = 1.0

        for key in OUTCOME_KEYS:
            collected[key].append(
                (
                    outcome.get(
                        key
                    ),
                    ranking_score
                )
            )

    result = {
        "stable_threshold":
            STABLE_DELTA_THRESHOLD
    }

    for key in OUTCOME_KEYS:
        result[key] = (
            _summarize(
                collected[key]
            )
        )

    return result