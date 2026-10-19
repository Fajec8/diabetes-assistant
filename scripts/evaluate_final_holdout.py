from collections import Counter
from datetime import timedelta
from json import dump
from math import ceil, floor, sqrt
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.services.adaptive_k import (
    ADAPTIVE_K_V2_STRATEGY_NAME,
    EXPAND_TO_20_THRESHOLD,
    SHRINK_COVERAGE_MIN,
    SHRINK_TO_3_THRESHOLD,
    SHRINK_TO_5_THRESHOLD,
)
from app.services.batch_evaluation import (
    evaluate_batch,
)
from scripts.seed_final_holdout import (
    FINAL_DATASETS,
)
from scripts.seed_validation_sets import (
    EMAIL,
    HOLDOUT_DAYS,
    TOTAL_DAYS,
    WARMUP_DAYS,
    _build_day_parameters,
)


FIXED_K = 10

HORIZONS = [
    30,
    60,
    90,
    120,
    180
]

EXPECTED_DATASET_COUNT = 4

EXPECTED_EVALUATIONS_PER_DATASET = (
    HOLDOUT_DAYS
)

EXPECTED_TOTAL_EVALUATIONS = (
    EXPECTED_DATASET_COUNT
    * EXPECTED_EVALUATIONS_PER_DATASET
)


def _format_number(
    value
):
    if value is None:
        return "-"

    return f"{value:.3f}"


def _format_percent(
    value
):
    if value is None:
        return "-"

    return f"{value:.1f}%"


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

    return round(
        sum(
            available
        )
        / len(
            available
        ),
        3
    )


def _median(
    values
):
    available = sorted(
        _available_values(
            values
        )
    )

    if not available:
        return None

    count = len(
        available
    )

    middle = (
        count // 2
    )

    if (
        count % 2
        == 1
    ):
        result = (
            available[
                middle
            ]
        )

    else:
        result = (
            (
                available[
                    middle - 1
                ]
                + available[
                    middle
                ]
            )
            / 2
        )

    return round(
        result,
        3
    )


def _standard_deviation(
    values
):
    available = (
        _available_values(
            values
        )
    )

    if not available:
        return None

    mean_value = (
        sum(
            available
        )
        / len(
            available
        )
    )

    variance = (
        sum(
            (
                value
                - mean_value
            ) ** 2
            for value
            in available
        )
        / len(
            available
        )
    )

    return round(
        sqrt(
            variance
        ),
        3
    )


def _percentile(
    values,
    percentile
):
    available = sorted(
        _available_values(
            values
        )
    )

    if not available:
        return None

    if (
        len(
            available
        )
        == 1
    ):
        return round(
            available[0],
            3
        )

    position = (
        (
            len(
                available
            )
            - 1
        )
        * percentile
        / 100
    )

    lower_index = floor(
        position
    )

    upper_index = ceil(
        position
    )

    if (
        lower_index
        == upper_index
    ):
        result = (
            available[
                lower_index
            ]
        )

    else:
        fraction = (
            position
            - lower_index
        )

        result = (
            available[
                lower_index
            ]
            + (
                available[
                    upper_index
                ]
                - available[
                    lower_index
                ]
            )
            * fraction
        )

    return round(
        result,
        3
    )


def _maximum(
    values
):
    available = (
        _available_values(
            values
        )
    )

    if not available:
        return None

    return round(
        max(
            available
        ),
        3
    )


def _statistics(
    values
):
    available = (
        _available_values(
            values
        )
    )

    return {
        "count":
            len(
                available
            ),

        "mean":
            _mean(
                available
            ),

        "median":
            _median(
                available
            ),

        "standard_deviation":
            _standard_deviation(
                available
            ),

        "p90":
            _percentile(
                available,
                90
            ),

        "p95":
            _percentile(
                available,
                95
            ),

        "maximum":
            _maximum(
                available
            )
    }


