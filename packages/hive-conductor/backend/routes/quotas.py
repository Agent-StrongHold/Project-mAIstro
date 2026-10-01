"""Quota panel routes — backed by the LiteLLM proxy (LLM gateway).

conductor-router has been retired; this panel now reads usage/spend and model
metadata from the LiteLLM proxy that replaced it. The data SOURCE changed; the
response SHAPES are unchanged so the React frontend (Quotas.tsx) keeps working.

Endpoint mapping (LiteLLM proxy):
- /v1/quotas/providers -> GET /global/spend/report  (spend aggregated per provider;
  request_count from each model's `usage.api_requests`, 0 when the proxy's
  report omits it — reported, not invented)
- /v1/quotas/models    -> GET /model/info           (registered models + metadata)
- /v1/quotas/outcomes  -> the canonical outcome store (maistro
  `Outcome` records, the same store thumbs feedback writes), not a canned
  zero (#389)

Failure is distinct from empty (#389): an unreachable or unconfigured LiteLLM
proxy is a `503` with the reason — never a `200` empty/zeroed payload. `200`
with `[]`/zeros means the source answered and genuinely holds nothing.

Every handler keeps the response SHAPE the frontend depends on.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException
from services import feedback_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quotas"])

TIMEOUT = 8.0
# How many days of spend history to aggregate for the providers panel.
SPEND_WINDOW_DAYS = 30
# Days of outcome history the outcomes panel reports.
OUTCOME_WINDOW_DAYS = 7


class QuotaSourceUnavailable(RuntimeError):
    """The LiteLLM proxy is unconfigured or unreachable.

    Raised, not swallowed: an unavailable source and a genuinely empty one
    must not look the same on the wire (#389).
    """


def _litellm_base() -> str:
    """LiteLLM proxy base URL, mirroring settings.py env-var precedence.

    CONDUCTOR_ROUTER_URL is kept only as a last-resort legacy fallback.
    """
    return (
        os.environ.get("LITELLM_API_BASE")
        or os.environ.get("LITELLM_PROXY_URL")
        or os.environ.get("CONDUCTOR_ROUTER_URL")
        or ""
    ).rstrip("/")


def _litellm_key() -> str:
    return (
        os.environ.get("LITELLM_API_KEY")
        or os.environ.get("LITELLM_PROXY_KEY")
        or os.environ.get("ROUTER_API_KEY")
        or ""
    )


def _headers() -> dict[str, str]:
    key = _litellm_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _require_base() -> str:
    base = _litellm_base()
    if not base:
        raise QuotaSourceUnavailable(
            "LiteLLM proxy is not configured (set LITELLM_API_BASE); the quota "
            "panel has no usage source to query"
        )
    return base


def _fetch(base: str, path: str, params: dict[str, str] | None = None) -> object:
    """GET a LiteLLM endpoint, mapping transport failures to one exception."""
    try:
        r = httpx.get(f"{base}{path}", params=params, headers=_headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        raise QuotaSourceUnavailable(f"LiteLLM proxy {path} request failed: {exc}") from exc


def _model_provider_map(base: str) -> dict[str, str]:
    """Map model_name -> provider via LiteLLM /model/info. Best-effort.

    A failed lookup here degrades attribution (providers read "unknown"), not
    the route: the spend data itself is still real, so the panel stays up.
    """
    try:
        data = _fetch(base, "/model/info").get("data", [])  # type: ignore[union-attr]
    except QuotaSourceUnavailable:
        logger.debug("model/info lookup failed during provider aggregation")
        return {}
    mapping: dict[str, str] = {}
    for entry in data:
        name = entry.get("model_name")
        info = entry.get("model_info") or {}
        if name:
            mapping[name] = info.get("litellm_provider") or "unknown"
    return mapping


def provider_panel() -> list[dict]:
    """Per-provider token usage and request counts (#389).

    Aggregated from LiteLLM /global/spend/report; `request_count` sums each
    model entry's `usage.api_requests` (0 when the proxy's report omits it).
    LiteLLM reports spend per (key, model); it does NOT expose free-token
    quotas, so free_tokens/remaining_tokens/limit/usage_pct default to
    0/None. Tokens are summed (input + output) and grouped by the model's
    litellm_provider. Raises `QuotaSourceUnavailable` — the route turns that
    into 503 so an unreachable gateway is never served as an empty panel.
    """
    base = _require_base()
    today = _dt.date.today()
    start = today - _dt.timedelta(days=SPEND_WINDOW_DAYS)
    rows = _fetch(
        base,
        "/global/spend/report",
        params={"start_date": start.isoformat(), "end_date": today.isoformat()},
    )

    provider_of = _model_provider_map(base)

    # provider -> {used_tokens, request_count}
    agg: dict[str, dict[str, int]] = {}
    for row in rows:  # type: ignore[union-attr]
        for detail in row.get("model_details", []):
            model = detail.get("model", "")
            provider = provider_of.get(model, "unknown")
            tokens = int(detail.get("total_input_tokens", 0) or 0) + int(
                detail.get("total_output_tokens", 0) or 0
            )
            usage = detail.get("usage") or {}
            requests = int(usage.get("api_requests", 0) or 0) or int(
                detail.get("api_requests", 0) or 0
            )
            bucket = agg.setdefault(provider, {"used_tokens": 0, "request_count": 0})
            bucket["used_tokens"] += tokens
            bucket["request_count"] += requests

    result = []
    for provider, bucket in sorted(agg.items()):
        used = int(bucket["used_tokens"])
        result.append(
            {
                "provider": provider.title(),
                "status": "active",
                "billing_cycle": "monthly",
                "cycle_key": today.strftime("%Y-%m"),
                "used_tokens": used,
                # LiteLLM exposes no quota/free-token concept.
                "free_tokens": 0,
                "remaining_tokens": 0,
                "limit": None,
                "usage_pct": 0.0,
                "request_count": int(bucket["request_count"]),
                "unit": "tokens",
            }
        )
    return result


@router.get("/providers")
def list_providers() -> list[dict]:
    """Per-provider usage from LiteLLM /global/spend/report.

    `503` when the LiteLLM proxy is unconfigured or unreachable (#389) — an
    unavailable source must be distinguishable from a genuinely empty one,
    which is `200 []`.
    """
    try:
        return provider_panel()
    except QuotaSourceUnavailable as exc:
        logger.warning("providers panel: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/outcomes")
async def list_outcomes() -> dict:
    """Success/failure outcome stats, from the canonical outcome store (#389).

    This panel used to return a hard-coded zeroed structure no event could
    ever change. Its owner is the same outcome store every other surface
    uses: `services.feedback_service` binds it (the engine bridge points it
    at the durable container store at boot), thumbs feedback and run outcomes
    are recorded there as maistro `Outcome` rows, and this route reads the
    aggregate for the last `days` window. Zeros now mean genuinely no
    recorded outcomes in the window — empty-valid, not canned. A store
    failure is a `503`, never a zeroed success.
    """
    try:
        store = feedback_service.get_outcome_store()
        return await store.get_task_completion_rate(days=OUTCOME_WINDOW_DAYS)
    except Exception as exc:
        logger.warning("outcomes panel: outcome store read failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"outcome store read failed: {exc}") from exc


@router.get("/models")
def list_models() -> list[dict]:
    """Registered models + metadata, from LiteLLM /model/info.

    LiteLLM does not expose tier/quality/speed/usage scores, so those default
    to the same neutral values the old conductor-router fallback used.
    provider, context window, and modality are populated from model_info where
    available. `503` when the proxy is unconfigured or unreachable (#389).
    """
    try:
        base = _require_base()
        data = _fetch(base, "/model/info").get("data", [])  # type: ignore[union-attr]
    except QuotaSourceUnavailable as exc:
        logger.warning("models panel: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    result = []
    for entry in data:
        name = entry.get("model_name", "")
        info = entry.get("model_info") or {}
        context = info.get("max_input_tokens") or info.get("max_tokens")
        result.append(
            {
                "model": name,
                "provider": info.get("litellm_provider", "unknown"),
                "tier": info.get("tier", "medium"),
                "quality": info.get("quality", 0.0),
                "speed": info.get("speed", 0),
                "usage_pct": info.get("usage_pct", 0.0),
                "available": info.get("available", True),
                "context": context,
                "modality": info.get("mode"),
                "strengths": info.get("strengths", []),
            }
        )
    return result
