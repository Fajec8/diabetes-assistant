from __future__ import annotations

from math import floor


DEFAULT_MIN_EVIDENCE_SCORE = 40.0
DEFAULT_MIN_SUPPORT_CASES = 2
DEFAULT_DOSE_STEP = 0.5


def _round_to_step(
    value: float,
    step: float,
) -> float:
    if step <= 0:
        raise ValueError(
            "step must be > 0"
        )

    rounded = (
        floor(
            value / step + 0.5
        )
        * step
    )

    return round(
        rounded,
        2,
    )


def _weighted_mean(
    cases: list[dict],
) -> float:
    total_weight = sum(
        case["evidence_score"]
        for case in cases
    )

    if total_weight <= 0:
        raise ValueError(
            "Total evidence weight must be > 0"
        )

    weighted_sum = sum(
        case["dose_units"]
        * case["evidence_score"]
        for case in cases
    )

    return (
        weighted_sum
        / total_weight
    )


def _weighted_median(
    cases: list[dict],
) -> float:
    ordered = sorted(
        cases,
        key=lambda case:
            case["dose_units"],
    )

    total_weight = sum(
        case["evidence_score"]
        for case in ordered
    )

    if total_weight <= 0:
        raise ValueError(
            "Total evidence weight must be > 0"
        )

    threshold = (
        total_weight / 2.0
    )

    cumulative = 0.0

    for case in ordered:
        cumulative += (
            case["evidence_score"]
        )

        if cumulative >= threshold:
            return float(
                case["dose_units"]
            )

    return float(
        ordered[-1]["dose_units"]
    )


def estimate_research_action(
    cases: list[dict],
    min_evidence_score: float = (
        DEFAULT_MIN_EVIDENCE_SCORE
    ),
    min_support_cases: int = (
        DEFAULT_MIN_SUPPORT_CASES
    ),
    dose_step: float = (
        DEFAULT_DOSE_STEP
    ),
) -> dict:
    usable = []

    for case in cases:
        dose = case.get(
            "dose_units"
        )

        evidence = case.get(
            "evidence_score"
        )

        if (
            dose is None
            or evidence is None
        ):
            continue

        dose = float(
            dose
        )

        evidence = float(
            evidence
        )

        if evidence < min_evidence_score:
            continue

        if evidence <= 0:
            continue

        usable.append(
            {
                "dose_units":
                    dose,
                "evidence_score":
                    evidence,
            }
        )

    if len(usable) < min_support_cases:
        return {
            "status":
                "ABSTAIN",

            "estimated_units":
                None,

            "weighted_median_units":
                None,

            "weighted_mean_units":
                None,

            "support_count":
                len(usable),

            "total_evidence":
                round(
                    sum(
                        item[
                            "evidence_score"
                        ]
                        for item in usable
                    ),
                    2,
                ),

            "min_evidence_score":
                min_evidence_score,

            "min_support_cases":
                min_support_cases,
        }

    weighted_median = (
        _weighted_median(
            usable
        )
    )

    weighted_mean = (
        _weighted_mean(
            usable
        )
    )

    estimated_units = (
        _round_to_step(
            weighted_median,
            dose_step,
        )
    )

    return {
        "status":
            "ESTIMATED",

        "estimated_units":
            estimated_units,

        "weighted_median_units":
            round(
                weighted_median,
                2,
            ),

        "weighted_mean_units":
            round(
                weighted_mean,
                2,
            ),

        "support_count":
            len(usable),

        "total_evidence":
            round(
                sum(
                    item[
                        "evidence_score"
                    ]
                    for item in usable
                ),
                2,
            ),

        "average_evidence":
            round(
                sum(
                    item[
                        "evidence_score"
                    ]
                    for item in usable
                )
                / len(
                    usable
                ),
                2,
            ),

        "min_evidence_score":
            min_evidence_score,

        "min_support_cases":
            min_support_cases,
    }