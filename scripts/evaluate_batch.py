from collections import Counter
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models.glucose import GlucoseReading
from app.models.user import User
from app.services.batch_evaluation import (
    DEFAULT_BATCH_K_VALUES,
    evaluate_batch,
)
from app.services.situation_outcome import (
    build_situation_outcome,
)


TEST_USER_EMAIL = (
    "test@example.com"
)

TARGET_HOUR = 13
TARGET_MINUTE = 30

HORIZONS = [
    "30m",
    "60m",
    "90m",
    "120m",
    "180m"
]


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


def _minutes_from_midnight(
    timestamp
):
    return (
        timestamp.hour * 60
        + timestamp.minute
    )


def _discover_evaluation_times(
    db,
    user
):
    timezone = ZoneInfo(
        user.timezone
    )

    readings = db.scalars(
        select(
            GlucoseReading
        )
        .where(
            GlucoseReading.user_id
            == user.id
        )
        .order_by(
            GlucoseReading.measured_at
        )
    ).all()

    target_minutes = (
        TARGET_HOUR * 60
        + TARGET_MINUTE
    )

    candidates_per_day = {}

    for reading in readings:
        local_time = (
            reading.measured_at
            .astimezone(
                timezone
            )
        )

        if (
            local_time.minute
            % 15
            != 0
        ):
            continue

        day = (
            local_time.date()
        )

        candidates_per_day.setdefault(
            day,
            []
        ).append(
            local_time
        )

    evaluation_times = []
    days_without_complete_outcome = []

    for day in sorted(
        candidates_per_day.keys()
    ):
        candidates = (
            candidates_per_day[
                day
            ]
        )

        candidates = sorted(
            candidates,
            key=lambda timestamp: (
                abs(
                    _minutes_from_midnight(
                        timestamp
                    )
                    - target_minutes
                ),
                timestamp
            )
        )

        selected_time = None

        for candidate_time in candidates:
            outcome = (
                build_situation_outcome(
                    db=db,
                    user_id=user.id,
                    t0=candidate_time
                )
            )

            if (
                outcome.get(
                    "outcome_coverage"
                )
                == 100.0
            ):
                selected_time = (
                    candidate_time
                )

                break

        if selected_time is None:
            days_without_complete_outcome.append({
                "date":
                    day.isoformat(),

                "reason":
                    "NO_COMPLETE_OUTCOME"
            })

            continue

        evaluation_times.append(
            selected_time
        )

    return (
        evaluation_times,
        days_without_complete_outcome
    )


def _best_k_values(
    aggregate_results,
    metric_name
):
    usable = [
        (
            item["k"],
            item.get(
                metric_name
            )
        )
        for item
        in aggregate_results
        if (
            item.get(
                metric_name
            )
            is not None
        )
    ]

    if not usable:
        return []

    best_value = min(
        value
        for _,
        value
        in usable
    )

    return [
        k
        for k,
        value
        in usable
        if value == best_value
    ]


def _format_k_list(
    k_values
):
    if not k_values:
        return "-"

    return "/".join(
        str(k)
        for k
        in k_values
    )


def _print_method_statistics(
    title,
    aggregate_results,
    method_key
):
    print()
    print(
        "=" * 108
    )

    print(
        title
    )

    print(
        "=" * 108
    )

    print(
        f"{'K':<6}"
        f"{'EVALS':<8}"
        f"{'AVG':<10}"
        f"{'MEDIAN':<10}"
        f"{'STD':<10}"
        f"{'P90':<10}"
        f"{'P95':<10}"
        f"{'MAX':<10}"
        f"{'WINS':<10}"
        f"{'WIN %':<10}"
    )

    print(
        "-" * 108
    )

    for item in aggregate_results:
        statistics = (
            item[
                method_key
            ]
        )

        print(
            f"{item['k']:<6}"
            f"{item['evaluation_count']:<8}"
            f"{_format_number(statistics['mean_mae']):<10}"
            f"{_format_number(statistics['median_mae']):<10}"
            f"{_format_number(statistics['standard_deviation']):<10}"
            f"{_format_number(statistics['p90']):<10}"
            f"{_format_number(statistics['p95']):<10}"
            f"{_format_number(statistics['maximum']):<10}"
            f"{statistics['win_count']:<10}"
            f"{_format_percent(statistics['win_rate_percent']):<10}"
        )


