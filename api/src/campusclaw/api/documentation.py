"""Public same-origin Swagger assets and generated, non-runtime OpenAPI metadata."""

from importlib.resources import files
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from campusclaw.api.schemas import DomainErrorResponse, QuestionRequest, SafeValidationErrorResponse
from campusclaw.api.sse import EVENT_MODELS

_SWAGGER_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>CampusClaw API</title><link rel="stylesheet" href="/api/docs/assets/swagger-ui.css">
<link rel="stylesheet" href="/api/docs/assets/local.css">
</head><body><div id="swagger-ui"></div>
<script src="/api/docs/assets/swagger-ui-bundle.js"></script>
<script src="/api/docs/init.js"></script></body></html>"""
_SWAGGER_INIT = """window.ui = SwaggerUIBundle({
url: '/api/openapi.json', dom_id: '#swagger-ui', deepLinking: true,
persistAuthorization: false, validatorUrl: null, presets: [SwaggerUIBundle.presets.apis],
});"""
_SSE_DESCRIPTION = """Bearer-authenticated POST using fetch(), not EventSource.
Pre-stream authorization, validation, readiness and concurrency failures are ordinary JSON errors.
After acceptance: exactly one message.started, zero or more answer.delta, zero or more citation,
then exactly one message.completed or message.error. Every semantic event has monotonically
increasing sequence (starting at 1) and shared conversation/user/assistant IDs. Heartbeat comments
are not semantic events. Deltas are Unicode-safe slices of a fully buffered, validated, persisted
answer, never raw provider tokens. Prior citations are not evidence for this turn.
message.completed includes answer length/SHA-256, mode, configuration revision and completion time.
message.error is a safe post-start terminal failure; the HTTP status remains 200. Disconnect does
not cancel bounded server work: refresh the conversation for its authoritative terminal state.
No automatic replay/resume or automatic request retry is supported."""


def install_documentation(app: FastAPI) -> None:
    # Package-pinned assets, served through the same gateway and existing strict CSP.
    vendor = files("campusclaw.swagger_assets")
    app.mount("/api/docs/assets", StaticFiles(directory=str(vendor)), name="swagger-assets")

    @app.get(
        "/api/docs",
        response_class=HTMLResponse,
        tags=["documentation"],
        summary="Open public Swagger UI",
        operation_id="get_api_docs",
    )
    def swagger_ui() -> HTMLResponse:
        return HTMLResponse(_SWAGGER_HTML)

    @app.get("/api/docs/init.js", include_in_schema=False)
    def swagger_init() -> Response:
        return Response(_SWAGGER_INIT, media_type="application/javascript")

    for route in app.routes:
        if isinstance(route, APIRoute) and route.include_in_schema:
            method = sorted(route.methods)[0].lower()
            route.operation_id = (
                method
                + "_"
                + route.path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
            )
            route.summary = route.summary or route.name.replace("_", " ").capitalize()

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        document = get_openapi(title=app.title, version=app.version, routes=app.routes)
        models: list[type[BaseModel]] = [
            DomainErrorResponse,
            QuestionRequest,
            SafeValidationErrorResponse,
            *EVENT_MODELS.values(),
        ]
        _, definitions = models_json_schema(
            [(model, "validation") for model in models],
            ref_template="#/components/schemas/{model}",
        )
        schemas = document.setdefault("components", {}).setdefault("schemas", {})
        schemas.update(definitions.get("$defs", {}))
        for path, methods in document["paths"].items():
            for method, operation in methods.items():
                if method not in {"get", "post", "patch", "delete"}:
                    continue
                public = path in {"/health", "/api/auth/login", "/api/auth/logout", "/api/docs"}
                operation["security"] = [] if public else [{"BearerJWT": []}]
                statuses = _error_statuses(path, method)
                for code in statuses:
                    operation["responses"][str(code)] = {
                        "description": {
                            400: "Invalid request",
                            401: "Authentication required",
                            403: "Forbidden role",
                            404: "Resource not found",
                            409: "Resource not ready or turn already processing",
                            413: "Request too large",
                            429: "Message rate limit exceeded",
                            500: "Material unavailable",
                            503: "Dependency unavailable",
                        }[code],
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/DomainErrorResponse",
                                }
                            }
                        },
                    }
                if path.startswith(("/api/agents", "/api/skills", "/api/conversations")):
                    operation["responses"].pop("422", None)
                elif "422" in operation["responses"]:
                    operation["responses"]["422"] = {
                        "description": "Invalid request; rejected inputs are never echoed",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/SafeValidationErrorResponse",
                                }
                            }
                        },
                    }
        schemas.pop("HTTPValidationError", None)
        schemas.pop("ValidationError", None)
        # These legacy handlers parse manually; describe their actual inputs without
        # changing runtime parsing, bounds or error behavior.
        document["paths"]["/api/knowledge/query"]["post"]["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/QuestionRequest",
                    }
                }
            },
        }
        document["paths"]["/api/materials"]["post"]["requestBody"] = {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["title", "file"],
                        "properties": {
                            "title": {"type": "string", "minLength": 1, "maxLength": 300},
                            "file": {"type": "string", "format": "binary"},
                        },
                    }
                }
            },
        }
        document["paths"]["/api/materials/{material_id}/download"]["get"]["responses"]["200"] = {
            "description": "Authorized file attachment with its stored content type",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
                "*/*": {"schema": {"type": "string", "format": "binary"}},
            },
        }
        stream = document["paths"]["/api/conversations/{conversation_id}/messages"]["post"]
        stream["description"] = _SSE_DESCRIPTION
        stream["responses"]["200"] = {
            "description": "Ordered SSE frames: event name plus a JSON data object",
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "x-event-schemas": {
                        name: {"$ref": f"#/components/schemas/{model.__name__}"}
                        for name, model in EVENT_MODELS.items()
                    },
                }
            },
        }
        health = document["paths"]["/health"]["get"]
        health["responses"]["200"]["content"] = {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"type": "string", "enum": ["ok"]}},
                    "additionalProperties": {"type": "string"},
                }
            }
        }
        health["responses"]["503"]["content"] = {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["detail"],
                    "properties": {
                        "detail": {
                            "type": "object",
                            "required": ["status", "code"],
                            "properties": {
                                "status": {"const": "unavailable"},
                                "code": {"const": "not_ready"},
                            },
                        }
                    },
                }
            }
        }
        document["paths"]["/api/openapi.json"] = {
            "get": {
                "operationId": "get_api_openapi_json",
                "summary": "Read public OpenAPI document",
                "tags": ["documentation"],
                "security": [],
                "responses": {
                    "200": {
                        "description": "OpenAPI 3.1 document",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"},
                            }
                        },
                    }
                },
            }
        }
        app.openapi_schema = document
        return document

    app.openapi_schema = openapi()


def _error_statuses(path: str, method: str) -> set[int]:
    if path == "/health":
        return {503}
    if path == "/api/docs" or path == "/api/auth/logout":
        return set()
    if path == "/api/auth/login":
        return {401}
    statuses = {401}
    if path.startswith(("/api/agents", "/api/skills", "/api/conversations")):
        statuses |= {400, 403, 404, 409}
    if path.endswith("/messages"):
        statuses |= {413, 429, 503}
    if path == "/api/knowledge/query":
        statuses |= {400, 403, 503}
    if path.startswith("/api/materials"):
        statuses |= {403}
        if "{material_id}" in path:
            statuses |= {404}
        if method == "post":
            statuses |= {400, 413}
        if path.endswith("/download"):
            statuses |= {500}
    return statuses
