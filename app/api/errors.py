import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.database import (
    DatabaseIntegrityError,
    DatabaseUnavailableError,
)
from app.location.errors import LocationError

logger = logging.getLogger("app.errors")


def register_exception_handlers(app: FastAPI) -> None:
    """Register consistent JSON error responses for the whole application."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Keep the response JSON-safe and free of internal exception objects:
        # pydantic's errors may carry non-serializable ctx (e.g. the exception
        # instance from a model_validator), so we project only the safe fields.
        detail = [
            {
                "loc": error.get("loc"),
                "msg": error.get("msg"),
                "type": error.get("type"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": detail},
        )

    @app.exception_handler(DatabaseUnavailableError)
    async def database_unavailable_handler(
        request: Request, exc: DatabaseUnavailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable"},
        )

    @app.exception_handler(DatabaseIntegrityError)
    async def database_integrity_handler(
        request: Request, exc: DatabaseIntegrityError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "The record conflicts with existing data"},
        )

    @app.exception_handler(LocationError)
    async def location_error_handler(
        request: Request, exc: LocationError
    ) -> JSONResponse:
        # One consistent, generic message for every geocoding failure (missing
        # provider, upstream outage, timeout, malformed provider data). Never
        # leaks provider-internal details.
        return JSONResponse(
            status_code=503,
            content={"detail": "Geocoder temporarily unavailable"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )