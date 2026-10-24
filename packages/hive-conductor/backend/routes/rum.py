"""Production perceived-load (RUM) collector routes (#1420).

Three surfaces, all under `/v1/rum`:

    POST /v1/rum/events          — the SPA reporter's batch ingest
    GET  /v1/rum/events          — operator read-back of the retained ring
    GET  /v1/rum/events/summary  — grouped aggregation (route/outcome/percentiles)

The decisions the endpoints encode (who operates the collector, when it is
on, how much is kept) live on `services/rum_store.py` and `docs/RUM.md`;
this module is their HTTP face:

- Ingest is fail-closed: with `RUM_INGEST_ENABLED` unset (the default) the
  POST answers 202 and discards, so an enabled client can never turn
  collection on by itself. A payload that fails schema validation is still
  refused 422 even then — fail-closed in both directions (nothing stored,
  and an invalid batch never gets a fake ack).
- A batch is bounded three times — by the event count (client and server
  agree on 25), by per-field length caps, and by a 64 KiB cap enforced on
  the raw body (Content-Length header and streaming byte count) before any
  JSON parsing — so one request can never make the backend buffer or parse
  more than a few tens of kilobytes, no matter what the client sends.
- Only fields the `hive.rum.v1` schema names are read; FastAPI is told to
  ignore extras and the store projects each event onto approved fields, so
  neither an over-eager client nor a crafted payload can widen what is
  stored.

Auth: AuthMiddleware, like every /v1 route. Ingest uses the session the
reporter already holds (`credentials: "same-origin"`), so a beacon is never
an unauthenticated write path.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from services.rum_store import (
    MAX_MAX_EVENTS,
    RUM_SCHEMA,
    ApiOutcome,
    WebVitalName,
    get_store,
    is_allowed_route,
    rum_ingest_enabled,
)

#: Mirrors the client's MAX_BATCH_EVENTS (rumSchema.ts). One source of truth
#: would be nicer; two files and a test pinning them together is the price
#: of a browser bundle that cannot import Python.
MAX_BATCH_EVENTS = 25

#: Hard ceiling on the encoded batch. 25 events x a few hundred bounded
#: bytes plus the envelope identifiers sits well under this, so it never
#: rejects a real reporter, but it bounds what the backend will read and
#: parse before the schema (`extra="ignore"` is applied only afterwards and
#: cannot bound the bytes FastAPI would otherwise receive in full).
MAX_BATCH_BYTES = 64 * 1024

REQUEST_ID_VALUE_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")
REQUEST_ID_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
IDENTIFIER_VALUE_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")

router = APIRouter(tags=["rum"])


class WebVitalEventIn(BaseModel):
    """One browser load-metric observation (`hive.rum.v1`)."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["web_vital"]
    name: WebVitalName
    value_ms: float = Field(ge=0, allow_inf_nan=False)
    route: str = Field(min_length=1, max_length=80)
    # Epoch milliseconds. Finite and non-negative: Python's JSON parser
    # accepts NaN/Infinity literals, and a retained non-finite value would
    # break the read-back endpoint's own serialization until eviction.
    ts: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("route")
    @classmethod
    def _route_charset(cls, value: str) -> str:
        if not is_allowed_route(value, event_type="web_vital"):
            raise ValueError("route template outside the hive.rum.v1 allowlist")
        return value


class ApiRequestEventIn(BaseModel):
    """One shared-client request observation (`hive.rum.v1`)."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["api_request"]
    method: str = Field(min_length=3, max_length=10)
    route: str = Field(min_length=1, max_length=80)
    status_class: Literal[0, 2, 3, 4, 5]
    outcome: ApiOutcome
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    request_id: str | None = Field(default=None, max_length=128)
    # Same contract as the web-vital timestamp above.
    ts: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("method")
    @classmethod
    def _method_charset(cls, value: str) -> str:
        if not value.isupper() or not value.isalpha():
            raise ValueError("method must be an upper-case HTTP verb")
        return value

    @field_validator("route")
    @classmethod
    def _route_charset(cls, value: str) -> str:
        if not is_allowed_route(value, event_type="api_request"):
            raise ValueError("route template outside the hive.rum.v1 allowlist")
        return value

    @field_validator("request_id")
    @classmethod
    def _request_id_charset(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not REQUEST_ID_VALUE_RE.fullmatch(value) or not REQUEST_ID_ALNUM_RE.search(value):
            # Same contract RequestIDMiddleware applies before echoing a
            # client id: the collector only ever stores ids that could have
            # come from the server.
            raise ValueError("request_id outside the X-Request-ID charset")
        return value


class RumBatchIn(BaseModel):
    """The `hive.rum.v1` envelope the reporter sends."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = Field(alias="schema")
    build_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=64)
    events: list[WebVitalEventIn | ApiRequestEventIn] = Field(
        min_length=1, max_length=MAX_BATCH_EVENTS
    )

    @field_validator("schema_version")
    @classmethod
    def _schema_matches(cls, value: str) -> str:
        if value != RUM_SCHEMA:
            raise ValueError(f"unsupported rum schema {value!r}; expected {RUM_SCHEMA!r}")
        return value

    @field_validator("build_id", "session_id")
    @classmethod
    def _identifier_charset(cls, value: str) -> str:
        if not IDENTIFIER_VALUE_RE.fullmatch(value):
            raise ValueError("identifier outside the hive.rum.v1 charset")
        return value


