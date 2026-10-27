from __future__ import annotations


STRONG_EVIDENCE_MIN = 60.0
MODERATE_EVIDENCE_MIN = 40.0


def _validate_score(
    value: float,
    name: str,
) -> float:
    value = float(value)

    if not 0.0 <= value <= 100.0:
        raise ValueError(
            f"{name} must be between 0 and 100"
        )

    return value


def _evidence_level(
    score: float,
) -> str:
    if score >= STRONG_EVIDENCE_MIN:
        return "STRONG"

    if score >= MODERATE_EVIDENCE_MIN:
        return "MODERATE"

    return "WEAK"


def evaluate_evidence_strength(
    context_score: float | None,
    quality_score: float | None,
    confidence: float | None,
) -> dict:
    if (
        context_score is None
        or quality_score is None
        or confidence is None
    ):
        return {
            "evidence_score": None,
            "evidence_level": "NO_DATA",
            "context_score": context_score,
            "quality_score": quality_score,
            "confidence": confidence,
        }

    context_score = _validate_score(
        context_score,
        "context_score",
    )

    quality_score = _validate_score(
        quality_score,
        "quality_score",
    )

    confidence = _validate_score(
        confidence,
        "confidence",
    )

    evidence_score = round(
        context_score
        * (quality_score / 100.0)
        * (confidence / 100.0),
        2,
    )

    return {
        "evidence_score":
            evidence_score,

        "evidence_level":
            _evidence_level(
                evidence_score
            ),

        "context_score":
            context_score,

        "quality_score":
            quality_score,

        "confidence":
            confidence,
    }