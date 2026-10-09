"""Service factory with startup validation and separate liveness/readiness."""

from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
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
        if config.stripe:
            from .stripe_provider import configure_connections
            try:
                configure_connections(database,config)
            except Exception:
                database.close()
                raise
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
        from .cases import router as cases_router
        app.include_router(cases_router)
        from .repairs import router as repairs_router
        app.include_router(repairs_router)
        frontend=Path(__file__).resolve().parents[2]/'frontend/dist'
        if frontend.exists():
            app.mount('/assets',StaticFiles(directory=frontend/'assets'),name='assets')

            @app.get('/',include_in_schema=False)
            def index():
                return FileResponse(frontend/'index.html',headers={'Cache-Control':'no-store'})

        @app.middleware('http')
        async def private_responses(request,call_next):
            response=await call_next(request)
            if request.url.path.startswith(('/api/','/dev/')):
                response.headers['Cache-Control']='no-store'
            response.headers['X-Content-Type-Options']='nosniff'
            response.headers['Referrer-Policy']='no-referrer'
            response.headers['X-Frame-Options']='DENY'
            if request.url.path == '/' or request.url.path.startswith('/assets/'):
                response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            return response

    @app.exception_handler(RequestValidationError)
    def invalid_input(request, error):
        # Pydantic's default response echoes raw input, including unknown secrets.
        # Keep only error categories. Even field names may be attacker supplied.
        return JSONResponse({'detail': 'Invalid request',
                             'errors': [{'type': item['type']} for item in error.errors()]}, status_code=422)

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
