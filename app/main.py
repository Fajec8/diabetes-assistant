from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.database import engine

from app.routers.activities import (
    router as activities_router,
)
from app.routers.auth import (
    router as auth_router,
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
from app.routers.situations import (
    router as situations_router,
)


APP_DIRECTORY = (
    Path(
        __file__
    )
    .resolve()
    .parent
)

STATIC_DIRECTORY = (
    APP_DIRECTORY
    / "static"
)


app = FastAPI(
    title="Diabetes Assistant API",
    version="0.5.0"
)


app.mount(
    "/static",
    StaticFiles(
        directory=
            STATIC_DIRECTORY
    ),
    name="static"
)


app.include_router(
    auth_router
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


@app.get(
    "/app",
    include_in_schema=False
)
def mobile_app():
    return FileResponse(
        STATIC_DIRECTORY
        / "index.html",
        headers={
            "Cache-Control":
                "no-cache"
        }
    )


@app.get(
    "/manifest.webmanifest",
    include_in_schema=False
)
def web_manifest():
    return FileResponse(
        STATIC_DIRECTORY
        / "manifest.webmanifest",
        media_type=
            "application/manifest+json",
        headers={
            "Cache-Control":
                "no-cache"
        }
    )


@app.get(
    "/service-worker.js",
    include_in_schema=False
)
def service_worker():
    return FileResponse(
        STATIC_DIRECTORY
        / "service-worker.js",
        media_type=
            "application/javascript",
        headers={
            "Cache-Control":
                "no-cache",

            "Service-Worker-Allowed":
                "/"
        }
    )


@app.get("/")
def root():
    return {
        "message":
            "Diabetes Assistant API is running"
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
            result.scalar()
    }