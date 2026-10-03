"""Stable versioned API problem details and request correlation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from agentops_incident_commander.domain import (
    AuthorizationError,
    DomainError,
    InvalidIncidentTransitionError,
    OptimisticVersionError,
)

PROBLEM_MEDIA_TYPE = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-ID"


class InvalidParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str
    code: str
    reason: str


class ProblemDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    code: str
    detail: str
    instance: str
    request_id: str
    errors: list[InvalidParameter] | None = None


class ApiProblem(Exception):
    def __init__(self, status_code: int, code: str, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail


def problem(status_code: int, code: str, title: str, detail: str) -> ApiProblem:
    return ApiProblem(status_code, code, title, detail)


def _request_id(request: Request) -> str:
    return str(request.state.request_id)


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    title: str,
    detail: str,
    errors: list[InvalidParameter] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ProblemDetail(
        type=f"urn:agentops:problem:{code.lower().replace('_', '-')}",
        title=title,
        status=status_code,
        code=code,
        detail=detail,
        instance=request.url.path,
        request_id=_request_id(request),
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        media_type=PROBLEM_MEDIA_TYPE,
        headers={**(headers or {}), REQUEST_ID_HEADER: body.request_id},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def api_problem(request: Request, exc: ApiProblem) -> JSONResponse:
        return _response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_error(request: Request, exc: AuthorizationError) -> JSONResponse:
        return _response(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            code="PERMISSION_DENIED",
            title="Permission denied",
            detail=str(exc),
        )

    @app.exception_handler(InvalidIncidentTransitionError)
    @app.exception_handler(OptimisticVersionError)
    async def state_conflict(request: Request, exc: DomainError) -> JSONResponse:
        return _response(
            request,
            status_code=status.HTTP_409_CONFLICT,
            code="INCIDENT_STATE_CONFLICT",
            title="Incident state conflict",
            detail=str(exc),
        )

    @app.exception_handler(DomainError)
    async def invalid_domain_value(request: Request, exc: DomainError) -> JSONResponse:
        return _response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="DOMAIN_VALIDATION_FAILED",
            title="Domain validation failed",
            detail=str(exc),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            InvalidParameter(
                location=".".join(str(part) for part in item["loc"]),
                code=str(item["type"]),
                reason=str(item["msg"]),
            )
            for item in exc.errors()
        ]
        return _response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="REQUEST_VALIDATION_FAILED",
            title="Request validation failed",
            detail="one or more request fields are invalid",
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_problem(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        mapping: dict[int, tuple[str, str]] = {
            status.HTTP_400_BAD_REQUEST: ("BAD_REQUEST", "Bad request"),
            status.HTTP_401_UNAUTHORIZED: (
                "AUTHENTICATION_REQUIRED",
                "Authentication required",
            ),
            status.HTTP_403_FORBIDDEN: ("PERMISSION_DENIED", "Permission denied"),
            status.HTTP_404_NOT_FOUND: ("RESOURCE_NOT_FOUND", "Resource not found"),
            status.HTTP_405_METHOD_NOT_ALLOWED: ("METHOD_NOT_ALLOWED", "Method not allowed"),
            status.HTTP_409_CONFLICT: ("CONFLICT", "Conflict"),
        }
        code, title = mapping.get(exc.status_code, ("HTTP_ERROR", "HTTP request failed"))
        detail = exc.detail if isinstance(exc.detail, str) else title
        return _response(
            request,
            status_code=exc.status_code,
            code=code,
            title=title,
            detail=detail,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, _: Exception) -> JSONResponse:
        return _response(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            title="Internal server error",
            detail="the server could not complete the request",
        )


def common_error_responses() -> dict[int | str, dict[str, Any]]:
    return {
        code: {"model": ProblemDetail, "description": description}
        for code, description in {
            400: "Malformed request or pagination cursor",
            401: "Authentication is required",
            403: "The principal lacks permission",
            404: "The tenant-scoped resource was not found",
            409: "State, version, or idempotency conflict",
            422: "Request or domain validation failed",
            500: "An unexpected internal error occurred",
        }.items()
    }