def _build_exact_holdout_times(
    dataset
):
    evaluation_times = []

    previous_activity_minutes = 0

    for day_index in range(
        TOTAL_DAYS
    ):
        parameters = (
            _build_day_parameters(
                dataset=
                    dataset,

                day_index=
                    day_index,

                previous_activity_minutes=
                    previous_activity_minutes
            )
        )

        base_t0 = (
            dataset[
                "start"
            ]
            + timedelta(
                days=
                    day_index
            )
        )

        t0 = (
            base_t0
            + timedelta(
                minutes=
                    parameters[
                        "time_offset"
                    ]
            )
        )

        if (
            day_index
            >= WARMUP_DAYS
        ):
            evaluation_times.append(
                t0
            )

        if (
            parameters[
                "has_activity"
            ]
        ):
            previous_activity_minutes = (
                parameters[
                    "activity_duration"
                ]
            )

        else:
            previous_activity_minutes = 0

    return evaluation_times


def _find_fixed_result(
    evaluation
):
    for item in evaluation.get(
        "results",
        []
    ):
        if (
            item.get(
                "k_requested"
            )
            == FIXED_K
        ):
            return item

    return None


def _build_summary(
    evaluations
):
    fixed_errors = []
    adaptive_errors = []
    differences = []

    fixed_horizon_errors = {
        f"{minutes}m": []
        for minutes
        in HORIZONS
    }

    adaptive_horizon_errors = {
        f"{minutes}m": []
        for minutes
        in HORIZONS
    }

    selections = Counter()
    reasons = Counter()

    adaptive_wins = 0
    ties = 0
    fixed_wins = 0

    records = []

    for evaluation in evaluations:
        fixed = (
            _find_fixed_result(
                evaluation
            )
        )

        adaptive = (
            evaluation.get(
                "adaptive"
            )
        )

        if (
            fixed is None
            or adaptive is None
        ):
            continue

        fixed_error = (
            fixed.get(
                "mae_median"
            )
        )

        adaptive_error = (
            adaptive.get(
                "mae_median"
            )
        )

        if (
            fixed_error is None
            or adaptive_error is None
        ):
            continue

        fixed_errors.append(
            fixed_error
        )

        adaptive_errors.append(
            adaptive_error
        )

        difference = round(
            adaptive_error
            - fixed_error,
            3
        )

        differences.append(
            difference
        )

        if (
            adaptive_error
            < fixed_error
        ):
            adaptive_wins += 1

        elif (
            adaptive_error
            > fixed_error
        ):
            fixed_wins += 1

        else:
            ties += 1

        selected_k = (
            adaptive.get(
                "selected_k"
            )
        )

        selections[
            selected_k
        ] += 1

        selection = (
            adaptive.get(
                "selection",
                {}
            )
        )

        reason = (
            selection.get(
                "reason",
                "UNKNOWN"
            )
        )

        reasons[
            reason
        ] += 1

        fixed_record_horizons = {}
        adaptive_record_horizons = {}

        for minutes in HORIZONS:
            horizon_key = (
                f"{minutes}m"
            )

            fixed_horizon = (
                fixed.get(
                    "horizons",
                    {}
                ).get(
                    horizon_key,
                    {}
                )
            )

            adaptive_horizon = (
                adaptive.get(
                    "horizons",
                    {}
                ).get(
                    horizon_key,
                    {}
                )
            )

            fixed_horizon_error = (
                fixed_horizon.get(
                    "absolute_error_median"
                )
            )

            adaptive_horizon_error = (
                adaptive_horizon.get(
                    "absolute_error_median"
                )
            )

            fixed_horizon_errors[
                horizon_key
            ].append(
                fixed_horizon_error
            )

            adaptive_horizon_errors[
                horizon_key
            ].append(
                adaptive_horizon_error
            )

            fixed_record_horizons[
                horizon_key
            ] = fixed_horizon_error

            adaptive_record_horizons[
                horizon_key
            ] = adaptive_horizon_error

        records.append({
            "timestamp":
                evaluation[
                    "evaluation_timestamp"
                ],

            "fixed_k10_mae":
                fixed_error,

            "adaptive_v2_mae":
                adaptive_error,

            "difference_adaptive_minus_k10":
                difference,

            "adaptive_selected_k":
                selected_k,

            "adaptive_reason":
                reason,

            "fixed_horizon_errors":
                fixed_record_horizons,

            "adaptive_horizon_errors":
                adaptive_record_horizons
        })

    comparison_count = (
        adaptive_wins
        + ties
        + fixed_wins
    )

    adaptive_non_worse = (
        adaptive_wins
        + ties
    )

    non_worse_percent = None

    if comparison_count:
        non_worse_percent = round(
            adaptive_non_worse
            / comparison_count
            * 100,
            1
        )

    horizon_summary = {}

    for minutes in HORIZONS:
        horizon_key = (
            f"{minutes}m"
        )

        horizon_summary[
            horizon_key
        ] = {
            "fixed_k10":
                _statistics(
                    fixed_horizon_errors[
                        horizon_key
                    ]
                ),

            "adaptive_v2":
                _statistics(
                    adaptive_horizon_errors[
                        horizon_key
                    ]
                )
        }

    return {
        "count":
            comparison_count,

        "fixed_k10":
            _statistics(
                fixed_errors
            ),

        "adaptive_v2":
            _statistics(
                adaptive_errors
            ),

        "paired_difference":
            _statistics(
                differences
            ),

        "adaptive_wins":
            adaptive_wins,

        "ties":
            ties,

        "fixed_k10_wins":
            fixed_wins,

        "adaptive_non_worse_percent":
            non_worse_percent,

        "selected_k":
            dict(
                selections
            ),

        "reasons":
            dict(
                reasons
            ),

        "horizons":
            horizon_summary,

        "records":
            records
    }


