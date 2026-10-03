"""FastAPI-only control-plane process composition."""

from __future__ import annotations

import os
from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agentops_incident_commander.domain import (
    AuthorizationError,
    DomainError,
    InvalidIncidentTransitionError,
    OptimisticVersionError,
    utc_now,
)

from .api_v1 import (
    Clock,
    IdempotencyConflictError,
    IdFactory,
    PrincipalResolver,
    SessionFactory,
    build_api_v1_router,
    deny_unconfigured_authentication,
    new_identifier,
)
from .config import ApiSettings


def create_app(
    settings: ApiSettings,
    *,
    session_factory: SessionFactory | None = None,
    principal_resolver: PrincipalResolver | None = None,
    clock: Clock | None = None,
    id_factory: IdFactory | None = None,
) -> FastAPI:
    """Create the HTTP process without starting worker tasks in its lifespan."""
    engine = None
    if session_factory is None:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title="AgentOps Incident Commander API", version="1.0.0", lifespan=lifespan)
    app.state.process_role = "api"
    app.state.settings = settings
    app.state.session_factory = session_factory

    @app.exception_handler(AuthorizationError)
    async def authorization_error(_: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(_: Request, exc: IdempotencyConflictError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})

    @app.exception_handler(InvalidIncidentTransitionError)
    @app.exception_handler(OptimisticVersionError)
    async def state_conflict(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})

    @app.exception_handler(DomainError)
    async def invalid_domain_value(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(exc)}
        )

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "healthy", "role": "api"}

    app.include_router(
        build_api_v1_router(
            session_factory,
            principal_resolver=principal_resolver or deny_unconfigured_authentication,
            clock=clock or utc_now,
            id_factory=id_factory or new_identifier,
        )
    )

    return app


def main(argv: Sequence[str] | None = None) -> int:
    """Load API-only settings and run the HTTP server."""
    if argv:
        raise SystemExit("agentops-api accepts no arguments")
    settings = ApiSettings.load(os.environ)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0
