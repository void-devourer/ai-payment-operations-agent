"""Service factory with startup validation and separate liveness/readiness."""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import httpx
import psycopg2

from .config import Settings
from .database import Database


def create_app(service: str | None = None, settings: Settings | None = None):
    service = service or os.environ.get("SERVICE", "console")

    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings.from_env(service)
        database = Database(config.database_url)
        app.state.settings = config
        app.state.database = database
        with httpx.Client(timeout=5, trust_env=False) as client:
            app.state.http = client
            try:
                yield
            finally:
                database.close()

    app = FastAPI(title=f"Payment operations: {service}", lifespan=lifespan)
    if service == "console":
        from .console import router
    elif service == "reference":
        from .reference import router
    elif service == "simulator":
        from .simulator import router
    else:
        raise ValueError("Unknown service")
    app.include_router(router)
    if service == "console":
        from .ingestion import router as ingestion_router
        app.include_router(ingestion_router)

    @app.get("/health/live")
    def live():
        return {"status": "alive", "service": service}

    @app.get("/health/ready")
    def ready():
        try:
            with app.state.database.transaction() as cursor:
                cursor.execute("SELECT 1")
            return {"status": "ready", "service": service}
        except psycopg2.Error:
            return JSONResponse({"status": "database_unavailable"}, status_code=503)

    @app.exception_handler(psycopg2.IntegrityError)
    def conflict(request, error):
        return JSONResponse({"detail": "Database constraint conflict"}, status_code=409)

    @app.exception_handler(psycopg2.Error)
    def database_unavailable(request, error):
        return JSONResponse({"detail": "Database unavailable; delivery remains retryable"}, status_code=503)

    @app.exception_handler(httpx.HTTPStatusError)
    @app.exception_handler(httpx.RequestError)
    def upstream(request, error):
        return JSONResponse({"detail": "Upstream unavailable; verify outcome before retry"}, status_code=503)

    return app
