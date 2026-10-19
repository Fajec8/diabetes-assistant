from app.services.adaptive_k import (
    ADAPTIVE_K_V2_STRATEGY_NAME,
    SUPPORTED_K_VALUES,
    choose_adaptive_k_v2,
)
from app.services.evidence import (
    build_evidence,
)
from app.services.history_search import (
    find_similar_situations,
)
from app.services.outcome_summary import (
    summarize_outcomes,
)
from app.services.situation_outcome import (
    build_situation_outcome,
)


DEFAULT_K_VALUES = [
    3,
    5,
    10,
    20,
    30
]

HORIZONS = [
    30,
    60,
    90,
    120,
    180
]


def _absolute_error(
    predicted,
    actual
):
    if (
        predicted is None
        or actual is None
    ):
        return None

    return round(
        abs(
            predicted
            - actual
        ),
        2
    )


def _mean(
    values
):
    available = [
        value
        for value in values
        if value is not None
    ]

    if not available:
        return None

    return round(
        sum(
            available
        )
        / len(
            available
        ),
        2
    )


def calculate_prediction_metrics(
    actual_outcome,
    outcome_summary
):
    horizons = {}

    median_errors = []
    weighted_mean_errors = []

    for minutes in HORIZONS:
        delta_key = (
            f"delta_{minutes}m"
        )

        actual_delta = (
            actual_outcome.get(
                delta_key
            )
        )

        summary = (
            outcome_summary.get(
                delta_key,
                {}
            )
        )

        predicted_median = (
            summary.get(
                "median"
            )
        )

        predicted_weighted_mean = (
            summary.get(
                "weighted_mean"
            )
        )

        median_error = (
            _absolute_error(
                predicted_median,
                actual_delta
            )
        )

        weighted_mean_error = (
            _absolute_error(
                predicted_weighted_mean,
                actual_delta
            )
        )

        median_errors.append(
            median_error
        )

        weighted_mean_errors.append(
            weighted_mean_error
        )

        horizons[
            f"{minutes}m"
        ] = {
            "actual_delta":
                actual_delta,

            "predicted_median":
                predicted_median,

            "predicted_weighted_mean":
                predicted_weighted_mean,

            "absolute_error_median":
                median_error,

            "absolute_error_weighted_mean":
                weighted_mean_error
        }

    return {
        "mae_median":
            _mean(
                median_errors
            ),

        "mae_weighted_mean":
            _mean(
                weighted_mean_errors
            ),

        "horizons":
            horizons
    }


def _evaluate_selected_situations(
    selected_situations,
    actual_outcome
):
    outcome_summary = (
        summarize_outcomes(
            selected_situations
        )
    )

    evidence = (
        build_evidence(
            selected_situations
        )
    )

    metrics = (
        calculate_prediction_metrics(
            actual_outcome=
                actual_outcome,

            outcome_summary=
                outcome_summary
        )
    )

    return {
        "k_found":
            len(
                selected_situations
            ),

        "evidence_quality":
            evidence[
                "quality"
            ],

        "average_ranking_score":
            evidence[
                "average_ranking_score"
            ],

        "minimum_ranking_score":
            evidence[
                "minimum_ranking_score"
            ],

        "average_data_coverage":
            evidence[
                "average_data_coverage"
            ],

        "mae_median":
            metrics[
                "mae_median"
            ],

        "mae_weighted_mean":
            metrics[
                "mae_weighted_mean"
            ],

        "horizons":
            metrics[
                "horizons"
            ]
    }


def evaluate_k_values(
    db,
    user_id,
    t0,
    k_values=None
):
    if k_values is None:
        k_values = (
            DEFAULT_K_VALUES
        )

    k_values = list(
        k_values
    )

    actual_outcome = (
        build_situation_outcome(
            db=db,
            user_id=user_id,
            t0=t0
        )
    )

    # -----------------------------------------------------
    # Historii chceme stale hledat pouze jednou.
    #
    # Potrebujeme dost kandidatu jak pro:
    #
    # fixed K evaluaci
    #
    # tak pro:
    #
    # Adaptive K V2
    #
    # ktere muze pouzit maximalne K20.
    # -----------------------------------------------------

    fixed_max_k = (
        max(
            k_values
        )
        if k_values
        else 0
    )

    adaptive_max_k = (
        max(
            SUPPORTED_K_VALUES
        )
    )

    search_limit = max(
        fixed_max_k,
        adaptive_max_k
    )

    history_result = (
        find_similar_situations(
            db=db,
            user_id=user_id,
            t0=t0,
            limit=search_limit
        )
    )

    all_similar_situations = (
        history_result.get(
            "similar_situations",
            []
        )
    )

    # -----------------------------------------------------
    # FIXED K
    # -----------------------------------------------------

    results = []

    for k in k_values:
        selected_situations = (
            all_similar_situations[
                :k
            ]
        )

        evaluation_result = (
            _evaluate_selected_situations(
                selected_situations=
                    selected_situations,

                actual_outcome=
                    actual_outcome
            )
        )

        results.append({
            "k_requested":
                k,

            **evaluation_result
        })

    # -----------------------------------------------------
    # ADAPTIVE K V2
    #
    # Vyber K NEPOUZIVA outcome aktualni situace.
    #
    # Rozhoduje pouze podle historickych kandidatu:
    #
    # - ranking score
    # - data coverage
    #
    # Actual outcome je pouzit az nasledne
    # pro evaluaci presnosti.
    # -----------------------------------------------------

    adaptive_selection = (
        choose_adaptive_k_v2(
            all_similar_situations
        )
    )

    adaptive_result = None

    adaptive_k = (
        adaptive_selection.get(
            "selected_k"
        )
    )

    if adaptive_k is not None:
        adaptive_situations = (
            all_similar_situations[
                :adaptive_k
            ]
        )

        adaptive_evaluation = (
            _evaluate_selected_situations(
                selected_situations=
                    adaptive_situations,

                actual_outcome=
                    actual_outcome
            )
        )

        adaptive_result = {
            "strategy":
                ADAPTIVE_K_V2_STRATEGY_NAME,

            "selected_k":
                adaptive_k,

            "selection":
                adaptive_selection,

            **adaptive_evaluation
        }

    return {
        "evaluation_timestamp":
            t0.isoformat(),

        "actual_outcome":
            actual_outcome,

        "results":
            results,

        "adaptive":
            adaptive_result
    }