def _print_horizon_statistics(
    title,
    aggregate_results,
    prediction_key
):
    print()
    print(
        "=" * 82
    )

    print(
        title
    )

    print(
        "=" * 82
    )

    print(
        f"{'K':<8}"
        f"{'30m':<12}"
        f"{'60m':<12}"
        f"{'90m':<12}"
        f"{'120m':<12}"
        f"{'180m':<12}"
    )

    print(
        "-" * 82
    )

    for item in aggregate_results:
        values = []

        for horizon in HORIZONS:
            statistics = (
                item[
                    "horizons"
                ][
                    horizon
                ][
                    prediction_key
                ]
            )

            values.append(
                statistics[
                    "mean"
                ]
            )

        print(
            f"{item['k']:<8}"
            f"{_format_number(values[0]):<12}"
            f"{_format_number(values[1]):<12}"
            f"{_format_number(values[2]):<12}"
            f"{_format_number(values[3]):<12}"
            f"{_format_number(values[4]):<12}"
        )


def _best_k_for_horizon(
    aggregate_results,
    horizon,
    prediction_key
):
    values = []

    for item in aggregate_results:
        value = (
            item[
                "horizons"
            ][
                horizon
            ][
                prediction_key
            ][
                "mean"
            ]
        )

        if value is None:
            continue

        values.append(
            (
                item["k"],
                value
            )
        )

    if not values:
        return []

    best_value = min(
        value
        for _,
        value
        in values
    )

    return [
        k
        for k,
        value
        in values
        if value == best_value
    ]


def _print_best_horizon_values(
    aggregate_results
):
    print()
    print(
        "=" * 82
    )

    print(
        "NEJLEPSI K PODLE PREDIKCNIHO HORIZONTU"
    )

    print(
        "=" * 82
    )

    print(
        f"{'HORIZONT':<14}"
        f"{'MEDIAN METHOD':<22}"
        f"{'WEIGHTED METHOD':<22}"
    )

    print(
        "-" * 82
    )

    for horizon in HORIZONS:
        median_best = (
            _best_k_for_horizon(
                aggregate_results=
                    aggregate_results,

                horizon=
                    horizon,

                prediction_key=
                    "median_prediction"
            )
        )

        weighted_best = (
            _best_k_for_horizon(
                aggregate_results=
                    aggregate_results,

                horizon=
                    horizon,

                prediction_key=
                    "weighted_mean_prediction"
            )
        )

        print(
            f"{horizon:<14}"
            f"{_format_k_list(median_best):<22}"
            f"{_format_k_list(weighted_best):<22}"
        )


