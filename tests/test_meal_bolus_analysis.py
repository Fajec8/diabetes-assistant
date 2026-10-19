import uuid
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.meal_bolus_analysis import (
    build_meal_bolus_analysis,
)


TZ = ZoneInfo(
    "Europe/Prague"
)


def _meal():
    return SimpleNamespace(
        id=uuid.uuid4(),

        eaten_at=datetime(
            2026,
            10,
            18,
            13,
            0,
            tzinfo=TZ
        ),

        carbohydrates_g=70.0
    )


def _dose(
    units,
    hour,
    minute
):
    return SimpleNamespace(
        id=uuid.uuid4(),

        units=units,

        administered_at=datetime(
            2026,
            10,
            18,
            hour,
            minute,
            tzinfo=TZ
        )
    )


def test_split_bolus_analysis():
    meal = _meal()

    doses = [
        _dose(
            units=4.0,
            hour=12,
            minute=45
        ),
        _dose(
            units=2.0,
            hour=13,
            minute=40
        )
    ]

    result = (
        build_meal_bolus_analysis(
            meal=meal,
            doses=doses
        )
    )

    assert (
        result[
            "strategy"
        ]
        == "SPLIT"
    )

    assert (
        result[
            "dose_count"
        ]
        == 2
    )

    assert (
        result[
            "total_bolus_units"
        ]
        == 6.0
    )

    assert (
        result[
            "prebolus_minutes"
        ]
        == 15.0
    )

    assert (
        result[
            "first_dose_relative_minutes"
        ]
        == -15.0
    )

    assert (
        result[
            "split_ratio"
        ]
        == "2/3 + 1/3"
    )

    assert (
        result[
            "doses"
        ][0][
            "percentage_of_total"
        ]
        == 66.7
    )

    assert (
        result[
            "doses"
        ][1][
            "percentage_of_total"
        ]
        == 33.3
    )

    assert (
        result[
            "doses"
        ][1][
            "relative_to_meal_minutes"
        ]
        == 40.0
    )


def test_single_bolus_analysis():
    meal = _meal()

    doses = [
        _dose(
            units=6.0,
            hour=12,
            minute=50
        )
    ]

    result = (
        build_meal_bolus_analysis(
            meal=meal,
            doses=doses
        )
    )

    assert (
        result[
            "strategy"
        ]
        == "SINGLE"
    )

    assert (
        result[
            "dose_count"
        ]
        == 1
    )

    assert (
        result[
            "total_bolus_units"
        ]
        == 6.0
    )

    assert (
        result[
            "prebolus_minutes"
        ]
        == 10.0
    )

    assert (
        result[
            "split"
        ]
        is False
    )

    assert (
        result[
            "split_ratio"
        ]
        is None
    )


def test_bolus_after_meal_has_zero_prebolus():
    meal = _meal()

    doses = [
        _dose(
            units=6.0,
            hour=13,
            minute=10
        )
    ]

    result = (
        build_meal_bolus_analysis(
            meal=meal,
            doses=doses
        )
    )

    assert (
        result[
            "prebolus_minutes"
        ]
        == 0.0
    )

    assert (
        result[
            "first_dose_relative_minutes"
        ]
        == 10.0
    )


def test_meal_without_linked_bolus():
    meal = _meal()

    result = (
        build_meal_bolus_analysis(
            meal=meal,
            doses=[]
        )
    )

    assert (
        result[
            "strategy"
        ]
        == "NO_LINKED_BOLUS"
    )

    assert (
        result[
            "dose_count"
        ]
        == 0
    )

    assert (
        result[
            "total_bolus_units"
        ]
        == 0.0
    )

    assert (
        result[
            "prebolus_minutes"
        ]
        is None
    )


def test_analysis_as_of_excludes_future_split_part():
    meal = _meal()

    doses = [
        _dose(
            units=4.0,
            hour=12,
            minute=45
        ),
        _dose(
            units=2.0,
            hour=13,
            minute=40
        )
    ]

    as_of = datetime(
        2026,
        10,
        18,
        13,
        20,
        tzinfo=TZ
    )

    result = (
        build_meal_bolus_analysis(
            meal=meal,
            doses=doses,
            as_of=as_of
        )
    )

    assert (
        result[
            "dose_count"
        ]
        == 1
    )

    assert (
        result[
            "strategy"
        ]
        == "SINGLE"
    )

    assert (
        result[
            "total_bolus_units"
        ]
        == 4.0
    )

    assert (
        result[
            "split"
        ]
        is False
    )


def test_analysis_as_of_includes_second_part_after_it_happens():
    meal = _meal()

    doses = [
        _dose(
            units=4.0,
            hour=12,
            minute=45
        ),
        _dose(
            units=2.0,
            hour=13,
            minute=40
        )
    ]

    as_of = datetime(
        2026,
        10,
        18,
        14,
        0,
        tzinfo=TZ
    )

    result = (
        build_meal_bolus_analysis(
            meal=meal,
            doses=doses,
            as_of=as_of
        )
    )

    assert (
        result[
            "dose_count"
        ]
        == 2
    )

    assert (
        result[
            "strategy"
        ]
        == "SPLIT"
    )

    assert (
        result[
            "total_bolus_units"
        ]
        == 6.0
    )

    assert (
        result[
            "split_ratio"
        ]
        == "2/3 + 1/3"
    )