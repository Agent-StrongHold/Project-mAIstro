"""Automated OpenRouter quota verification — a runnable check over the provider's
own ground-truth endpoints, for the reconciliation layer and for operators.

    python -m maistro.quota.verify            # human-readable report
    python -m maistro.quota.verify --json     # machine-readable

Reads two keys from the environment (never printed):

* ``OPENROUTER_API_KEY``    — inference key: `GET /api/v1/key` (credit balance,
  free-tier status).
* ``OPENROUTER_MANAGE_KEY`` — management/provisioning key: `GET /api/v1/activity`
  (per-model requests/tokens/cost). Optional — if absent, the per-model section
  is skipped (the inference key gets 403 on /activity).

The free-tier daily request cap is derived from the account tier: OpenRouter
grants 1000 :free requests/day once >=$10 has been PURCHASED lifetime (else 50);
``is_free_tier == False`` on /key means the account has paid before.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime

import httpx

from maistro.http import shared_client
from maistro.quota.verifiers.openrouter import (
    FREE_MODEL_RPD_NO_CREDITS,
    FREE_MODEL_RPD_WITH_CREDITS,
    OpenRouterActivityVerifier,
)

_BASE_URL = "https://openrouter.ai/api/v1"


async def _get_key_status(api_key: str, *, base_url: str = _BASE_URL) -> dict[str, object]:
    async with shared_client(timeout=15.0) as client:
        r = await client.get(f"{base_url}/key", headers={"Authorization": f"Bearer {api_key}"})
        r.raise_for_status()
        data = r.json().get("data")
        return data if isinstance(data, dict) else {}


async def gather_report(inference_key: str, management_key: str | None) -> dict[str, object]:
    """Collect the full quota picture. Pure data — no printing — so it's reusable
    by the reconciliation layer, tests, and the CLI."""
    key = await _get_key_status(inference_key)
    is_free_tier = bool(key.get("is_free_tier"))
    # is_free_tier False => has purchased before => the raised free cap applies.
    free_rpd_cap = FREE_MODEL_RPD_NO_CREDITS if is_free_tier else FREE_MODEL_RPD_WITH_CREDITS

    report: dict[str, object] = {
        "credit_limit": key.get("limit"),
        "credit_remaining": key.get("limit_remaining"),
        "usage_all_time": key.get("usage"),
        "usage_daily": key.get("usage_daily"),
        "is_free_tier": is_free_tier,
        "free_rpd_cap": free_rpd_cap,
    }

    if management_key:
        verifier = OpenRouterActivityVerifier(management_key, free_rpd_limit=free_rpd_cap)
        # Scope both the per-model breakdown and the free-requests-remaining count to
        # the current UTC day — the day the :free caps reset on. The default
        # /activity window is the last 30 completed days and excludes today.
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        activity = await verifier.fetch_activity(date=today)
        snapshot = await verifier.verify(date=today)
        report["free_requests_remaining"] = snapshot.remaining
        report["activity"] = [
            {
                "model": u.model,
                "requests": u.requests,
                "cost_usd": u.cost_usd,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
            }
            for u in activity
        ]
    return report


def _render(report: dict[str, object]) -> str:
    lines = ["OpenRouter quota:"]
    rem = report.get("credit_remaining")
    lines.append(
        f"  paid credit: remaining={'unlimited' if rem is None else f'${rem}'} "
        f"used_all_time=${report.get('usage_all_time')} used_today=${report.get('usage_daily')}"
    )
    tier = "paid (>=1 purchase)" if not report["is_free_tier"] else "free (never purchased)"
    lines.append(f"  free tier: {tier} -> {report['free_rpd_cap']} :free requests/day")
    if "free_requests_remaining" in report:
        rem_free = report["free_requests_remaining"]
        rem_free_n = int(rem_free) if isinstance(rem_free, int | float) else 0
        lines.append(f"  free requests remaining today: {rem_free_n}")
        activity = report.get("activity") or []
        if activity:
            lines.append("  per-model activity:")
            for u in activity[:20]:  # type: ignore[index]
                lines.append(
                    f"    {u['model']}: reqs={u['requests']} ${u['cost_usd']:.4f} "
                    f"in={u['prompt_tokens']} out={u['completion_tokens']}"
                )
    else:
        lines.append("  (per-model activity skipped — set OPENROUTER_MANAGE_KEY)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maistro.quota.verify")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    inference_key = os.environ.get("OPENROUTER_API_KEY")
    if not inference_key:
        print("error: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2
    management_key = os.environ.get("OPENROUTER_MANAGE_KEY")

    try:
        report = asyncio.run(gather_report(inference_key, management_key))
    except httpx.HTTPError as exc:
        print(f"error: quota check failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2) if args.json else _render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
