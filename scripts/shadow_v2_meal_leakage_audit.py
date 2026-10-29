from __future__ import annotations

import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import (
    func,
    select,
)

from app.database import SessionLocal
from app.models.glucose import GlucoseReading
from app.models.user import User
from app.services.meal_shadow_engine_v2 import (
    MODEL_VERSION,
    _build_planned_meal_reference_situation,
    _meal_reference_groups,
    estimate_meal_linked_shadow_action,
)
from app.services.predose_shadow_engine import (
    CLARITY_SOURCE,
    HISTORY_DAYS,
    HORIZONS,
    REFERENCE_SAFETY_HOURS,
    _nearest_glucose_value,
    _parse_datetime,
    _prepare_real_cache,
    build_current_situation_from_snapshot,
)
from scripts.shadow_v2_meal_historical_replay import (
    EVALUATION_DAYS,
    EVALUATION_END_GAP_HOURS,
    _build_hidden_target_snapshot,
    _decision_time,
)


USER_ID = uuid.UUID(
    "d78bf688-ec52-495c-b390-9e6747fedb47"
)

FORBIDDEN_TARGET_KEYS = {
    "actual_units",
    "target_units",
    "target_dose",
    "target_dose_units",
    "historical_target_units",
    "outcome",
    "outcomes",
    "glucose_30m",
    "glucose_60m",
    "glucose_90m",
    "glucose_120m",
    "glucose_180m",
    "delta_30m_outcome",
    "delta_60m_outcome",
    "delta_90m_outcome",
    "delta_120m_outcome",
    "delta_180m_outcome",
}


class Audit:
    def __init__(self):
        self.checks = 0
        self.violations = []

    def check(
        self,
        condition: bool,
        code: str,
        details: str,
    ) -> None:
        self.checks += 1

        if not condition:
            self.violations.append(
                {
                    "code": code,
                    "details": details,
                }
            )


def _contains_value(
    value,
    target: str,
) -> bool:
    if isinstance(
        value,
        dict,
    ):
        return any(
            _contains_value(
                nested,
                target,
            )
            for nested
            in value.values()
        )

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):
        return any(
            _contains_value(
                nested,
                target,
            )
            for nested
            in value
        )

    return (
        str(
            value
        )
        == target
    )


def _find_forbidden_keys(
    value,
    path: str = "",
) -> list[str]:
    found = []

    if isinstance(
        value,
        dict,
    ):
        for (
            key,
            nested,
        ) in value.items():
            current_path = (
                f"{path}.{key}"
                if path
                else str(
                    key
                )
            )

            if (
                key
                in FORBIDDEN_TARGET_KEYS
            ):
                found.append(
                    current_path
                )

            found.extend(
                _find_forbidden_keys(
                    nested,
                    current_path,
                )
            )

    elif isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        for (
            index,
            nested,
        ) in enumerate(
            value
        ):
            found.extend(
                _find_forbidden_keys(
                    nested,
                    (
                        f"{path}"
                        f"[{index}]"
                    ),
                )
            )

    return found


def _build_reference_lookup(
    cache,
    candidate_start,
    candidate_end,
    timezone,
) -> dict:
    lookup = {}

    groups = (
        _meal_reference_groups(
            cache=cache,
            candidate_start=
                candidate_start,
            candidate_end=
                candidate_end,
        )
    )

    for group in groups:
        (
            reference_t0,
            situation,
        ) = (
            _build_planned_meal_reference_situation(
                cache=cache,
                meal=
                    group[
                        "meal"
                    ],
                first_dose=
                    group[
                        "first_dose"
                    ],
                timezone=
                    timezone,
            )
        )

        lookup[
            reference_t0.isoformat()
        ] = {
            "group": group,
            "situation": situation,
        }

    return lookup


