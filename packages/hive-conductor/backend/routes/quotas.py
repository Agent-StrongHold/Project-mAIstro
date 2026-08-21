"""Quota panel routes — backed by the LiteLLM proxy (LLM gateway).

conductor-router has been retired; this panel now reads usage/spend and model
metadata from the LiteLLM proxy that replaced it. The data SOURCE changed; the
response SHAPES are unchanged so the React frontend (Quotas.tsx) keeps working.

Endpoint mapping (LiteLLM proxy):
- /v1/quotas/providers -> GET /global/spend/report  (spend aggregated per provider)
- /v1/quotas/models    -> GET /model/info           (registered models + metadata)
- /v1/quotas/outcomes  -> no native LiteLLM success/failure-rate endpoint; returns
                          the zeroed fallback shape (see _fallback_outcomes).

Every handler keeps the original graceful try/except -> fallback behavior: on any
error (or no LiteLLM config) it returns the fallback shape and never raises.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os

import httpx
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quotas"])

TIMEOUT = 8.0
# How many days of spend history to aggregate for the providers panel.
SPEND_WINDOW_DAYS = 30


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


def _fallback_providers() -> list[dict]:
    return []


def _fallback_models() -> list[dict]:
    return []


def _fallback_outcomes() -> dict:
    return {"total": 0, "succeeded": 0, "failed": 0, "rate": 0.0, "by_model": {}, "days": 7}


def _model_provider_map(base: str) -> dict[str, str]:
    """Map model_name -> provider via LiteLLM /model/info. Best-effort; {} on error."""
    try:
        r = httpx.get(f"{base}/model/info", headers=_headers(), timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception:
        logger.debug("model/info lookup failed during provider aggregation")
        return {}
    mapping: dict[str, str] = {}
    for entry in data:
        name = entry.get("model_name")
        info = entry.get("model_info") or {}
        if name:
            mapping[name] = info.get("litellm_provider") or "unknown"
    return mapping


@router.get("/providers")
def list_providers() -> list[dict]:
    """Per-provider token usage, aggregated from LiteLLM /global/spend/report.

    LiteLLM reports spend per (key, model); it does NOT expose free-token quotas,
    so free_tokens/remaining_tokens/limit/usage_pct default to 0/None. Tokens are
    summed (input + output) and grouped by the model's litellm_provider.
    """
    base = _litellm_base()
    if not base:
        return _fallback_providers()
    try:
        today = _dt.date.today()
        start = today - _dt.timedelta(days=SPEND_WINDOW_DAYS)
        r = httpx.get(
            f"{base}/global/spend/report",
            params={"start_date": start.isoformat(), "end_date": today.isoformat()},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        rows = r.json()

        provider_of = _model_provider_map(base)

        # provider -> {used_tokens, request_count}
        agg: dict[str, dict[str, float]] = {}
        for row in rows:
            for detail in row.get("model_details", []):
                model = detail.get("model", "")
                provider = provider_of.get(model, "unknown")
                tokens = int(detail.get("total_input_tokens", 0) or 0) + int(
                    detail.get("total_output_tokens", 0) or 0
                )
                bucket = agg.setdefault(provider, {"used_tokens": 0, "request_count": 0})
                bucket["used_tokens"] += tokens

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
    except Exception:
        logger.warning("Failed to fetch spend report from LiteLLM, using fallback")
        return _fallback_providers()


@router.get("/outcomes")
def list_outcomes() -> dict:
    """Success/failure outcome stats.

    LiteLLM has no native aggregated success/failure-rate endpoint that maps onto
    this shape, so this returns the zeroed fallback structure. Preserved as a
    handler (rather than dropped) to keep the frontend contract intact and leave a
    seam for a future /spend/logs-derived implementation.
    """
    base = _litellm_base()
    if not base:
        return _fallback_outcomes()
    # No reliable mapping available today; return the documented fallback shape.
    logger.debug("outcomes panel: LiteLLM exposes no success/failure aggregate; using fallback")
    return _fallback_outcomes()


@router.get("/models")
def list_models() -> list[dict]:
    """Registered models + metadata, from LiteLLM /model/info.

    LiteLLM does not expose tier/quality/speed/usage scores, so those default to
    the same neutral values the old conductor-router fallback used. provider,
    context window, and modality are populated from model_info where available.
    """
    base = _litellm_base()
    if not base:
        return _fallback_models()
    try:
        r = httpx.get(f"{base}/model/info", headers=_headers(), timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", [])
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
    except Exception:
        logger.warning("Failed to fetch models from LiteLLM, using fallback")
        return _fallback_models()
