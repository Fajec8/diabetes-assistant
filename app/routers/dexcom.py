import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)
from sqlalchemy import (
    func,
    select,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.dexcom import (
    DexcomConnection,
    DexcomGlucoseReading,
)
from app.models.user import User
from app.services.dexcom_client import (
    DexcomAPIError,
    build_authorization_url,
    dexcom_environment,
    dexcom_is_configured,
    exchange_authorization_code,
    verify_oauth_state,
)
from app.services.dexcom_sync import (
    save_connection_from_oauth,
    sync_connection,
)


router = APIRouter(
    prefix="/dexcom",
    tags=["Dexcom"],
)


@router.get("/status")
def dexcom_configuration_status():
    return {
        "configured":
            dexcom_is_configured(),

        "environment":
            dexcom_environment(),
    }


@router.get(
    "/connect/{user_id}",
    include_in_schema=False,
)
def connect_dexcom(
    user_id: uuid.UUID,
    db: Session = Depends(
        get_db
    ),
):
    if not dexcom_is_configured():
        raise HTTPException(
            status_code=500,
            detail=(
                "Dexcom environment variables "
                "are not configured"
            ),
        )

    user = db.get(
        User,
        user_id,
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    authorization_url = (
        build_authorization_url(
            user_id
        )
    )

    return RedirectResponse(
        url=authorization_url,
        status_code=302,
    )


@router.get(
    "/callback",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def dexcom_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(
        get_db
    ),
):
    if error:
        raise HTTPException(
            status_code=400,
            detail=(
                "Dexcom authorization "
                f"failed: {error}"
            ),
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail=(
                "Dexcom authorization code "
                "is missing"
            ),
        )

    if not state:
        raise HTTPException(
            status_code=400,
            detail=(
                "Dexcom OAuth state "
                "is missing"
            ),
        )

    try:
        user_id = (
            verify_oauth_state(
                state
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    user = db.get(
        User,
        user_id,
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    try:
        token_payload = (
            exchange_authorization_code(
                code
            )
        )

        connection = (
            save_connection_from_oauth(
                db,
                user_id,
                token_payload,
            )
        )

    except (
        DexcomAPIError,
        RuntimeError,
    ) as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Dexcom token exchange "
                f"failed: {exc}"
            ),
        ) from exc

    sync_result = None
    sync_failed = False

    try:
        sync_result = sync_connection(
            db,
            connection,
            initial_lookback_hours=24,
        )

    except Exception:
        sync_failed = True

    if sync_failed:
        sync_html = """
            <p>
                Dexcom účet byl připojen,
                ale první synchronizace dat
                se nepodařila.
            </p>

            <p>
                Připojení zůstalo uložené
                a synchronizaci můžeme
                spustit znovu.
            </p>
        """

    else:
        inserted = (
            sync_result[
                "records_inserted"
            ]
            if sync_result
            else 0
        )

        received = (
            sync_result[
                "records_received"
            ]
            if sync_result
            else 0
        )

        sync_html = f"""
            <p>
                První synchronizace proběhla.
            </p>

            <p>
                Dexcom poslal
                <strong>{received}</strong>
                záznamů a
                <strong>{inserted}</strong>
                nových jsme uložili.
            </p>
        """

    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>

        <html lang="cs">

        <head>
            <meta charset="UTF-8">

            <meta
                name="viewport"
                content="width=device-width,
                initial-scale=1"
            >

            <title>
                Dexcom připojen
            </title>

            <style>
                body {{
                    font-family:
                        -apple-system,
                        BlinkMacSystemFont,
                        "Segoe UI",
                        sans-serif;

                    background: #f4f6f8;
                    margin: 0;
                    padding: 24px;
                    color: #17202a;
                }}

                .card {{
                    max-width: 600px;
                    margin: 40px auto;
                    background: white;
                    border-radius: 16px;
                    padding: 24px;
                    box-shadow:
                        0 2px 12px
                        rgba(
                            0,
                            0,
                            0,
                            0.08
                        );
                }}

                .ok {{
                    font-size: 42px;
                }}

                a {{
                    display: inline-block;
                    margin-top: 16px;
                    padding: 12px 18px;
                    background: #17202a;
                    color: white;
                    text-decoration: none;
                    border-radius: 10px;
                    font-weight: 700;
                }}
            </style>

        </head>

        <body>

            <div class="card">

                <div class="ok">
                    ✓
                </div>

                <h1>
                    Dexcom je připojen
                </h1>

                <p>
                    OAuth autorizace proběhla
                    úspěšně a tokeny jsou
                    uložené na backendu.
                </p>

                {sync_html}

                <a
                    href="/dexcom/status/{user_id}"
                >
                    Zobrazit stav připojení
                </a>

            </div>

        </body>

        </html>
        """,
        status_code=200,
    )


@router.get(
    "/status/{user_id}"
)
def dexcom_user_status(
    user_id: uuid.UUID,
    db: Session = Depends(
        get_db
    ),
):
    connection = db.scalar(
        select(
            DexcomConnection
        )
        .where(
            DexcomConnection.user_id
            == user_id
        )
    )

    if connection is None:
        return {
            "connected":
                False,

            "user_id":
                str(user_id),
        }

    reading_count = db.scalar(
        select(
            func.count(
                DexcomGlucoseReading.id
            )
        )
        .where(
            DexcomGlucoseReading.user_id
            == user_id
        )
    )

    latest = db.scalar(
        select(
            DexcomGlucoseReading
        )
        .where(
            DexcomGlucoseReading.user_id
            == user_id
        )
        .order_by(
            DexcomGlucoseReading
            .system_time
            .desc()
        )
        .limit(1)
    )

    return {
        "connected":
            True,

        "active":
            connection.active,

        "environment":
            connection.environment,

        "connected_at":
            connection.connected_at,

        "last_sync_at":
            connection.last_sync_at,

        "last_successful_sync_at":
            (
                connection
                .last_successful_sync_at
            ),

        "last_sync_error":
            connection.last_sync_error,

        "stored_readings":
            reading_count or 0,

        "latest":
            (
                {
                    "system_time":
                        latest.system_time,

                    "value_mmol_l":
                        latest.value_mmol_l,

                    "trend":
                        latest.trend,

                    "trend_rate_mg_dl_min":
                        (
                            latest
                            .trend_rate_mg_dl_min
                        ),
                }
                if latest
                else None
            ),
    }


@router.post(
    "/sync/{user_id}"
)
def manual_dexcom_sync(
    user_id: uuid.UUID,
    db: Session = Depends(
        get_db
    ),
):
    connection = db.scalar(
        select(
            DexcomConnection
        )
        .where(
            DexcomConnection.user_id
            == user_id
        )
    )

    if connection is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Dexcom is not connected "
                "for this user"
            ),
        )

    try:
        return sync_connection(
            db,
            connection,
        )

    except DexcomAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc


@router.get(
    "/latest/{user_id}"
)
def latest_dexcom_readings(
    user_id: uuid.UUID,
    limit: int = 12,
    db: Session = Depends(
        get_db
    ),
):
    limit = max(
        1,
        min(
            limit,
            100,
        ),
    )

    readings = (
        db.scalars(
            select(
                DexcomGlucoseReading
            )
            .where(
                DexcomGlucoseReading.user_id
                == user_id
            )
            .order_by(
                DexcomGlucoseReading
                .system_time
                .desc()
            )
            .limit(
                limit
            )
        )
        .all()
    )

    return {
        "count":
            len(readings),

        "readings":
            [
                {
                    "system_time":
                        reading.system_time,

                    "display_time":
                        reading.display_time,

                    "value_mg_dl":
                        reading.value_mg_dl,

                    "value_mmol_l":
                        reading.value_mmol_l,

                    "trend":
                        reading.trend,

                    "trend_rate_mg_dl_min":
                        (
                            reading
                            .trend_rate_mg_dl_min
                        ),

                    "status":
                        reading.status,

                    "display_device":
                        reading.display_device,
                }

                for reading
                in readings
            ],
    }