def _print_method_table(
    summary
):
    fixed = (
        summary[
            "fixed_k10"
        ]
    )

    adaptive = (
        summary[
            "adaptive_v2"
        ]
    )

    print()

    print(
        f"{'METHOD':<18}"
        f"{'AVG':<10}"
        f"{'MEDIAN':<10}"
        f"{'STD':<10}"
        f"{'P90':<10}"
        f"{'P95':<10}"
        f"{'MAX':<10}"
    )

    print(
        "-" * 78
    )

    print(
        f"{'FIXED K10':<18}"
        f"{_format_number(fixed['mean']):<10}"
        f"{_format_number(fixed['median']):<10}"
        f"{_format_number(fixed['standard_deviation']):<10}"
        f"{_format_number(fixed['p90']):<10}"
        f"{_format_number(fixed['p95']):<10}"
        f"{_format_number(fixed['maximum']):<10}"
    )

    print(
        f"{'ADAPTIVE V2':<18}"
        f"{_format_number(adaptive['mean']):<10}"
        f"{_format_number(adaptive['median']):<10}"
        f"{_format_number(adaptive['standard_deviation']):<10}"
        f"{_format_number(adaptive['p90']):<10}"
        f"{_format_number(adaptive['p95']):<10}"
        f"{_format_number(adaptive['maximum']):<10}"
    )


def _print_comparison(
    summary
):
    difference = (
        summary[
            "paired_difference"
        ]
    )

    print()

    print(
        "Parove porovnani:"
    )

    print(
        "  Adaptive V2 vyhry:",
        summary[
            "adaptive_wins"
        ]
    )

    print(
        "  Remizy:",
        summary[
            "ties"
        ]
    )

    print(
        "  Fixed K10 vyhry:",
        summary[
            "fixed_k10_wins"
        ]
    )

    print(
        "  Adaptive neni horsi:",
        _format_percent(
            summary[
                "adaptive_non_worse_percent"
            ]
        )
    )

    print(
        "  AVG rozdil "
        "(Adaptive - K10):",
        _format_number(
            difference[
                "mean"
            ]
        )
    )

    print(
        "  MEDIAN rozdil:",
        _format_number(
            difference[
                "median"
            ]
        )
    )

    print(
        "  P95 rozdilu:",
        _format_number(
            difference[
                "p95"
            ]
        )
    )


