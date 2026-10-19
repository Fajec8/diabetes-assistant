from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User
from app.services.evaluation import (
    DEFAULT_K_VALUES,
    evaluate_k_values,
)


TEST_USER_EMAIL = "test@example.com"

EVALUATION_TIMESTAMP = datetime(
    2026,
    10,
    2,
    13,
    30,
    tzinfo=ZoneInfo(
        "Europe/Prague"
    )
)


def _format_number(
    value
):
    if value is None:
        return "-"

    return f"{value:.2f}"


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

        result = evaluate_k_values(
            db=db,
            user_id=user.id,
            t0=EVALUATION_TIMESTAMP,
            k_values=DEFAULT_K_VALUES
        )

        print()
        print(
            "EVALUACE POCTU PODOBNYCH SITUACI"
        )

        print(
            "=" * 72
        )

        print(
            "Cas evaluace:",
            result[
                "evaluation_timestamp"
            ]
        )

        print()

        actual = result[
            "actual_outcome"
        ]

        print(
            "Skutecny vyvoj glykemie:"
        )

        print(
            f"  +30 min:  "
            f"{_format_number(actual.get('delta_30m'))} mmol/l"
        )

        print(
            f"  +60 min:  "
            f"{_format_number(actual.get('delta_60m'))} mmol/l"
        )

        print(
            f"  +90 min:  "
            f"{_format_number(actual.get('delta_90m'))} mmol/l"
        )

        print(
            f"  +120 min: "
            f"{_format_number(actual.get('delta_120m'))} mmol/l"
        )

        print(
            f"  +180 min: "
            f"{_format_number(actual.get('delta_180m'))} mmol/l"
        )

        print()
        print(
            "=" * 72
        )

        print(
            f"{'K':<6}"
            f"{'FOUND':<8}"
            f"{'MAE MEDIAN':<14}"
            f"{'MAE WEIGHTED':<16}"
            f"{'AVG RANK':<12}"
            f"{'EVIDENCE':<10}"
        )

        print(
            "-" * 72
        )

        for item in result[
            "results"
        ]:
            print(
                f"{item['k_requested']:<6}"
                f"{item['k_found']:<8}"
                f"{_format_number(item['mae_median']):<14}"
                f"{_format_number(item['mae_weighted_mean']):<16}"
                f"{_format_number(item['average_ranking_score']):<12}"
                f"{item['evidence_quality']:<10}"
            )

        print()
        print(
            "=" * 72
        )

        valid_results = [
            item
            for item in result[
                "results"
            ]
            if (
                item[
                    "mae_weighted_mean"
                ]
                is not None
            )
        ]

        if valid_results:
            best_weighted = min(
                valid_results,
                key=lambda item:
                    item[
                        "mae_weighted_mean"
                    ]
            )

            best_median = min(
                valid_results,
                key=lambda item:
                    item[
                        "mae_median"
                    ]
                if (
                    item[
                        "mae_median"
                    ]
                    is not None
                )
                else float("inf")
            )

            print(
                "Nejlepsi weighted mean:"
            )

            print(
                f"  K = "
                f"{best_weighted['k_requested']}"
            )

            print(
                f"  nalezeno = "
                f"{best_weighted['k_found']}"
            )

            print(
                f"  MAE = "
                f"{_format_number(best_weighted['mae_weighted_mean'])} mmol/l"
            )

            print()

            print(
                "Nejlepsi median:"
            )

            print(
                f"  K = "
                f"{best_median['k_requested']}"
            )

            print(
                f"  nalezeno = "
                f"{best_median['k_found']}"
            )

            print(
                f"  MAE = "
                f"{_format_number(best_median['mae_median'])} mmol/l"
            )

        print()
        print(
            "Detail jednotlivych horizontu:"
        )

        for item in result[
            "results"
        ]:
            print()
            print(
                f"K = {item['k_requested']} "
                f"(nalezeno {item['k_found']})"
            )

            for (
                horizon,
                horizon_result
            ) in item[
                "horizons"
            ].items():

                print(
                    f"  {horizon:<5} "
                    f"actual="
                    f"{_format_number(horizon_result['actual_delta']):>6} "
                    f"median="
                    f"{_format_number(horizon_result['predicted_median']):>6} "
                    f"weighted="
                    f"{_format_number(horizon_result['predicted_weighted_mean']):>6} "
                    f"err_median="
                    f"{_format_number(horizon_result['absolute_error_median']):>5} "
                    f"err_weighted="
                    f"{_format_number(horizon_result['absolute_error_weighted_mean']):>5}"
                )

    finally:
        db.close()


if __name__ == "__main__":
    main()