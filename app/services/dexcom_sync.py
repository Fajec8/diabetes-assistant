import uuid
from datetime import (
    datetime,
    timedelta,
    timezone,
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dexcom import (
    DexcomConnection,
    DexcomGlucoseReading,
)
from app.services.dexcom_client import (
    DexcomAPIError,
    dexcom_environment,
    get_egvs,
    refresh_access_token,
)


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _parse_datetime(
    value: str,
) -> datetime:
    normalized = (
        value
        .strip()
        .replace(
            "Z",
            "+00:00",
        )
    )

    parsed = datetime.fromisoformat(
        normalized
    )

    if (
        parsed.tzinfo
        is None
    ):
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def _apply_token_response(
    connection: DexcomConnection,
    payload: dict,
) -> None:
    access_token = payload.get(
        "access_token"
    )

    refresh_token = payload.get(
        "refresh_token"
    )

    if (
        not access_token
        or not refresh_token
    ):
        raise DexcomAPIError(
            "Dexcom token response "
            "is missing required tokens"
        )

    now = _utc_now()

    expires_in = int(
        payload.get(
            "expires_in",
            7200,
        )
    )

    refresh_expires_in = int(
        payload.get(
            "refresh_expires_in",
            0,
        )
        or 0
    )

    connection.access_token = (
        str(access_token)
    )

    connection.refresh_token = (
        str(refresh_token)
    )

    connection.token_type = str(
        payload.get(
            "token_type",
            "Bearer",
        )
    )

    connection.access_expires_at = (
        now
        + timedelta(
            seconds=expires_in
        )
    )

    if (
        refresh_expires_in > 0
    ):
        connection.refresh_expires_at = (
            now
            + timedelta(
                seconds=(
                    refresh_expires_in
                )
            )
        )

    else:
        connection.refresh_expires_at = (
            None
        )

    connection.active = True


def save_connection_from_oauth(
    db: Session,
    user_id: uuid.UUID,
    token_payload: dict,
) -> DexcomConnection:
    connection = db.scalar(
        select(
            DexcomConnection
        )
        .where(
            DexcomConnection.user_id
            == user_id
        )
    )

    if (
        connection
        is None
    ):
        connection = DexcomConnection(
            user_id=user_id,
            environment=(
                dexcom_environment()
            ),
            access_token="",
            refresh_token="",
            access_expires_at=(
                _utc_now()
            ),
        )

        db.add(
            connection
        )

    connection.environment = (
        dexcom_environment()
    )

    connection.last_sync_error = (
        None
    )

    _apply_token_response(
        connection,
        token_payload,
    )

    db.commit()
    db.refresh(
        connection
    )

    return connection


def _refresh_connection(
    db: Session,
    connection: DexcomConnection,
) -> None:
    payload = refresh_access_token(
        connection.refresh_token
    )

    _apply_token_response(
        connection,
        payload,
    )

    connection.last_sync_error = (
        None
    )

    db.commit()
    db.refresh(
        connection
    )


def _ensure_access_token(
    db: Session,
    connection: DexcomConnection,
) -> None:
    refresh_before = (
        _utc_now()
        + timedelta(
            minutes=5
        )
    )

    if (
        connection.access_expires_at
        <= refresh_before
    ):
        _refresh_connection(
            db,
            connection,
        )


def _existing_record_ids(
    db: Session,
    connection_id: uuid.UUID,
    record_ids: list[str],
) -> set[str]:
    if not record_ids:
        return set()

    result = db.scalars(
        select(
            DexcomGlucoseReading.record_id
        )
        .where(
            DexcomGlucoseReading
            .connection_id
            == connection_id
        )
        .where(
            DexcomGlucoseReading
            .record_id
            .in_(
                record_ids
            )
        )
    )

    return set(
        result.all()
    )


def _request_egvs_with_refresh_retry(
    db: Session,
    connection: DexcomConnection,
    start_at: datetime,
    end_at: datetime,
) -> dict:
    _ensure_access_token(
        db,
        connection,
    )

    try:
        return get_egvs(
            connection.access_token,
            start_at,
            end_at,
        )

    except DexcomAPIError as exc:
        if (
            exc.status_code
            != 401
        ):
            raise

        _refresh_connection(
            db,
            connection,
        )

        return get_egvs(
            connection.access_token,
            start_at,
            end_at,
        )


def sync_connection(
    db: Session,
    connection: DexcomConnection,
    initial_lookback_hours: int = 24,
) -> dict:
    now = _utc_now()

    connection.last_sync_at = (
        now
    )

    connection.last_sync_error = (
        None
    )

    db.commit()

    if (
        connection.last_successful_sync_at
        is None
    ):
        start_at = (
            now
            - timedelta(
                hours=(
                    initial_lookback_hours
                )
            )
        )

    else:
        start_at = (
            connection
            .last_successful_sync_at
            - timedelta(
                minutes=15
            )
        )

    maximum_start = (
        now
        - timedelta(
            days=30
        )
    )

    if (
        start_at
        < maximum_start
    ):
        start_at = (
            maximum_start
        )

    try:
        payload = (
            _request_egvs_with_refresh_retry(
                db,
                connection,
                start_at,
                now,
            )
        )

        records = payload.get(
            "records",
            [],
        )

        dexcom_user_id = (
            payload.get(
                "userId"
            )
        )

        if dexcom_user_id:
            connection.dexcom_user_id = (
                str(
                    dexcom_user_id
                )
            )

        record_ids = [
            str(
                record.get(
                    "recordId"
                )
            )
            for record in records
            if record.get(
                "recordId"
            )
        ]

        existing_ids = (
            _existing_record_ids(
                db,
                connection.id,
                record_ids,
            )
        )

        inserted = 0

        latest_system_time = None
        latest_value_mmol_l = None
        latest_trend = None

        for record in records:
            record_id = record.get(
                "recordId"
            )

            system_time_raw = record.get(
                "systemTime"
            )

            if (
                not record_id
                or not system_time_raw
            ):
                continue

            if (
                str(record_id)
                in existing_ids
            ):
                continue

            system_time = (
                _parse_datetime(
                    str(
                        system_time_raw
                    )
                )
            )

            value = record.get(
                "value"
            )

            if (
                value is not None
            ):
                value_mg_dl = int(
                    value
                )

                value_mmol_l = round(
                    value_mg_dl
                    / 18.0,
                    2,
                )

            else:
                value_mg_dl = (
                    None
                )

                value_mmol_l = (
                    None
                )

            trend_rate = (
                record.get(
                    "trendRate"
                )
            )

            if (
                trend_rate
                is not None
            ):
                trend_rate = float(
                    trend_rate
                )

            reading = (
                DexcomGlucoseReading(
                    connection_id=(
                        connection.id
                    ),
                    user_id=(
                        connection.user_id
                    ),
                    record_id=(
                        str(record_id)
                    ),
                    system_time=(
                        system_time
                    ),
                    display_time=(
                        record.get(
                            "displayTime"
                        )
                    ),
                    value_mg_dl=(
                        value_mg_dl
                    ),
                    value_mmol_l=(
                        value_mmol_l
                    ),
                    status=(
                        record.get(
                            "status"
                        )
                    ),
                    trend=(
                        record.get(
                            "trend"
                        )
                    ),
                    trend_rate_mg_dl_min=(
                        trend_rate
                    ),
                    display_device=(
                        record.get(
                            "displayDevice"
                        )
                    ),
                    transmitter_generation=(
                        record.get(
                            (
                                "transmitter"
                                "Generation"
                            )
                        )
                    ),
                    display_app=(
                        record.get(
                            "displayApp"
                        )
                    ),
                )
            )

            db.add(
                reading
            )

            inserted += 1

            if (
                latest_system_time
                is None
                or system_time
                > latest_system_time
            ):
                latest_system_time = (
                    system_time
                )

                latest_value_mmol_l = (
                    value_mmol_l
                )

                latest_trend = (
                    record.get(
                        "trend"
                    )
                )

        connection.last_successful_sync_at = (
            now
        )

        connection.last_sync_error = (
            None
        )

        db.commit()

        return {
            "environment":
                connection.environment,

            "requested_from":
                start_at.isoformat(),

            "requested_to":
                now.isoformat(),

            "records_received":
                len(records),

            "records_inserted":
                inserted,

            "latest_system_time":
                (
                    latest_system_time
                    .isoformat()
                    if latest_system_time
                    else None
                ),

            "latest_value_mmol_l":
                latest_value_mmol_l,

            "latest_trend":
                latest_trend,
        }

    except Exception as exc:
        connection.last_sync_error = (
            str(exc)[:1000]
        )

        db.commit()

        raise