def main() -> None:
    db = SessionLocal()

    audit = Audit()

    target_count = 0
    estimated_count = 0
    abstain_count = 0

    reference_groups_checked = 0
    evidence_matches_checked = 0

    target_id_leaks = 0
    target_outcome_leaks = 0
    linked_bolus_leaks = 0
    reference_safety_violations = 0
    reference_label_timing_violations = 0
    evidence_safety_violations = 0
    outcome_horizon_violations = 0
    glucose_asof_violations = 0

    try:
        user = db.get(
            User,
            USER_ID,
        )

        if user is None:
            raise RuntimeError(
                "User not found"
            )

        timezone = ZoneInfo(
            user.timezone
        )

        latest_real_time = db.scalar(
            select(
                func.max(
                    GlucoseReading.measured_at
                )
            )
            .where(
                GlucoseReading.user_id
                == USER_ID,

                GlucoseReading.source
                == CLARITY_SOURCE,
            )
        )

        if latest_real_time is None:
            raise RuntimeError(
                "No Dexcom Clarity glucose found"
            )

        evaluation_end = (
            latest_real_time
            - timedelta(
                hours=
                    EVALUATION_END_GAP_HOURS
            )
        )

        evaluation_start = (
            evaluation_end
            - timedelta(
                days=
                    EVALUATION_DAYS
            )
        )

        preload_start = (
            evaluation_start
            - timedelta(
                hours=48
            )
        )

        target_cache = (
            _prepare_real_cache(
                db=db,
                user_id=
                    USER_ID,
                search_t0=
                    latest_real_time,
                preload_start=
                    preload_start,
            )
        )

        target_groups = (
            _meal_reference_groups(
                cache=
                    target_cache,

                candidate_start=
                    evaluation_start,

                candidate_end=
                    evaluation_end,
            )
        )

        target_groups.sort(
            key=
                _decision_time,
            reverse=True,
        )

        print()
        print(
            "=" * 120
        )

        print(
            "SHADOW V2 MEAL - LEAKAGE AUDIT"
        )

        print(
            "=" * 120
        )

        print(
            "Model:",
            MODEL_VERSION,
        )

        print(
            "Targets:",
            len(
                target_groups
            ),
        )

        print(
            "Safety gap:",
            REFERENCE_SAFETY_HOURS,
            "hours",
        )

        print(
            "Maximum historical outcome horizon:",
            max(
                HORIZONS
            ),
            "minutes",
        )

        print()

        for (
            index,
            group,
        ) in enumerate(
            target_groups,
            start=1,
        ):
            target_count += 1

            (
                decision_t0,
                input_snapshot,
            ) = (
                _build_hidden_target_snapshot(
                    cache=
                        target_cache,

                    group=
                        group,

                    timezone=
                        timezone,
                )
            )

            target_doses = (
                group[
                    "linked_doses"
                ]
            )

            target_dose_ids = {
                str(
                    dose.id
                )
                for dose
                in target_doses
            }

            target_total_units = float(
                group[
                    "total_units"
                ]
            )

            local_time = (
                decision_t0
                .astimezone(
                    timezone
                )
            )

            print(
                f"{index:>2}. "
                f"{local_time.isoformat()} | "
                f"carbs="
                f"{float(group['meal'].carbohydrates_g):>5.1f} | "
                f"hidden target="
                f"{target_total_units:>4.1f} U",
                end="",
            )

            snapshot_decision_t0 = (
                _parse_datetime(
                    input_snapshot[
                        "decision_at"
                    ]
                )
            )

            audit.check(
                snapshot_decision_t0
                == decision_t0,

                "TARGET_DECISION_TIME_MISMATCH",

                (
                    f"Target {index}: "
                    f"snapshot decision_at "
                    f"{snapshot_decision_t0} "
                    f"!= expected "
                    f"{decision_t0}"
                ),
            )

            forbidden_keys = (
                _find_forbidden_keys(
                    input_snapshot
                )
            )

            if forbidden_keys:
                target_outcome_leaks += 1

            audit.check(
                not forbidden_keys,

                "TARGET_FUTURE_FIELD_EXPOSED",

                (
                    f"Target {index}: "
                    f"forbidden fields in "
                    f"input snapshot: "
                    f"{forbidden_keys}"
                ),
            )

            for target_id in target_dose_ids:
                leaked = (
                    _contains_value(
                        input_snapshot,
                        target_id,
                    )
                )

                if leaked:
                    target_id_leaks += 1

                audit.check(
                    not leaked,

                    "TARGET_DOSE_ID_EXPOSED",

                    (
                        f"Target {index}: "
                        f"target dose id "
                        f"{target_id} "
                        f"appears in estimator "
                        f"input snapshot"
                    ),
                )

            planned_meal = (
                input_snapshot.get(
                    "planned_meal"
                )
                or {}
            )

            audit.check(
                "actual_units"
                not in planned_meal
                and "target_units"
                not in planned_meal
                and "dose_units"
                not in planned_meal
                and "linked_bolus"
                not in planned_meal,

                "TARGET_DOSE_VALUE_EXPOSED",

                (
                    f"Target {index}: "
                    "planned_meal contains "
                    "a target-dose field"
                ),
            )

            for dose in target_doses:
                audit.check(
                    dose.administered_at
                    > decision_t0,

                    "TARGET_DOSE_NOT_FUTURE",

                    (
                        f"Target {index}: "
                        f"hidden dose "
                        f"{dose.id} at "
                        f"{dose.administered_at} "
                        f"is not after "
                        f"decision_t0 "
                        f"{decision_t0}"
                    ),
                )

            current_situation = (
                build_current_situation_from_snapshot(
                    input_snapshot=
                        input_snapshot,

                    timezone=
                        timezone,
                )
            )

            current_linked_bolus = (
                current_situation[
                    "meal"
                ].get(
                    "linked_bolus"
                )
            )

            if (
                current_linked_bolus
                is not None
            ):
                linked_bolus_leaks += 1

            audit.check(
                current_linked_bolus
                is None,

                "TARGET_LINKED_BOLUS_EXPOSED",

                (
                    f"Target {index}: "
                    f"current situation "
                    f"linked_bolus="
                    f"{current_linked_bolus}"
                ),
            )

            result = (
                estimate_meal_linked_shadow_action(
                    db=db,

                    user_id=
                        USER_ID,

                    input_snapshot=
                        input_snapshot,
                )
            )

            if (
                result[
                    "status"
                ]
                == "ESTIMATED"
            ):
                estimated_count += 1

            else:
                abstain_count += 1

            history_preload_start = (
                decision_t0
                - timedelta(
                    days=
                        HISTORY_DAYS,

                    hours=2,
                )
            )

            candidate_start = (
                decision_t0
                - timedelta(
                    days=
                        HISTORY_DAYS
                )
            )

            candidate_end = (
                decision_t0
                - timedelta(
                    hours=
                        REFERENCE_SAFETY_HOURS
                )
            )

            history_cache = (
                _prepare_real_cache(
                    db=db,

                    user_id=
                        USER_ID,

                    search_t0=
                        decision_t0,

                    preload_start=
                        history_preload_start,
                )
            )

            reference_lookup = (
                _build_reference_lookup(
                    cache=
                        history_cache,

                    candidate_start=
                        candidate_start,

                    candidate_end=
                        candidate_end,

                    timezone=
                        timezone,
                )
            )

            reference_groups_checked += len(
                reference_lookup
            )

            for (
                reference_iso,
                reference,
            ) in reference_lookup.items():
                reference_t0 = (
                    _parse_datetime(
                        reference_iso
                    )
                )

                reference_group = (
                    reference[
                        "group"
                    ]
                )

                reference_situation = (
                    reference[
                        "situation"
                    ]
                )

                safe = (
                    reference_t0
                    < candidate_end
                )

                if not safe:
                    reference_safety_violations += 1

                audit.check(
                    safe,

                    "REFERENCE_SAFETY_GAP_VIOLATION",

                    (
                        f"Target {index}: "
                        f"reference "
                        f"{reference_t0} "
                        f"is not older than "
                        f"safety boundary "
                        f"{candidate_end}"
                    ),
                )

                audit.check(
                    reference_t0
                    < decision_t0,

                    "REFERENCE_NOT_HISTORICAL",

                    (
                        f"Target {index}: "
                        f"reference "
                        f"{reference_t0} "
                        f"is not before "
                        f"target "
                        f"{decision_t0}"
                    ),
                )

                ref_linked_bolus = (
                    reference_situation[
                        "meal"
                    ].get(
                        "linked_bolus"
                    )
                )

                if (
                    ref_linked_bolus
                    is not None
                ):
                    linked_bolus_leaks += 1

                audit.check(
                    ref_linked_bolus
                    is None,

                    "REFERENCE_LINKED_BOLUS_EXPOSED",

                    (
                        f"Target {index}: "
                        f"reference "
                        f"{reference_t0} "
                        f"contains linked_bolus="
                        f"{ref_linked_bolus}"
                    ),
                )

                for dose in (
                    reference_group[
                        "linked_doses"
                    ]
                ):
                    label_is_future = (
                        dose.administered_at
                        > reference_t0
                    )

                    if not label_is_future:
                        (
                            reference_label_timing_violations
                        ) += 1

                    audit.check(
                        label_is_future,

                        "REFERENCE_LABEL_VISIBLE_AT_DECISION",

                        (
                            f"Target {index}: "
                            f"reference dose "
                            f"{dose.id} at "
                            f"{dose.administered_at} "
                            f"is not after "
                            f"reference t0 "
                            f"{reference_t0}"
                        ),
                    )

                    audit.check(
                        str(
                            dose.id
                        )
                        not in target_dose_ids,

                        "TARGET_DOSE_USED_AS_REFERENCE",

                        (
                            f"Target {index}: "
                            f"target dose "
                            f"{dose.id} "
                            f"appeared inside "
                            f"reference group"
                        ),
                    )

                    audit.check(
                        dose.administered_at
                        < decision_t0,

                        "REFERENCE_LABEL_AFTER_TARGET",

                        (
                            f"Target {index}: "
                            f"reference label "
                            f"{dose.id} at "
                            f"{dose.administered_at} "
                            f"is not historical "
                            f"relative to target "
                            f"{decision_t0}"
                        ),
                    )

                maximum_outcome_time = (
                    reference_t0
                    + timedelta(
                        minutes=
                            max(
                                HORIZONS
                            )
                    )
                )

                outcome_safe = (
                    maximum_outcome_time
                    < decision_t0
                )

                if not outcome_safe:
                    outcome_horizon_violations += 1

                audit.check(
                    outcome_safe,

                    "REFERENCE_OUTCOME_CROSSES_TARGET_TIME",

                    (
                        f"Target {index}: "
                        f"reference "
                        f"{reference_t0} "
                        f"outcome horizon ends "
                        f"{maximum_outcome_time}, "
                        f"target is "
                        f"{decision_t0}"
                    ),
                )

                expected_glucose = (
                    _nearest_glucose_value(
                        history_cache.glucose_readings,

                        history_cache.glucose_times,

                        reference_t0,

                        past_only=True,
                    )
                )

                observed_glucose = (
                    reference_situation[
                        "glucose"
                    ].get(
                        "current"
                    )
                )

                glucose_matches = (
                    expected_glucose
                    == observed_glucose
                )

                if not glucose_matches:
                    glucose_asof_violations += 1

                audit.check(
                    glucose_matches,

                    "REFERENCE_CURRENT_GLUCOSE_NOT_ASOF",

                    (
                        f"Target {index}: "
                        f"reference "
                        f"{reference_t0}: "
                        f"expected past-only "
                        f"glucose "
                        f"{expected_glucose}, "
                        f"observed "
                        f"{observed_glucose}"
                    ),
                )

            snapshot = (
                result.get(
                    "evidence_snapshot"
                )
                or {}
            )

            matches = (
                snapshot.get(
                    "matches"
                )
                or []
            )

            evidence_matches_checked += len(
                matches
            )

            for match in matches:
                match_t0 = (
                    _parse_datetime(
                        match[
                            "decision_at"
                        ]
                    )
                )

                match_safe = (
                    match_t0
                    < candidate_end
                )

                if not match_safe:
                    evidence_safety_violations += 1

                audit.check(
                    match_safe,

                    "USED_MATCH_SAFETY_GAP_VIOLATION",

                    (
                        f"Target {index}: "
                        f"USED match "
                        f"{match_t0} "
                        f"is newer than "
                        f"safety boundary "
                        f"{candidate_end}"
                    ),
                )

                match_outcome_end = (
                    match_t0
                    + timedelta(
                        minutes=
                            max(
                                HORIZONS
                            )
                    )
                )

                match_outcome_safe = (
                    match_outcome_end
                    < decision_t0
                )

                if not match_outcome_safe:
                    outcome_horizon_violations += 1

                audit.check(
                    match_outcome_safe,

                    "USED_MATCH_OUTCOME_CROSSES_TARGET_TIME",

                    (
                        f"Target {index}: "
                        f"USED match "
                        f"{match_t0} "
                        f"has maximum outcome "
                        f"time "
                        f"{match_outcome_end} "
                        f"after target "
                        f"{decision_t0}"
                    ),
                )

                reference = (
                    reference_lookup.get(
                        match[
                            "decision_at"
                        ]
                    )
                )

                audit.check(
                    reference is not None,

                    "USED_MATCH_NOT_IN_REFERENCE_SET",

                    (
                        f"Target {index}: "
                        f"used match "
                        f"{match['decision_at']} "
                        "was not found in "
                        "historical reference set"
                    ),
                )

            print(
                f" | "
                f"{result['status']:<9} | "
                f"matches="
                f"{len(matches):>2}"
            )

        print()
        print(
            "=" * 120
        )

        print(
            "AUDIT SUMMARY"
        )

        print(
            "-" * 120
        )

        print(
            "Targets audited:",
            target_count,
        )

        print(
            "Estimated:",
            estimated_count,
        )

        print(
            "Abstained:",
            abstain_count,
        )

        print(
            "Reference groups checked:",
            reference_groups_checked,
        )

        print(
            "Actual evidence matches checked:",
            evidence_matches_checked,
        )

        print(
            "Total assertions:",
            audit.checks,
        )

        print()

        print(
            "Target dose ID leaks:",
            target_id_leaks,
        )

        print(
            "Target future/outcome field leaks:",
            target_outcome_leaks,
        )

        print(
            "linked_bolus leaks:",
            linked_bolus_leaks,
        )

        print(
            "Reference safety-gap violations:",
            reference_safety_violations,
        )

        print(
            "Reference label timing violations:",
            reference_label_timing_violations,
        )

        print(
            "Used evidence safety violations:",
            evidence_safety_violations,
        )

        print(
            "Outcome horizon violations:",
            outcome_horizon_violations,
        )

        print(
            "Past-only glucose mismatches:",
            glucose_asof_violations,
        )

        print()

        print(
            "TOTAL VIOLATIONS:",
            len(
                audit.violations
            ),
        )

        if audit.violations:
            print()
            print(
                "=" * 120
            )

            print(
                "VIOLATION DETAILS"
            )

            print(
                "-" * 120
            )

            for (
                index,
                violation,
            ) in enumerate(
                audit.violations,
                start=1,
            ):
                print(
                    f"{index}. "
                    f"{violation['code']}"
                )

                print(
                    "   ",
                    violation[
                        "details"
                    ],
                )

            audit_result = (
                "FAIL"
            )

        else:
            audit_result = (
                "PASS"
            )

        print()
        print(
            "=" * 120
        )

        print(
            "AUDIT RESULT:",
            audit_result,
        )

        print(
            "DATABASE CHANGED: NO"
        )

        print(
            "=" * 120
        )

    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()