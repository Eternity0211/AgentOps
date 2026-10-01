"""CLI for running one simulator service role."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn

from agentops_incident_commander.simulator.app import ServiceName, create_app


def main(argv: Sequence[str] | None = None) -> int:
    """Run a selected service on the shared container port."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("gateway", "order", "inventory", "payment"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args(argv)
    service: ServiceName = arguments.service
    uvicorn.run(create_app(service), host=arguments.host, port=arguments.port)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the module entry point
    raise SystemExit(main())
