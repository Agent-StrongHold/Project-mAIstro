"""Quota panel routes — backed by the LiteLLM proxy (LLM gateway).

conductor-router has been retired; this panel reads usage/spend and model
metadata from the LiteLLM proxy that replaced it.

Every handler answers with an envelope (#380, #389): the panel must be able
to say "measured", "no data", "unavailable" and "source error" apart. The
previous fallbacks were silent — `outcomes` was a hard-coded zeroed dict even
with the proxy up, `providers` reported `free_tokens: 0` for a quota concept
LiteLLM does not have, and every failure mode rendered as a healthy empty
page. An unmeasured quantity is `None`, never a plausible-looking zero.

Shapes: the envelope is a new outer object; the inner rows keep the field
names the React panel has always read, so the diff on the rendering side is
the state handling only.

Outcomes (#389): unlike the usage panels, outcomes has a canonical durable
owner in this tree — the same outcome store `services.feedback_service` binds
(thumbs feedback and run outcomes are recorded there as maistro `Outcome`
rows). This route reads that store's aggregate for the window, so `ok` means
measured data and zeros only ever mean genuinely no recorded outcomes —
empty-valid, not canned, and never hard-coded "unavailable" while a real
owner exists.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter
from services import feedback_service
from services.provider_usage import (
    TIMEOUT,
    _envelope,
    _headers,
    _litellm_base,
    _unconfigured,
    provider_panel,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quotas"])

# Days of outcome history the outcomes panel reports (#389).
OUTCOME_WINDOW_DAYS = 7


@router.get("/providers")
def list_providers() -> dict:
    """Per-provider token usage, aggregated from LiteLLM /global/spend/report.

    LiteLLM reports spend and tokens per (key, model); it does NOT expose a
    free-token quota concept, so free_tokens/remaining_tokens/limit/usage_pct
    stay `None` — the bar renders "unlimited" from `limit: null`, not from an
    invented 0%. See `provider_panel` for the request-count provenance.
    """
    return provider_panel()


@router.get("/outcomes")
async def list_outcomes() -> dict:
    """Success/failure outcome stats, from the canonical outcome store (#389).

    This panel used to return a hard-coded zeroed structure no event could
    ever change. Its owner is the same outcome store every other surface
    uses: `services.feedback_service` binds it (the engine bridge points it
    at the durable container store at boot), thumbs feedback and run outcomes
    are recorded there as maistro `Outcome` rows, and this route reads the
    aggregate for the last `OUTCOME_WINDOW_DAYS` window. `no_data` now means
    genuinely no recorded outcomes in the window — empty-valid, not canned —
    and a store read failure is an explicit `error` state, never a zeroed
    success.
    """
    source = "outcome store (services.feedback_service)"
    try:
        store = feedback_service.get_outcome_store()
        data = await store.get_task_completion_rate(days=OUTCOME_WINDOW_DAYS)
    except Exception as exc:
        logger.warning("outcomes panel: outcome store read failed: %s", exc)
        return _envelope(
            state="error",
            source=source,
            reason=f"{type(exc).__name__}: outcome store read failed; see server logs",
            window_days=OUTCOME_WINDOW_DAYS,
        )
    total = int(data.get("total", 0) or 0)
    return {
        **_envelope(
            state="ok" if total else "no_data",
            source=source,
            reason=None if total else "no outcomes recorded in the window",
            window_days=OUTCOME_WINDOW_DAYS,
        ),
        **data,
    }


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
