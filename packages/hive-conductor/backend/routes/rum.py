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
  collection on by itself.
- A batch is bounded twice — by the event count (client and server agree on
  25) and by per-field length caps — so one request can carry at most a few
  tens of kilobytes no matter what the client sends.
- Only fields the `hive.rum.v1` schema names are read; FastAPI is told to
  ignore extras and the store projects each event onto approved fields, so
  neither an over-eager client nor a crafted payload can widen what is
  stored.

Auth: AuthMiddleware, like every /v1 route. Ingest uses the session the
reporter already holds (`credentials: "same-origin"`), so a beacon is never
an unauthenticated write path.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from services.rum_store import (
    MAX_MAX_EVENTS,
    RUM_SCHEMA,
    ApiOutcome,
    WebVitalName,
    get_store,
    rum_ingest_enabled,
)

#: Mirrors the client's MAX_BATCH_EVENTS (rumSchema.ts). One source of truth
#: would be nicer; two files and a test pinning them together is the price
#: of a browser bundle that cannot import Python.
MAX_BATCH_EVENTS = 25

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
    ts: float

    @field_validator("route")
    @classmethod
    def _route_charset(cls, value: str) -> str:
        # A route template is built from path characters only; anything else
        # (a URL with a query string, a fragment, whitespace) is a client
        # that skipped redaction, and the event is refused rather than
        # sanitized silently.
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_.*-")
        if not set(value) <= allowed:
            raise ValueError("route template outside the hive.rum.v1 charset")
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
    ts: float

    @field_validator("method")
    @classmethod
    def _method_charset(cls, value: str) -> str:
        if not value.isupper() or not value.isalpha():
            raise ValueError("method must be an upper-case HTTP verb")
        return value

    @field_validator("route")
    @classmethod
    def _route_charset(cls, value: str) -> str:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_.*-")
        if not set(value) <= allowed:
            raise ValueError("route template outside the hive.rum.v1 charset")
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


@router.post("/events")
def ingest_events(batch: RumBatchIn, request: Request, response: Response) -> dict[str, Any]:
    del request  # session context comes from AuthMiddleware upstream
    if not rum_ingest_enabled():
        # Explicitly disabled: acknowledge (202) so the reporter does not
        # churn, store nothing. An enabled client cannot switch collection on.
        response.status_code = 202
        return {"accepted": 0, "enabled": False}
    accepted = get_store().ingest([event.model_dump() for event in batch.events])
    return {"accepted": accepted, "enabled": True}


@router.get("/events")
def list_events(
    limit: int = Query(default=200, ge=1, le=MAX_MAX_EVENTS),
) -> dict[str, Any]:
    return get_store().list_events(limit=limit)


@router.get("/events/summary")
def summary() -> dict[str, Any]:
    return get_store().summary()