def _print_selection(
    summary
):
    print()

    print(
        "Adaptive K V2 vyber:"
    )

    total = (
        summary[
            "count"
        ]
    )

    for k in [
        3,
        5,
        10,
        20
    ]:
        count = (
            summary[
                "selected_k"
            ].get(
                k,
                0
            )
        )

        percent = None

        if total:
            percent = (
                count
                / total
                * 100
            )

        print(
            f"  K={k:<2} "
            f"{count:<4} "
            f"({_format_percent(percent)})"
        )

    print()

    print(
        "Duvody:"
    )

    for (
        reason,
        count
    ) in sorted(
        summary[
            "reasons"
        ].items()
    ):
        print(
            f"  {reason}: "
            f"{count}"
        )


def _print_horizons(
    summary
):
    print()

    print(
        "MAE PODLE HORIZONTU"
    )

    print(
        "-" * 76
    )

    print(
        f"{'HORIZON':<12}"
        f"{'K10 AVG':<14}"
        f"{'ADAPT AVG':<14}"
        f"{'DELTA':<14}"
    )

    print(
        "-" * 76
    )

    for minutes in HORIZONS:
        horizon_key = (
            f"{minutes}m"
        )

        fixed_mean = (
            summary[
                "horizons"
            ][
                horizon_key
            ][
                "fixed_k10"
            ][
                "mean"
            ]
        )

        adaptive_mean = (
            summary[
                "horizons"
            ][
                horizon_key
            ][
                "adaptive_v2"
            ][
                "mean"
            ]
        )

        difference = None

        if (
            fixed_mean is not None
            and adaptive_mean is not None
        ):
            difference = round(
                adaptive_mean
                - fixed_mean,
                3
            )

        print(
            f"{horizon_key:<12}"
            f"{_format_number(fixed_mean):<14}"
            f"{_format_number(adaptive_mean):<14}"
            f"{_format_number(difference):<14}"
        )


def _print_dataset_summary(
    dataset_name,
    summary
):
    print()
    print(
        "=" * 104
    )

    print(
        dataset_name
    )

    print(
        "=" * 104
    )

    print(
        "Final situaci:",
        summary[
            "count"
        ]
    )

    _print_method_table(
        summary
    )

    _print_comparison(
        summary
    )

    _print_selection(
        summary
    )

    _print_horizons(
        summary
    )


def _save_results(
    dataset_summaries,
    overall_summary
):
    output_directory = Path(
        "results"
    )

    output_directory.mkdir(
        exist_ok=True
    )

    output_path = (
        output_directory
        / "final_holdout_k10_vs_adaptive_v2.json"
    )

    payload = {
        "protocol": {
            "status":
                "FINAL_LOCKED_HOLDOUT",

            "primary_metric":
                (
                    "Mean MAE across "
                    "30/60/90/120/180 minute "
                    "median-prediction errors"
                ),

            "baseline":
                "FIXED_K10",

            "challenger":
                ADAPTIVE_K_V2_STRATEGY_NAME,

            "expected_final_situations":
                EXPECTED_TOTAL_EVALUATIONS,

            "adaptive_parameters": {
                "shrink_k10_to_k5":
                    SHRINK_TO_5_THRESHOLD,

                "shrink_k5_to_k3":
                    SHRINK_TO_3_THRESHOLD,

                "expand_k10_to_k20":
                    EXPAND_TO_20_THRESHOLD,

                "minimum_coverage_for_shrink":
                    SHRINK_COVERAGE_MIN
            }
        },

        "datasets":
            dataset_summaries,

        "overall":
            overall_summary
    }

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as file:
        dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2
        )

    return output_path


