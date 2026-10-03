"""FastAPI-only control-plane process composition."""

from __future__ import annotations

import os
from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import RequestResponseEndpoint

from agentops_incident_commander.domain import OpaqueIdentifier, utc_now

from .api_contracts import install_openapi_contract
from .api_errors import REQUEST_ID_HEADER, install_error_handlers
from .api_v1 import (
    Clock,
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
    request_id_factory: IdFactory | None = None,
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
    request_ids = request_id_factory or new_identifier

    @app.middleware("http")
    async def correlate_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = OpaqueIdentifier(request_ids()).value
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        return response

    install_error_handlers(app)

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
    install_openapi_contract(app)

    return app


def main(argv: Sequence[str] | None = None) -> int:
    """Load API-only settings and run the HTTP server."""
    if argv:
        raise SystemExit("agentops-api accepts no arguments")
    settings = ApiSettings.load(os.environ)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0
