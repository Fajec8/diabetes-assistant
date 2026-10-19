ADAPTIVE_K_V2_STRATEGY_NAME = (
    "ADAPTIVE_K_V2"
)

SHRINK_TO_5_THRESHOLD = 2.5
SHRINK_TO_3_THRESHOLD = 2.5
EXPAND_TO_20_THRESHOLD = 1.0

SHRINK_COVERAGE_MIN = 95.0

SUPPORTED_K_VALUES = [
    3,
    5,
    10,
    20
]


def _available_values(
    values
):
    return [
        value
        for value in values
        if value is not None
    ]


def _mean(
    values
):
    available = (
        _available_values(
            values
        )
    )

    if not available:
        return None

    return (
        sum(
            available
        )
        / len(
            available
        )
    )


def _average_ranking(
    situations
):
    return (
        _mean(
            [
                situation.get(
                    "ranking_score"
                )
                for situation
                in situations
            ]
        )
    )


def _average_coverage(
    situations
):
    return (
        _mean(
            [
                situation.get(
                    "data_coverage"
                )
                for situation
                in situations
            ]
        )
    )


def _ranking_drop(
    similar_situations,
    lower_k,
    upper_k
):
    if (
        len(
            similar_situations
        )
        < upper_k
    ):
        return None

    current_group = (
        similar_situations[
            :lower_k
        ]
    )

    added_group = (
        similar_situations[
            lower_k:upper_k
        ]
    )

    current_average = (
        _average_ranking(
            current_group
        )
    )

    added_average = (
        _average_ranking(
            added_group
        )
    )

    if (
        current_average is None
        or added_average is None
    ):
        return None

    return (
        current_average
        - added_average
    )


def _round_optional(
    value
):
    if value is None:
        return None

    return round(
        value,
        3
    )


def choose_adaptive_k_v2(
    similar_situations
):
    candidate_count = len(
        similar_situations
    )

    if (
        candidate_count
        < 3
    ):
        return {
            "strategy":
                ADAPTIVE_K_V2_STRATEGY_NAME,

            "selected_k":
                None,

            "candidate_count":
                candidate_count,

            "reason":
                "INSUFFICIENT_HISTORY",

            "top3_average_data_coverage":
                None,

            "drop_3_to_5":
                None,

            "drop_5_to_10":
                None,

            "drop_10_to_20":
                None
        }

    top3 = (
        similar_situations[
            :3
        ]
    )

    top3_average_data_coverage = (
        _average_coverage(
            top3
        )
    )

    drop_3_to_5 = (
        _ranking_drop(
            similar_situations=
                similar_situations,

            lower_k=3,
            upper_k=5
        )
    )

    drop_5_to_10 = (
        _ranking_drop(
            similar_situations=
                similar_situations,

            lower_k=5,
            upper_k=10
        )
    )

    drop_10_to_20 = (
        _ranking_drop(
            similar_situations=
                similar_situations,

            lower_k=10,
            upper_k=20
        )
    )

    # -----------------------------------------------------
    # Nedostatek historie
    #
    # Pokud zatim nemame ani K10,
    # pouzijeme nejvetsi podporovane K,
    # ktere je skutecne dostupne.
    #
    # Toto je fallback pro pocatecni fazi
    # uzivatele s malym mnozstvim historie.
    # -----------------------------------------------------

    if (
        candidate_count
        < 5
    ):
        selected_k = 3
        reason = "LIMITED_HISTORY_K3"

        return {
            "strategy":
                ADAPTIVE_K_V2_STRATEGY_NAME,

            "selected_k":
                selected_k,

            "candidate_count":
                candidate_count,

            "reason":
                reason,

            "top3_average_data_coverage":
                _round_optional(
                    top3_average_data_coverage
                ),

            "drop_3_to_5":
                _round_optional(
                    drop_3_to_5
                ),

            "drop_5_to_10":
                _round_optional(
                    drop_5_to_10
                ),

            "drop_10_to_20":
                _round_optional(
                    drop_10_to_20
                )
        }

    if (
        candidate_count
        < 10
    ):
        selected_k = 5
        reason = "LIMITED_HISTORY_K5"

        can_shrink = (
            top3_average_data_coverage
            is not None
            and top3_average_data_coverage
            >= SHRINK_COVERAGE_MIN
        )

        if (
            can_shrink
            and drop_3_to_5
            is not None
            and drop_3_to_5
            >= SHRINK_TO_3_THRESHOLD
        ):
            selected_k = 3
            reason = "STRONG_DROP_AFTER_K3"

        return {
            "strategy":
                ADAPTIVE_K_V2_STRATEGY_NAME,

            "selected_k":
                selected_k,

            "candidate_count":
                candidate_count,

            "reason":
                reason,

            "top3_average_data_coverage":
                _round_optional(
                    top3_average_data_coverage
                ),

            "drop_3_to_5":
                _round_optional(
                    drop_3_to_5
                ),

            "drop_5_to_10":
                _round_optional(
                    drop_5_to_10
                ),

            "drop_10_to_20":
                _round_optional(
                    drop_10_to_20
                )
        }

    # -----------------------------------------------------
    # Plna Adaptive K V2 logika
    #
    # Default:
    #
    # K = 10
    # -----------------------------------------------------

    selected_k = 10
    reason = "DEFAULT_K10"

    can_shrink = (
        top3_average_data_coverage
        is not None
        and top3_average_data_coverage
        >= SHRINK_COVERAGE_MIN
    )

    # -----------------------------------------------------
    # K10 -> K5
    #
    # Pokud kandidati 6-10 uz maji
    # vyrazne horsi ranking nez TOP5,
    # pouzijeme pouze K5.
    # -----------------------------------------------------

    if (
        can_shrink
        and drop_5_to_10
        is not None
        and drop_5_to_10
        >= SHRINK_TO_5_THRESHOLD
    ):
        selected_k = 5
        reason = "STRONG_DROP_AFTER_K5"

        # -------------------------------------------------
        # K5 -> K3
        #
        # Pokud jsou navic kandidati 4-5
        # vyrazne horsi nez TOP3,
        # zustaneme pouze u K3.
        # -------------------------------------------------

        if (
            drop_3_to_5
            is not None
            and drop_3_to_5
            >= SHRINK_TO_3_THRESHOLD
        ):
            selected_k = 3
            reason = "STRONG_DROP_AFTER_K3"

    # -----------------------------------------------------
    # K10 -> K20
    #
    # Pouze pokud jsme zustali na K10
    # a kandidati 11-20 maji velmi
    # podobnou ranking kvalitu.
    # -----------------------------------------------------

    if (
        selected_k
        == 10
        and candidate_count
        >= 20
        and drop_10_to_20
        is not None
        and drop_10_to_20
        <= EXPAND_TO_20_THRESHOLD
    ):
        selected_k = 20
        reason = "FLAT_RANKING_TO_K20"

    return {
        "strategy":
            ADAPTIVE_K_V2_STRATEGY_NAME,

        "selected_k":
            selected_k,

        "candidate_count":
            candidate_count,

        "reason":
            reason,

        "top3_average_data_coverage":
            _round_optional(
                top3_average_data_coverage
            ),

        "drop_3_to_5":
            _round_optional(
                drop_3_to_5
            ),

        "drop_5_to_10":
            _round_optional(
                drop_5_to_10
            ),

        "drop_10_to_20":
            _round_optional(
                drop_10_to_20
            )
    }