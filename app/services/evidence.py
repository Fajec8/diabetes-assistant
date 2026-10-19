HIGH_MIN_SAMPLE_SIZE = 8
HIGH_MIN_AVERAGE_RANKING = 90.0
HIGH_MIN_AVERAGE_COVERAGE = 90.0

MEDIUM_MIN_SAMPLE_SIZE = 5
MEDIUM_MIN_AVERAGE_RANKING = 75.0
MEDIUM_MIN_AVERAGE_COVERAGE = 75.0


def _average(values):
    available = [
        value
        for value in values
        if value is not None
    ]

    if not available:
        return None

    return round(
        sum(available)
        / len(available),
        2
    )


def _minimum(values):
    available = [
        value
        for value in values
        if value is not None
    ]

    if not available:
        return None

    return round(
        min(available),
        2
    )


def _evaluate_quality(
    sample_size,
    average_ranking_score,
    average_data_coverage
):
    if sample_size == 0:
        return "NO_DATA"

    if (
        sample_size
        >= HIGH_MIN_SAMPLE_SIZE

        and average_ranking_score
        is not None

        and average_ranking_score
        >= HIGH_MIN_AVERAGE_RANKING

        and average_data_coverage
        is not None

        and average_data_coverage
        >= HIGH_MIN_AVERAGE_COVERAGE
    ):
        return "HIGH"

    if (
        sample_size
        >= MEDIUM_MIN_SAMPLE_SIZE

        and average_ranking_score
        is not None

        and average_ranking_score
        >= MEDIUM_MIN_AVERAGE_RANKING

        and average_data_coverage
        is not None

        and average_data_coverage
        >= MEDIUM_MIN_AVERAGE_COVERAGE
    ):
        return "MEDIUM"

    return "LOW"


def build_evidence(
    items
):
    sample_size = len(items)

    similarity_scores = [
        item.get(
            "similarity_score"
        )
        for item in items
    ]

    ranking_scores = [
        item.get(
            "ranking_score"
        )
        for item in items
    ]

    data_coverages = [
        item.get(
            "data_coverage"
        )
        for item in items
    ]

    average_similarity_score = (
        _average(
            similarity_scores
        )
    )

    average_ranking_score = (
        _average(
            ranking_scores
        )
    )

    minimum_ranking_score = (
        _minimum(
            ranking_scores
        )
    )

    average_data_coverage = (
        _average(
            data_coverages
        )
    )

    quality = (
        _evaluate_quality(
            sample_size=
                sample_size,

            average_ranking_score=
                average_ranking_score,

            average_data_coverage=
                average_data_coverage
        )
    )

    return {
        "sample_size":
            sample_size,

        "average_similarity_score":
            average_similarity_score,

        "average_ranking_score":
            average_ranking_score,

        "minimum_ranking_score":
            minimum_ranking_score,

        "average_data_coverage":
            average_data_coverage,

        "quality":
            quality
    }