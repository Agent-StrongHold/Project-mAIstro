"""Quota panel routes — backed by the LiteLLM proxy (LLM gateway).

conductor-router has been retired; this panel reads usage/spend and model
metadata from the LiteLLM proxy that replaced it.

Every handler answers with an envelope (#380): the panel must be able to say
"measured", "no data", "unavailable" and "source error" apart. The previous
fallbacks were silent — `outcomes` was a hard-coded zeroed dict even with the
proxy up, `providers` reported `free_tokens: 0` for a quota concept LiteLLM
does not have, and every failure mode rendered as a healthy empty page. An
unmeasured quantity is `None`, never a plausible-looking zero.

Shapes: the envelope is a new outer object; the inner rows keep the field
names the React panel has always read, so the diff on the rendering side is
the state handling only.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Any

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


def _envelope(
    *,
    state: str,
    source: str,
    reason: str | None = None,
    window_days: int | None = None,
) -> dict:
    """Outer envelope every panel endpoint answers with."""
    return {
        "state": state,  # ok | no_data | unavailable | error
        "source": source,
        "window_days": window_days,
        "computed_at": _dt.datetime.now(_dt.UTC).isoformat(),
        "reason": reason,
    }


def _unconfigured() -> dict:
    return _envelope(
        state="unavailable",
        source="LiteLLM proxy",
        reason="LiteLLM proxy is not configured (no LITELLM_API_BASE / LITELLM_PROXY_URL)",
    )


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
def list_providers() -> dict:
    """Per-provider token usage, aggregated from LiteLLM /global/spend/report.

    LiteLLM reports spend and tokens per (key, model); it does NOT expose a
    free-token quota concept, so free_tokens/remaining_tokens/limit/usage_pct
    stay `None` — the bar renders "unlimited" from `limit: null`, not from an
    invented 0%. `request_count` is summed from the report's own
    `num_requests` fields when the proxy provides them, and is `None` (shown
    as "n/a") when it does not: a count nobody returned is not a count of 0.
    """
    source = "LiteLLM /global/spend/report"
    base = _litellm_base()
    if not base:
        return _unconfigured()
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
    except Exception as exc:
        logger.warning("Failed to fetch spend report from LiteLLM: %s", exc)
        return _envelope(
            state="error",
            source=source,
            reason=f"{type(exc).__name__}: spend report unreachable; see server logs",
            window_days=SPEND_WINDOW_DAYS,
        )

    try:
        provider_of = _model_provider_map(base)

        # provider -> {used_tokens, request_count, requests_measured}
        agg: dict[str, dict[str, Any]] = {}
        for row in rows:
            for detail in row.get("model_details", []):
                model = detail.get("model", "")
                provider = provider_of.get(model, "unknown")
                tokens = int(detail.get("total_input_tokens", 0) or 0) + int(
                    detail.get("total_output_tokens", 0) or 0
                )
                bucket = agg.setdefault(
                    provider, {"used_tokens": 0, "request_count": 0, "requests_measured": False}
                )
                bucket["used_tokens"] = int(bucket["used_tokens"]) + tokens
                raw_count = detail.get("num_requests")
                if raw_count is not None:
                    bucket["requests_measured"] = True
                    bucket["request_count"] = int(bucket["request_count"]) + int(raw_count)

        result = []
        for provider, bucket in sorted(agg.items()):
            used = int(bucket["used_tokens"])
            result.append(
                {
                    "provider": provider.title(),
                    # "active" here means: this provider shows spend in the
                    # report window. That is evidence; there is no richer
                    # health signal to claim.
                    "status": "active",
                    "billing_cycle": "monthly",
                    "cycle_key": today.strftime("%Y-%m"),
                    "used_tokens": used,
                    # LiteLLM exposes no quota/free-token concept.
                    "free_tokens": None,
                    "remaining_tokens": None,
                    "limit": None,
                    "usage_pct": None,
                    "request_count": int(bucket["request_count"])
                    if bucket["requests_measured"]
                    else None,
                    "unit": "tokens",
                }
            )
        return {
            **_envelope(
                state="ok" if result else "no_data",
                source=source,
                reason=None if result else "no spend recorded in the window",
                window_days=SPEND_WINDOW_DAYS,
            ),
            "providers": result,
        }
    except Exception as exc:
        logger.warning("Failed to aggregate spend report from LiteLLM: %s", exc)
        return _envelope(
            state="error",
            source=source,
            reason=f"{type(exc).__name__}: spend report could not be aggregated; see server logs",
            window_days=SPEND_WINDOW_DAYS,
        )


@router.get("/outcomes")
def list_outcomes() -> dict:
    """Success/failure outcome stats: explicitly unavailable, never zeros.

    LiteLLM has no native aggregated success/failure-rate endpoint that maps
    onto this shape. The handler used to paper over that with a zeroed
    structure, which rendered "0 requests, 100% failure" look-alikes on every
    deployment (#380). Until a /spend/logs-derived implementation exists, the
    panel says the measurement is unavailable.
    """
    source = "LiteLLM /global/spend/logs (aggregated success/failure — not implemented)"
    base = _litellm_base()
    if not base:
        return _envelope(
            state="unavailable",
            source=source,
            reason="LiteLLM proxy is not configured, and no aggregated outcome source exists",
        )
    return _envelope(
        state="unavailable",
        source=source,
        reason=(
            "LiteLLM exposes no aggregated success/failure endpoint this panel "
            "can name; outcomes are not measured, not zero"
        ),
    )


@router.get("/models")
def list_models() -> dict:
    """Registered models + metadata, from LiteLLM /model/info.

    LiteLLM does not expose tier/quality/speed/usage scores. Those fields used
    to default to invented neutrals (`quality: 0.0` rendered as a real 0%
    bar, `tier: "medium"` as a real tier); when the proxy does not provide
    them they are `None` now and the panel shows "n/a" instead (#380).
    provider, context window, and modality are populated from model_info
    where available.
    """
    source = "LiteLLM /model/info"
    base = _litellm_base()
    if not base:
        return _unconfigured()
    try:
        r = httpx.get(f"{base}/model/info", headers=_headers(), timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as exc:
        logger.warning("Failed to fetch models from LiteLLM: %s", exc)
        return _envelope(
            state="error",
            source=source,
            reason=f"{type(exc).__name__}: model registry unreachable; see server logs",
        )

    try:
        result = []
        for entry in data:
            name = entry.get("model_name", "")
            info = entry.get("model_info") or {}
            context = info.get("max_input_tokens") or info.get("max_tokens")
            result.append(
                {
                    "model": name,
                    "provider": info.get("litellm_provider") or "unknown",
                    "tier": info.get("tier"),
                    "quality": info.get("quality"),
                    "speed": info.get("speed"),
                    "usage_pct": info.get("usage_pct"),
                    "available": info.get("available", True),
                    "context": context,
                    "modality": info.get("mode"),
                    "strengths": info.get("strengths", []),
                }
            )
        return {
            **_envelope(
                state="ok" if result else "no_data",
                source=source,
                reason=None if result else "no models registered in the proxy",
            ),
            "models": result,
        }
    except Exception as exc:
        logger.warning("Failed to map models from LiteLLM: %s", exc)
        return _envelope(
            state="error",
            source=source,
            reason=f"{type(exc).__name__}: model registry could not be mapped; see server logs",
        )
