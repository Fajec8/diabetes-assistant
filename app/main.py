from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine

from app.routers.users import (
    router as users_router,
)
from app.routers.glucose import (
    router as glucose_router,
)
from app.routers.insulin import (
    router as insulin_router,
)
from app.routers.meals import (
    router as meals_router,
)
from app.routers.activities import (
    router as activities_router,
)
from app.routers.situations import (
    router as situations_router,
)
from app.routers.decision_sessions import (
    router as decision_sessions_router,
)
from app.routers.dexcom import (
    router as dexcom_router,
)


app = FastAPI(
    title="Diabetes Assistant API",
    version="0.1.0",
)


app.include_router(
    users_router
)

app.include_router(
    glucose_router
)

app.include_router(
    insulin_router
)

app.include_router(
    meals_router
)

app.include_router(
    activities_router
)

app.include_router(
    situations_router
)

app.include_router(
    decision_sessions_router
)

app.include_router(
    dexcom_router
)


@app.get("/")
def root():
    return {
        "message":
            (
                "Diabetes Assistant "
                "API is running"
            )
    }


@app.get("/health/db")
def database_health():
    with engine.connect() as connection:
        result = connection.execute(
            text(
                "SELECT 1"
            )
        )

    return {
        "database":
            "connected",

        "result":
            result.scalar(),
    }