def main():
    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(
                User.email
                == EMAIL
            )
        )

        if user is None:
            print(
                "Testovaci uzivatel "
                "nebyl nalezen."
            )
            return

        print()
        print(
            "FINAL HOLDOUT EVALUATION"
        )

        print(
            "=" * 104
        )

        print(
            "TOTO JE ZAMKNUTA FINALNI EVALUACE."
        )

        print()

        print(
            "Baseline:"
        )

        print(
            "  Fixed K = 10"
        )

        print()

        print(
            "Challenger:"
        )

        print(
            "  Adaptive K V2"
        )

        print(
            "  K10 -> K5:",
            SHRINK_TO_5_THRESHOLD
        )

        print(
            "  K5 -> K3:",
            SHRINK_TO_3_THRESHOLD
        )

        print(
            "  K10 -> K20:",
            EXPAND_TO_20_THRESHOLD
        )

        print(
            "  min coverage:",
            SHRINK_COVERAGE_MIN
        )

        print()

        print(
            "Primarni metrika:"
        )

        print(
            "  AVG MAE pres horizonty "
            "+30/+60/+90/+120/+180 minut"
        )

        print()

        print(
            "Sekundarni metriky:"
        )

        print(
            "  median, STD, P90, P95, MAX,"
        )

        print(
            "  paired wins/ties/losses,"
        )

        print(
            "  chyby podle horizontu."
        )

        dataset_summaries = {}

        all_evaluations = []

        total_skipped = 0

        for dataset in FINAL_DATASETS:
            evaluation_times = (
                _build_exact_holdout_times(
                    dataset
                )
            )

            result = (
                evaluate_batch(
                    db=db,
                    user_id=user.id,
                    evaluation_times=
                        evaluation_times,
                    k_values=[
                        FIXED_K
                    ]
                )
            )

            total_skipped += (
                result[
                    "skipped_count"
                ]
            )

            if (
                result[
                    "evaluated_count"
                ]
                != HOLDOUT_DAYS
            ):
                print()
                print(
                    "VAROVANI:"
                )

                print(
                    dataset[
                        "name"
                    ],
                    "nema ocekavanych",
                    HOLDOUT_DAYS,
                    "kompletnich situaci."
                )

            summary = (
                _build_summary(
                    result[
                        "evaluations"
                    ]
                )
            )

            dataset_summaries[
                dataset[
                    "name"
                ]
            ] = summary

            all_evaluations.extend(
                result[
                    "evaluations"
                ]
            )

            _print_dataset_summary(
                dataset_name=
                    dataset[
                        "name"
                    ],

                summary=
                    summary
            )

        overall_summary = (
            _build_summary(
                all_evaluations
            )
        )

        print()
        print(
            "#" * 104
        )

        print(
            "FINAL OVERALL RESULT"
        )

        print(
            "#" * 104
        )

        print(
            "Ocekavano situaci:",
            EXPECTED_TOTAL_EVALUATIONS
        )

        print(
            "Vyhodnoceno situaci:",
            overall_summary[
                "count"
            ]
        )

        print(
            "Preskoceno:",
            total_skipped
        )

        _print_method_table(
            overall_summary
        )

        _print_comparison(
            overall_summary
        )

        _print_selection(
            overall_summary
        )

        _print_horizons(
            overall_summary
        )

        output_path = (
            _save_results(
                dataset_summaries=
                    dataset_summaries,

                overall_summary=
                    overall_summary
            )
        )

        print()
        print(
            "=" * 104
        )

        print(
            "FINAL HOLDOUT DOKONCEN."
        )

        print(
            "=" * 104
        )

        print(
            "Vysledky ulozeny do:"
        )

        print(
            f"  {output_path}"
        )

        print()

        print(
            "Od tohoto okamziku se podle "
            "tohoto final holdoutu "
            "Adaptive K V2 NEPRELADUJE."
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()