from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _require_timezone(
    value: datetime,
    field_name: str,
) -> datetime:
    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )

    return value


class DecisionGlucoseInput(BaseModel):
    current: float = Field(
        gt=0,
        le=40,
    )

    delta_15m: float | None = None
    delta_30m: float | None = None
    delta_60m: float | None = None

    trend: str | None = None


class DecisionMealItemInput(BaseModel):
    food_name: str = Field(
        min_length=1,
        max_length=120,
    )

    preparation: str | None = Field(
        default=None,
        max_length=80,
    )

    variant: str | None = Field(
        default=None,
        max_length=120,
    )

    amount_g: float | None = Field(
        default=None,
        gt=0,
    )

    carbohydrates_g: float | None = Field(
        default=None,
        ge=0,
    )

    note: str | None = Field(
        default=None,
        max_length=500,
    )


class DecisionMealInput(BaseModel):
    carbohydrates_g: float = Field(
        ge=0,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    items: list[
        DecisionMealItemInput
    ] = Field(
        default_factory=list,
    )


class RecentNovoRapidDoseInput(BaseModel):
    units: float = Field(
        gt=0,
    )

    administered_at: datetime

    @field_validator(
        "administered_at"
    )
    @classmethod
    def validate_administered_at(
        cls,
        value: datetime,
    ) -> datetime:
        return _require_timezone(
            value,
            "administered_at",
        )


class TresibaInput(BaseModel):
    units: float = Field(
        gt=0,
    )

    administered_at: datetime

    @field_validator(
        "administered_at"
    )
    @classmethod
    def validate_administered_at(
        cls,
        value: datetime,
    ) -> datetime:
        return _require_timezone(
            value,
            "administered_at",
        )


class DecisionActivityInput(BaseModel):
    activity_type: str = Field(
        min_length=1,
        max_length=100,
    )

    intensity: str

    duration_minutes: int = Field(
        gt=0,
    )

    started_at: datetime
    ended_at: datetime

    @field_validator(
        "started_at",
        "ended_at",
    )
    @classmethod
    def validate_activity_datetime(
        cls,
        value: datetime,
    ) -> datetime:
        return _require_timezone(
            value,
            "activity datetime",
        )

    @field_validator(
        "intensity"
    )
    @classmethod
    def validate_intensity(
        cls,
        value: str,
    ) -> str:
        allowed = {
            "LOW",
            "MEDIUM",
            "HIGH",
        }

        value = value.upper()

        if value not in allowed:
            raise ValueError(
                "intensity must be "
                "LOW, MEDIUM or HIGH"
            )

        return value

    @model_validator(
        mode="after"
    )
    def validate_activity(
        self,
    ):
        if (
            self.ended_at
            <= self.started_at
        ):
            raise ValueError(
                "ended_at must be after "
                "started_at"
            )

        return self


class DecisionSessionCreate(BaseModel):
    user_id: uuid.UUID

    decision_at: datetime

    glucose: DecisionGlucoseInput

    planned_meal: (
        DecisionMealInput
        | None
    ) = None

    recent_novorapid: list[
        RecentNovoRapidDoseInput
    ] = Field(
        default_factory=list,
    )

    tresiba: TresibaInput | None = None

    activities: list[
        DecisionActivityInput
    ] = Field(
        default_factory=list,
    )

    note: str | None = Field(
        default=None,
        max_length=1000,
    )

    @field_validator(
        "decision_at"
    )
    @classmethod
    def validate_decision_at(
        cls,
        value: datetime,
    ) -> datetime:
        return _require_timezone(
            value,
            "decision_at",
        )

    @model_validator(
        mode="after"
    )
    def validate_historical_inputs(
        self,
    ):
        for dose in (
            self.recent_novorapid
        ):
            if (
                dose.administered_at
                > self.decision_at
            ):
                raise ValueError(
                    "Previous NovoRapid dose "
                    "cannot be in the future"
                )

        if (
            self.tresiba is not None
            and self.tresiba.administered_at
            > self.decision_at
        ):
            raise ValueError(
                "Tresiba dose cannot be "
                "in the future"
            )

        for activity in self.activities:
            if (
                activity.ended_at
                > self.decision_at
            ):
                raise ValueError(
                    "Activity cannot end "
                    "after decision_at"
                )

        return self


class ActionPlanCreate(BaseModel):
    strategy: str

    total_novorapid_units: float = Field(
        ge=0,
    )

    prebolus_minutes: int | None = Field(
        default=None,
        ge=0,
    )

    first_dose_units: float | None = Field(
        default=None,
        ge=0,
    )

    second_dose_units: float | None = Field(
        default=None,
        ge=0,
    )

    second_dose_delay_minutes: (
        int | None
    ) = Field(
        default=None,
        ge=0,
    )

    @field_validator(
        "strategy"
    )
    @classmethod
    def validate_strategy(
        cls,
        value: str,
    ) -> str:
        value = value.upper()

        allowed = {
            "NONE",
            "SINGLE",
            "SPLIT",
        }

        if value not in allowed:
            raise ValueError(
                "strategy must be "
                "NONE, SINGLE or SPLIT"
            )

        return value

    @model_validator(
        mode="after"
    )
    def validate_plan(
        self,
    ):
        tolerance = 0.05

        if self.strategy == "NONE":
            if (
                abs(
                    self.total_novorapid_units
                )
                > tolerance
            ):
                raise ValueError(
                    "NONE strategy requires "
                    "total_novorapid_units = 0"
                )

            if (
                self.first_dose_units
                is not None
                or self.second_dose_units
                is not None
                or self.second_dose_delay_minutes
                is not None
            ):
                raise ValueError(
                    "NONE strategy cannot "
                    "contain dose parts"
                )

        elif self.strategy == "SINGLE":
            if (
                self.total_novorapid_units
                <= 0
            ):
                raise ValueError(
                    "SINGLE strategy requires "
                    "a positive total dose"
                )

            if (
                self.first_dose_units
                is None
            ):
                raise ValueError(
                    "SINGLE strategy requires "
                    "first_dose_units"
                )

            if (
                abs(
                    self.first_dose_units
                    - self.total_novorapid_units
                )
                > tolerance
            ):
                raise ValueError(
                    "For SINGLE strategy "
                    "first_dose_units must equal "
                    "total_novorapid_units"
                )

            if (
                self.second_dose_units
                is not None
                or self.second_dose_delay_minutes
                is not None
            ):
                raise ValueError(
                    "SINGLE strategy cannot "
                    "contain a second dose"
                )

        elif self.strategy == "SPLIT":
            if (
                self.total_novorapid_units
                <= 0
            ):
                raise ValueError(
                    "SPLIT strategy requires "
                    "a positive total dose"
                )

            if (
                self.first_dose_units
                is None
                or self.first_dose_units
                <= 0
            ):
                raise ValueError(
                    "SPLIT strategy requires "
                    "positive first_dose_units"
                )

            if (
                self.second_dose_units
                is None
                or self.second_dose_units
                <= 0
            ):
                raise ValueError(
                    "SPLIT strategy requires "
                    "positive second_dose_units"
                )

            if (
                self.second_dose_delay_minutes
                is None
                or self.second_dose_delay_minutes
                <= 0
            ):
                raise ValueError(
                    "SPLIT strategy requires "
                    "positive "
                    "second_dose_delay_minutes"
                )

            total_parts = (
                self.first_dose_units
                + self.second_dose_units
            )

            if (
                abs(
                    total_parts
                    - self.total_novorapid_units
                )
                > tolerance
            ):
                raise ValueError(
                    "SPLIT dose parts must sum "
                    "to total_novorapid_units"
                )

        return self


class DecisionOutcomeCreate(BaseModel):
    baseline_glucose: float = Field(
        gt=0,
        le=40,
    )

    glucose_30m: float | None = Field(
        default=None,
        gt=0,
        le=40,
    )

    glucose_60m: float | None = Field(
        default=None,
        gt=0,
        le=40,
    )

    glucose_90m: float | None = Field(
        default=None,
        gt=0,
        le=40,
    )

    glucose_120m: float | None = Field(
        default=None,
        gt=0,
        le=40,
    )

    glucose_180m: float | None = Field(
        default=None,
        gt=0,
        le=40,
    )

    evaluated_at: datetime | None = None

    note: str | None = Field(
        default=None,
        max_length=1000,
    )

    @field_validator(
        "evaluated_at"
    )
    @classmethod
    def validate_evaluated_at(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None

        return _require_timezone(
            value,
            "evaluated_at",
        )

    @model_validator(
        mode="after"
    )
    def validate_outcome(
        self,
    ):
        future_values = [
            self.glucose_30m,
            self.glucose_60m,
            self.glucose_90m,
            self.glucose_120m,
            self.glucose_180m,
        ]

        if not any(
            value is not None
            for value in future_values
        ):
            raise ValueError(
                "At least one future glucose "
                "value is required"
            )

        return self


class ActionPlanResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: uuid.UUID

    source: str
    status: str

    strategy: str | None = None

    total_novorapid_units: (
        float | None
    ) = None

    prebolus_minutes: (
        int | None
    ) = None

    first_dose_units: (
        float | None
    ) = None

    second_dose_units: (
        float | None
    ) = None

    second_dose_delay_minutes: (
        int | None
    ) = None

    model_version: str | None = None

    confidence_score: (
        float | None
    ) = None

    confidence_level: (
        str | None
    ) = None

    support_count: int | None = None

    strongest_evidence: (
        float | None
    ) = None

    average_evidence: (
        float | None
    ) = None

    abstain_reason: str | None = None

    revealed_at: datetime | None = None

    created_at: datetime | None = None


class DecisionOutcomeResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: uuid.UUID

    baseline_glucose: float | None

    glucose_30m: float | None
    glucose_60m: float | None
    glucose_90m: float | None
    glucose_120m: float | None
    glucose_180m: float | None

    quality_score: float | None
    quality_status: str | None

    confidence: float | None
    confidence_level: str | None

    low_detected: bool
    high_detected: bool

    evaluated_at: datetime | None
    created_at: datetime | None


class DecisionSessionResponse(BaseModel):
    id: uuid.UUID

    user_id: uuid.UUID

    decision_at: datetime
    status: str

    input_snapshot: dict

    user_plan: (
        ActionPlanResponse
        | None
    )

    system_shadow_available: bool

    system_shadow: (
        ActionPlanResponse
        | None
    )

    outcome: (
        DecisionOutcomeResponse
        | None
    )

    comparison: dict | None

    created_at: datetime