#: The ingest operation's OpenAPI face. The handler reads the body manually
#: (the 64 KiB cap must apply before FastAPI buffers or parses anything), so
#: FastAPI cannot infer the request body or the validation-error response from
#: the signature the way it does for every other route. Declaring them here
#: keeps `POST /v1/rum/events` documented with the same `RumBatchIn` schema and
#: 422 envelope the parameter-driven routes emit, which is what
#: `scripts/dump-hive-openapi.py` -> `npm run gen:api` regenerates
#: `src/api/types.gen.ts` from (the drift gate, #1048). `ensure_openapi_contract`
#: registers the referenced component schemas.
_INGEST_OPENAPI_EXTRA: dict[str, Any] = {
    "requestBody": {
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/RumBatchIn"}}},
        "required": True,
    },
    "responses": {
        "422": {
            "description": "Validation Error",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/HTTPValidationError"}}
            },
        },
    },
}


def ensure_openapi_contract(app: FastAPI) -> None:
    """Keep the `hive.rum.v1` ingest models in the app's OpenAPI document.

    The models are referenced only by ``openapi_extra`` above and by manual
    ``RumBatchIn.model_validate`` inside the handler, so FastAPI's automatic
    component collection never sees them and the references would dangle.
    The schemas are rendered by FastAPI itself, on a scratch app where the
    batch IS a declared body parameter — the exact rendering (field defaults,
    titles, required lists) a parameter-driven route gets, on this FastAPI
    version, rather than a hand-maintained copy that drifts from it.
    ``setdefault`` keeps the document's own rendering if a future change ever
    lets the real route emit the schemas natively again.
    """

    base_openapi = app.openapi

    def openapi_with_rum_contract() -> Any:
        if app.openapi_schema is not None:
            return app.openapi_schema
        document = base_openapi()
        schemas = document.setdefault("components", {}).setdefault("schemas", {})
        for name, schema in _ingest_component_schemas().items():
            schemas.setdefault(name, schema)
        app.openapi_schema = document
        return document

    app.openapi = openapi_with_rum_contract  # type: ignore[method-assign]


def _ingest_component_schemas() -> dict[str, Any]:
    """The three ingest schemas as FastAPI renders them for a body parameter."""

    scratch = FastAPI(version="rum-contract")

    @scratch.post("/rum-contract")
    def _contract(batch: RumBatchIn) -> dict[str, Any]:
        # Never called: the scratch app exists only for its OpenAPI rendering.
        return {"accepted": len(batch.events), "enabled": True}

    document = scratch.openapi()
    wanted = {WebVitalEventIn.__name__, ApiRequestEventIn.__name__, RumBatchIn.__name__}
    return {
        name: schema
        for name, schema in document.get("components", {}).get("schemas", {}).items()
        if name in wanted
    }


@router.post("/events", openapi_extra=_INGEST_OPENAPI_EXTRA)
async def ingest_events(request: Request, response: Response) -> dict[str, Any]:
    # Session context comes from AuthMiddleware upstream; the body is read
    # manually (not as a Pydantic parameter) so the byte cap below applies
    # before anything is buffered or parsed. The enabled check comes AFTER
    # read+validate on purpose: bytes are capped before parsing in every
    # state (the bound must not depend on configuration), while the pinned
    # fail-closed contract keeps a schema-invalid batch refused 422 even
    # while disabled — only a *valid* batch is acknowledged-and-discarded.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            declared = 0
        if declared > MAX_BATCH_BYTES:
            raise HTTPException(status_code=413, detail="rum batch exceeds byte limit")

    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_BATCH_BYTES:
            # Covers missing/spoofed Content-Length and chunked transfer
            # encoding: the cap holds even when the header lies.
            raise HTTPException(status_code=413, detail="rum batch exceeds byte limit")
        chunks.append(chunk)
    body = b"".join(chunks)

    try:
        payload = json.loads(body)
        batch = RumBatchIn.model_validate(payload)
    except (ValueError, ValidationError):
        # Same 422 FastAPI's envelope validation produced before this route
        # took over body parsing.
        raise HTTPException(status_code=422, detail="invalid rum batch") from None

    if not rum_ingest_enabled():
        # Explicitly disabled: acknowledge (202) so the reporter does not
        # churn, store nothing. An enabled client cannot switch collection on.
        response.status_code = 202
        return {"accepted": 0, "enabled": False}

    # The envelope's identifiers ride along: without them the ring could not
    # tell builds (or sessions) apart once more than one is resident.
    accepted = get_store().ingest(
        [event.model_dump() for event in batch.events],
        build_id=batch.build_id,
        session_id=batch.session_id,
    )
    return {"accepted": accepted, "enabled": True}


@router.get("/events")
def list_events(
    limit: int = Query(default=200, ge=1, le=MAX_MAX_EVENTS),
) -> dict[str, Any]:
    return get_store().list_events(limit=limit)


@router.get("/events/summary")
def summary() -> dict[str, Any]:
    return get_store().summary()
