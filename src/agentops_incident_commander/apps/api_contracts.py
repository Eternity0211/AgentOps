"""Deterministic OpenAPI conventions shared by every versioned endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from .api_errors import PROBLEM_MEDIA_TYPE, REQUEST_ID_HEADER


def apply_openapi_conventions(schema: dict[str, Any]) -> dict[str, Any]:
    paths = schema.get("paths", {})
    for path, path_item in paths.items():
        if not path.startswith("/api/v1/") or not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            if not isinstance(responses, dict):
                continue
            for response_code, response in responses.items():
                if not isinstance(response, dict):
                    continue
                headers = response.setdefault("headers", {})
                headers[REQUEST_ID_HEADER] = {
                    "description": "Server-generated request correlation identifier",
                    "schema": {"type": "string"},
                }
                if str(response_code).startswith(("4", "5")):
                    response["content"] = {
                        PROBLEM_MEDIA_TYPE: {
                            "schema": {"$ref": "#/components/schemas/ProblemDetail"}
                        }
                    }
            if path.endswith("/controls/start-investigation") or path.endswith("/controls/cancel"):
                success = responses.get("200")
                if isinstance(success, dict):
                    success.setdefault("headers", {})["Idempotency-Replayed"] = {
                        "description": "true when a stored successful response was replayed",
                        "schema": {"type": "string", "enum": ["true", "false"]},
                    }
    return schema


def install_openapi_contract(app: FastAPI) -> None:
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        app.openapi_schema = apply_openapi_conventions(schema)
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
