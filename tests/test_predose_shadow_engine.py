from zoneinfo import ZoneInfo

from app.services.predose_shadow_engine import (
    build_current_situation_from_snapshot,
)


def test_build_current_shadow_situation():
    snapshot = {
        "decision_at":
            "2026-10-27T20:00:00+01:00",

        "glucose": {
            "current": 10.0,
            "delta_15m": 0.5,
            "delta_30m": 1.0,
            "delta_60m": 2.0,
            "trend": "RISING",
        },

        "planned_meal":
            None,

        "recent_novorapid": [
            {
                "units": 4.0,
                "administered_at":
                    "2026-10-27T19:00:00+01:00",
            },
            {
                "units": 2.0,
                "administered_at":
                    "2026-10-27T17:00:00+01:00",
            },
        ],

        "tresiba": {
            "units": 20.0,
            "administered_at":
                "2026-10-26T22:00:00+01:00",
        },

        "activities": [],

        "note":
            "test",
    }

    situation = (
        build_current_situation_from_snapshot(
            input_snapshot=
                snapshot,

            timezone=
                ZoneInfo(
                    "Europe/Prague"
                ),
        )
    )

    assert (
        situation[
            "glucose"
        ][
            "current"
        ]
        == 10.0
    )

    assert (
        situation[
            "novorapid"
        ][
            "last_bolus_units"
        ]
        == 4.0
    )

    assert (
        situation[
            "novorapid"
        ][
            "minutes_since_last_bolus"
        ]
        == 60
    )

    assert (
        situation[
            "novorapid"
        ][
            "units_last_2h"
        ]
        == 4.0
    )

    assert (
        situation[
            "novorapid"
        ][
            "units_last_4h"
        ]
        == 6.0
    )

    assert (
        situation[
            "novorapid"
        ][
            "estimated_active_units"
        ]
        == 3.5
    )

    assert (
        situation[
            "tresiba"
        ][
            "last_basal_units"
        ]
        == 20.0
    )