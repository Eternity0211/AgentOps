"""FastAPI-only control-plane process composition."""

from __future__ import annotations

import os
from collections.abc import Sequence

import uvicorn
from fastapi import FastAPI

from .config import ApiSettings


def create_app(settings: ApiSettings) -> FastAPI:
    """Create the HTTP process without starting worker tasks in its lifespan."""
    app = FastAPI(title="AgentOps Incident Commander API", version="1.0.0")
    app.state.process_role = "api"
    app.state.settings = settings

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "healthy", "role": "api"}

    return app


def main(argv: Sequence[str] | None = None) -> int:
    """Load API-only settings and run the HTTP server."""
    if argv:
        raise SystemExit("agentops-api accepts no arguments")
    settings = ApiSettings.load(os.environ)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0