def main():
    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(
                User.email
                == TEST_USER_EMAIL
            )
        )

        if user is None:
            print(
                "Testovaci uzivatel nebyl nalezen."
            )
            return

        (
            evaluation_times,
            discovery_skipped
        ) = _discover_evaluation_times(
            db,
            user
        )

        print()
        print(
            "BATCH EVALUACE K"
        )

        print(
            "=" * 78
        )

        total_days = (
            len(evaluation_times)
            + len(discovery_skipped)
        )

        print(
            "Nalezene dny:",
            total_days
        )

        print(
            "Dny s kompletnim outcome:",
            len(
                evaluation_times
            )
        )

        print(
            "Dny bez kompletniho outcome:",
            len(
                discovery_skipped
            )
        )

        print(
            "Testovana K:",
            DEFAULT_BATCH_K_VALUES
        )

        print()

        print(
            "Vybrane casy pro evaluaci:"
        )

        for timestamp in evaluation_times:
            print(
                " ",
                timestamp.isoformat()
            )

        if discovery_skipped:
            print()
            print(
                "Dny bez kompletniho +180 min outcome:"
            )

            for item in discovery_skipped:
                print(
                    f"  {item['date']} "
                    f"-> "
                    f"{item['reason']}"
                )

        print()

        result = evaluate_batch(
            db=db,
            user_id=user.id,
            evaluation_times=
                evaluation_times,
            k_values=
                DEFAULT_BATCH_K_VALUES
        )

        print(
            "=" * 78
        )

        print(
            "Pozadovanych evaluaci:",
            result[
                "requested_evaluation_count"
            ]
        )

        print(
            "Pouzitych evaluaci:",
            result[
                "evaluated_count"
            ]
        )

        print(
            "Preskocenych kvuli historii:",
            result[
                "skipped_count"
            ]
        )

        aggregate = (
            result[
                "aggregate"
            ]
        )

        aggregate_results = (
            aggregate[
                "results"
            ]
        )

        print()
        print(
            "=" * 78
        )

        print(
            "ZAKLADNI PREHLED"
        )

        print(
            "=" * 78
        )

        print(
            f"{'K':<8}"
            f"{'EVALS':<10}"
            f"{'AVG MAE MEDIAN':<18}"
            f"{'AVG MAE WEIGHTED':<20}"
            f"{'AVG RANK':<14}"
        )

        print(
            "-" * 78
        )

        for item in aggregate_results:
            print(
                f"{item['k']:<8}"
                f"{item['evaluation_count']:<10}"
                f"{_format_number(item['average_mae_median']):<18}"
                f"{_format_number(item['average_mae_weighted_mean']):<20}"
                f"{_format_number(item['average_ranking_score']):<14}"
            )

        best_median = (
            _best_k_values(
                aggregate_results,
                "average_mae_median"
            )
        )

        best_weighted = (
            _best_k_values(
                aggregate_results,
                "average_mae_weighted_mean"
            )
        )

        print()
        print(
            "Nejlepsi K podle "
            "prumerneho median MAE:",
            _format_k_list(
                best_median
            )
        )

        print(
            "Nejlepsi K podle "
            "prumerneho weighted MAE:",
            _format_k_list(
                best_weighted
            )
        )

        _print_method_statistics(
            title=(
                "DETAILNI STATISTIKY - "
                "MEDIAN PREDICTION"
            ),
            aggregate_results=
                aggregate_results,
            method_key=
                "median_method"
        )

        _print_method_statistics(
            title=(
                "DETAILNI STATISTIKY - "
                "WEIGHTED MEAN PREDICTION"
            ),
            aggregate_results=
                aggregate_results,
            method_key=
                "weighted_mean_method"
        )

        _print_horizon_statistics(
            title=(
                "PRUMERNE MAE PODLE HORIZONTU - "
                "MEDIAN PREDICTION"
            ),
            aggregate_results=
                aggregate_results,
            prediction_key=
                "median_prediction"
        )

        _print_horizon_statistics(
            title=(
                "PRUMERNE MAE PODLE HORIZONTU - "
                "WEIGHTED MEAN PREDICTION"
            ),
            aggregate_results=
                aggregate_results,
            prediction_key=
                "weighted_mean_prediction"
        )

        _print_best_horizon_values(
            aggregate_results
        )

        print()

        if result["skipped"]:
            reasons = Counter(
                item["reason"]
                for item
                in result[
                    "skipped"
                ]
            )

            print(
                "=" * 78
            )

            print(
                "DUVODY PRESKOCENI"
            )

            print(
                "=" * 78
            )

            for (
                reason,
                count
            ) in reasons.items():
                print(
                    f"  {reason}: "
                    f"{count}"
                )

            print()
            print(
                "Preskocene situace:"
            )

            for item in result[
                "skipped"
            ]:
                line = (
                    f"  "
                    f"{item['timestamp']} "
                    f"-> "
                    f"{item['reason']}"
                )

                if (
                    "insufficient_k"
                    in item
                ):
                    line += (
                        f" "
                        f"{item['insufficient_k']}"
                    )

                print(
                    line
                )

        print()
        print(
            "=" * 78
        )

        print(
            "JEDNOTLIVE POUZITE EVALUACE"
        )

        print(
            "=" * 78
        )

        for evaluation in result[
            "evaluations"
        ]:
            print()
            print(
                evaluation[
                    "evaluation_timestamp"
                ]
            )

            for item in evaluation[
                "results"
            ]:
                print(
                    f"  "
                    f"K={item['k_requested']:<2} "
                    f"median MAE="
                    f"{_format_number(item['mae_median'])} "
                    f"weighted MAE="
                    f"{_format_number(item['mae_weighted_mean'])} "
                    f"avg rank="
                    f"{_format_number(item['average_ranking_score'])}"
                )

    finally:
        db.close()


if __name__ == "__main__":
    main()