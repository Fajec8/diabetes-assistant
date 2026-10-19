HORIZONS = {
    "30m": {
        "summary_key":
            "delta_30m",

        "minutes":
            30
    },

    "60m": {
        "summary_key":
            "delta_60m",

        "minutes":
            60
    },

    "90m": {
        "summary_key":
            "delta_90m",

        "minutes":
            90
    },

    "120m": {
        "summary_key":
            "delta_120m",

        "minutes":
            120
    },

    "180m": {
        "summary_key":
            "delta_180m",

        "minutes":
            180
    }
}


DIRECTION_LABELS = {
    "decreased":
        "klesla",

    "stable":
        "zůstala přibližně stabilní",

    "increased":
        "vzrostla"
}


def _format_delta(
    value
):
    if value is None:
        return None

    return f"{value:+.2f}"


def _interpret_horizon(
    summary,
    minutes
):
    count = summary.get(
        "count",
        0
    )

    median_delta = summary.get(
        "median"
    )

    weighted_mean = summary.get(
        "weighted_mean"
    )

    direction = summary.get(
        "direction",
        {}
    )

    decreased = direction.get(
        "decreased",
        0
    )

    stable = direction.get(
        "stable",
        0
    )

    increased = direction.get(
        "increased",
        0
    )

    if count == 0:
        return {
            "horizon_minutes":
                minutes,

            "sample_size":
                0,

            "dominant_direction":
                None,

            "dominant_count":
                0,

            "dominant_share_percent":
                None,

            "pattern_strength":
                "NO_DATA",

            "median_delta":
                None,

            "weighted_mean_delta":
                None,

            "text": (
                "Pro tento časový horizont nejsou "
                "dostupná historická data."
            )
        }

    counts = {
        "decreased":
            decreased,

        "stable":
            stable,

        "increased":
            increased
    }

    highest_count = max(
        counts.values()
    )

    winners = [
        name
        for name, value
        in counts.items()
        if value == highest_count
    ]

    dominant_share = round(
        highest_count
        / count
        * 100,
        1
    )

    if len(winners) > 1:
        dominant_direction = (
            "mixed"
        )

        pattern_strength = (
            "MIXED"
        )

        text = (
            f"Historické výsledky za "
            f"{minutes} minut byly smíšené. "
            f"Pokles: {decreased} z {count}, "
            f"stabilní: {stable} z {count}, "
            f"růst: {increased} z {count}."
        )

    else:
        dominant_direction = (
            winners[0]
        )

        if dominant_share >= 70:
            pattern_strength = (
                "STRONG"
            )

        elif dominant_share >= 50:
            pattern_strength = (
                "MODERATE"
            )

        else:
            pattern_strength = (
                "MIXED"
            )

        direction_label = (
            DIRECTION_LABELS[
                dominant_direction
            ]
        )

        median_text = (
            _format_delta(
                median_delta
            )
        )

        text = (
            f"V podobných historických situacích "
            f"za {minutes} minut nejčastěji "
            f"glykémie {direction_label}: "
            f"{highest_count} z {count} případů."
        )

        if median_text is not None:
            text += (
                f" Medián změny byl "
                f"{median_text} mmol/l."
            )

    return {
        "horizon_minutes":
            minutes,

        "sample_size":
            count,

        "dominant_direction":
            dominant_direction,

        "dominant_count":
            highest_count,

        "dominant_share_percent":
            dominant_share,

        "pattern_strength":
            pattern_strength,

        "median_delta":
            median_delta,

        "weighted_mean_delta":
            weighted_mean,

        "text":
            text
    }


def build_outcome_interpretation(
    outcome_summary
):
    result = {}

    for name, config in HORIZONS.items():
        summary = outcome_summary.get(
            config["summary_key"],
            {}
        )

        result[name] = (
            _interpret_horizon(
                summary,
                config["minutes"]
            )
        )

    return result