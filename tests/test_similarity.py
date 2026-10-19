from copy import deepcopy

from app.services.similarity import (
    compare_situations,
)


BASE_SITUATION = {
    "glucose": {
        "current": 7.2,
        "delta_15m": -0.4,
        "delta_30m": -0.9,
        "delta_60m": -1.7,

        "data_quality": {
            "window_minutes": 120,
            "expected_interval_minutes": 5,
            "expected_readings": 25,
            "actual_readings": 25,
            "coverage_percent": 100.0,
            "max_gap_minutes": 5.0
        }
    },

    "meal": {
        "last_meal_carbs": 60,
        "minutes_since_last_meal": 90,
        "carbs_last_2h": 60,
        "carbs_last_4h": 60
    },

    "novorapid": {
        "last_bolus_units": 6,
        "minutes_since_last_bolus": 85,
        "units_last_2h": 6,
        "units_last_4h": 6,
        "units_last_6h": 6,
        "estimated_active_units": 3.88
    },

    "activity": {
        "type": "GYM",
        "intensity": "MEDIUM",
        "duration_minutes": 120,
        "minutes_since_end": 150,
        "minutes_last_6h": 120,
        "minutes_6_24h": 0,
        "minutes_24_48h": 120
    },

    "tresiba": {
        "last_basal_units": 16,
        "minutes_since_last_basal": 930
    },

    "time": {
        "minutes_from_midnight": 810
    }
}


def test_identical_situations_are_100_percent_similar():
    result = compare_situations(
        BASE_SITUATION,
        deepcopy(
            BASE_SITUATION
        )
    )

    assert (
        result["similarity_score"]
        == 100.0
    )

    assert (
        result["data_coverage"]
        == 100.0
    )


def test_different_time_reduces_similarity():
    other = deepcopy(
        BASE_SITUATION
    )

    other["time"][
        "minutes_from_midnight"
    ] = 1080

    result = compare_situations(
        BASE_SITUATION,
        other
    )

    assert (
        result["similarity_score"]
        < 100.0
    )

    assert (
        result["components"]["time"]
        < 100.0
    )


def test_close_time_has_high_priority():
    other = deepcopy(
        BASE_SITUATION
    )

    other["time"][
        "minutes_from_midnight"
    ] = 800

    result = compare_situations(
        BASE_SITUATION,
        other
    )

    assert (
        result["components"]["time"]
        > 95.0
    )


def test_missing_data_reduces_coverage():
    other = deepcopy(
        BASE_SITUATION
    )

    other["activity"][
        "intensity"
    ] = None

    other["activity"][
        "duration_minutes"
    ] = None

    other["activity"][
        "minutes_since_end"
    ] = None

    other["activity"][
        "minutes_last_6h"
    ] = None

    other["activity"][
        "minutes_6_24h"
    ] = None

    other["activity"][
        "minutes_24_48h"
    ] = None

    result = compare_situations(
        BASE_SITUATION,
        other
    )

    assert (
        result["data_coverage"]
        < 100.0
    )

    # Z recent activity části
    # zůstává dostupný pouze type:
    #
    # recent coverage:
    # 1 / 5 = 20 %
    #
    # recent část má váhu 70 %:
    # 0.20 * 0.70 = 14 %
    #
    # obě starší části chybí.
    assert (
        result[
            "component_coverage"
        ]["activity"]
        == 14.0
    )


def test_low_cgm_coverage_reduces_glucose_coverage():
    other = deepcopy(
        BASE_SITUATION
    )

    other[
        "glucose"
    ][
        "data_quality"
    ][
        "actual_readings"
    ] = 10

    other[
        "glucose"
    ][
        "data_quality"
    ][
        "coverage_percent"
    ] = 40.0

    other[
        "glucose"
    ][
        "data_quality"
    ][
        "max_gap_minutes"
    ] = 45.0

    result = compare_situations(
        BASE_SITUATION,
        other
    )

    assert (
        result[
            "component_coverage"
        ]["glucose"]
        == 30.0
    )

    assert (
        result["data_coverage"]
        < 100.0
    )


def test_large_cgm_gap_reduces_quality_even_with_full_count():
    other = deepcopy(
        BASE_SITUATION
    )

    other[
        "glucose"
    ][
        "data_quality"
    ][
        "actual_readings"
    ] = 25

    other[
        "glucose"
    ][
        "data_quality"
    ][
        "coverage_percent"
    ] = 100.0

    other[
        "glucose"
    ][
        "data_quality"
    ][
        "max_gap_minutes"
    ] = 35.0

    result = compare_situations(
        BASE_SITUATION,
        other
    )

    assert (
        result[
            "component_coverage"
        ]["glucose"]
        == 50.0
    )

    assert (
        result["data_coverage"]
        < 100.0
    )


def test_active_novorapid_affects_similarity():
    other = deepcopy(
        BASE_SITUATION
    )

    other["novorapid"][
        "estimated_active_units"
    ] = 0.0

    result = compare_situations(
        BASE_SITUATION,
        other
    )

    assert (
        result[
            "components"
        ]["novorapid"]
        < 100.0
    )


def test_activity_intensity_affects_similarity():
    other = deepcopy(
        BASE_SITUATION
    )

    other["activity"][
        "intensity"
    ] = "HIGH"

    result = compare_situations(
        BASE_SITUATION,
        other
    )

    # Recent activity:
    #
    # MEDIUM vs HIGH
    # = 50 % similarity intensity.
    #
    # Ostatní 4 recent údaje
    # jsou stejné:
    #
    # (100 + 50 + 100 + 100 + 100)
    # / 5
    # = 90 %
    #
    # Celková activity component:
    #
    # 90 % * 0.70
    # + 100 % * 0.20
    # + 100 % * 0.10
    # = 93 %
    assert (
        result[
            "components"
        ]["activity"]
        == 93.0
    )

    assert (
        result["similarity_score"]
        < 100.0
    )


def test_activity_6_24h_affects_similarity():
    other = deepcopy(
        BASE_SITUATION
    )

    other["activity"][
        "minutes_6_24h"
    ] = 120

    result = compare_situations(
        BASE_SITUATION,
        other
    )

    assert (
        result[
            "components"
        ]["activity"]
        < 100.0
    )

    assert (
        result["similarity_score"]
        < 100.0
    )


def test_activity_24_48h_affects_similarity():
    other = deepcopy(
        BASE_SITUATION
    )

    other["activity"][
        "minutes_24_48h"
    ] = 0

    result = compare_situations(
        BASE_SITUATION,
        other
    )

    # Rozdíl je 120 minut.
    # Scale je 240 minut:
    #
    # history similarity = 50 %
    #
    # Tato část má 10 %
    # activity váhy, takže:
    #
    # 100 * 0.70
    # + 100 * 0.20
    # + 50 * 0.10
    # = 95 %
    assert (
        result[
            "components"
        ]["activity"]
        == 95.0
    )

    assert (
        result["similarity_score"]
        < 100.0
    )