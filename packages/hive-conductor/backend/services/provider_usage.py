"""The one LiteLLM-backed provider usage panel (#389, #380).

`GET /v1/quotas/providers` and `GET /v1/settings/quotas` both serve
`provider_panel`: one aggregation, one envelope, one source of truth. The
panel lives here -- outside any single router -- so a surface that needs it
delegates to this module instead of importing another router file (routes are
presentation; the retirement ledger forbids a router gaining consumers,
`quality/workspace-retirement.json`).

Every handler answers with an envelope (#380, #389): the panel must be able
to say "measured", "no data", "unavailable" and "source error" apart. The
previous fallbacks were silent -- `providers` reported `free_tokens: 0` for a
quota concept LiteLLM does not have, and every failure mode rendered as a
healthy empty page. An unmeasured quantity is `None`, never a
plausible-looking zero.

Shapes: the envelope is a new outer object; the inner rows keep the field
names the React panel has always read.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

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
    """Map model_name -> provider via LiteLLM /model/info. Best-effort; {} on error.

    A failed lookup here degrades attribution (providers read "unknown"), not
    the route: the spend data itself is still real, so the panel stays up.
    """
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


def provider_panel() -> dict:
    """Per-provider token usage and request counts — the canonical owner (#389).

    Aggregated from LiteLLM /global/spend/report. `request_count` uses the
    report's own per-model counts wherever they are reported —
    `num_requests`, or `usage.api_requests` / `api_requests` (#389) — and is
    `None` (shown as "n/a") when no source reports one: a count nobody
    returned is not a count of 0. `GET /v1/settings/quotas` delegates here
    rather than maintaining a second source that would drift.
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
                usage = detail.get("usage") or {}
                raw_count = detail.get("num_requests")
                if raw_count is None:
                    raw_count = usage.get("api_requests")
                if raw_count is None:
                    raw_count = detail.get("api_requests")
                bucket = agg.setdefault(
                    provider, {"used_tokens": 0, "request_count": 0, "requests_measured": False}
                )
                bucket["used_tokens"] = int(bucket["used_tokens"]) + tokens
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
