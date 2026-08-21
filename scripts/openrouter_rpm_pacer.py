#!/usr/bin/env python
"""Pace LiteLLM's OpenRouter ``:free`` deployments against the daily 1000-RPD budget.

OpenRouter caps free-model requests at ``FREE_MODEL_HAS_CREDITS_RPD`` (1000/day for
accounts that have purchased >= $10 credits) and the limit is shared globally across
the whole account — making more API keys does not raise it. OpenRouter exposes the
running daily count via the Analytics API (management key), not on the inference key.

Operator pacing rule:
    if usage < COMFORT_THRESHOLD:       rpm = DEFAULT_RPM                 (free-flow)
    else:                               rpm = (RPD - usage) / minutes-to-UTC-midnight
                                                            (spread the rest over the window)

This script reads today's free-model request count, computes the rpm, and updates
every ``openrouter/*`` deployment in LiteLLM via ``/model/update`` so the router's
headroom-aware routing backs off as the daily budget drains. Run it periodically
(every few minutes) — it is idempotent.

Config (env, with a .env fallback): LITELLM_BASE_URL, LITELLM_MASTER_KEY,
OPENROUTER_MANAGE_KEY. Override the .env path with --env-file.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

RPD = 1000
COMFORT_THRESHOLD = 600
DEFAULT_RPM = 5


def _load_env(env_file: Path) -> dict[str, str]:
    """Read KEY=VALUE lines from a .env file (no interpolation)."""
    out: dict[str, str] = {}
    if not env_file.is_file():
        return out
    for line in env_file.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def _cfg(env_file: Path) -> dict[str, str]:
    cfg = _load_env(env_file)
    for k in ("LITELLM_BASE_URL", "LITELLM_MASTER_KEY", "OPENROUTER_MANAGE_KEY"):
        v = _env(k)
        if v:
            cfg[k] = v
    return cfg


def _env(key: str) -> str | None:
    import os

    return os.environ.get(key)


def free_usage_today(mgmt_key: str) -> int:
    """Sum today's free-model request count (free models report $0 usage)."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    r = httpx.get(
        f"https://openrouter.ai/api/v1/analytics?date={today}",
        headers={"Authorization": f"Bearer {mgmt_key}"},
        timeout=20.0,
    )
    r.raise_for_status()
    rows = r.json().get("data", []) or []
    return sum(
        x.get("requests", 0)
        for x in rows
        if float(x.get("usage", 0) or 0) == 0 and float(x.get("byok_usage_inference", 0) or 0) == 0
    )


def minutes_to_utc_midnight() -> float:
    now = datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1.0, (midnight - now).total_seconds() / 60.0)


def target_rpm(usage: int) -> int:
    """Operator rule: free-flow under 600, else spread the remainder to UTC midnight."""
    if usage < COMFORT_THRESHOLD:
        return DEFAULT_RPM
    return max(0, round((RPD - usage) / minutes_to_utc_midnight()))


def openrouter_deployments(base: str, master_key: str) -> list[tuple[str, str, int]]:
    """Return (model_name, model_info.id, current_rpm) for every openrouter/* deployment."""
    r = httpx.get(
        f"{base}/model/info",
        headers={"Authorization": f"Bearer {master_key}"},
        timeout=15.0,
    )
    r.raise_for_status()
    out = []
    for m in r.json().get("data", []):
        lp = m.get("litellm_params", {})
        if str(lp.get("model", "")).startswith("openrouter/"):
            mid = (m.get("model_info") or {}).get("id")
            if mid:
                out.append((m.get("model_name", "?"), mid, lp.get("rpm")))
    return out


def update_rpm(base: str, master_key: str, model_id: str, rpm: int) -> int:
    r = httpx.post(
        f"{base}/model/update",
        headers={"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"},
        json={"litellm_params": {"rpm": rpm}, "model_info": {"id": model_id}},
        timeout=15.0,
    )
    return r.status_code


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-file", type=Path, default=Path("C:/maistro/.env"))
    ap.add_argument("--once", action="store_true", help="run a single update and exit")
    ap.add_argument("--interval", type=int, default=300, help="loop seconds (default 300)")
    args = ap.parse_args()

    cfg = _cfg(args.env_file)
    base = (cfg.get("LITELLM_BASE_URL") or "http://localhost:4000").rstrip("/")
    llm_key = cfg.get("LITELLM_MASTER_KEY")
    or_key = cfg.get("OPENROUTER_MANAGE_KEY")
    if not (llm_key and or_key):
        print("LITELLM_MASTER_KEY / OPENROUTER_MANAGE_KEY missing", file=sys.stderr)
        return 2

    def step() -> None:
        usage = free_usage_today(or_key)
        rpm = target_rpm(usage)
        mins = minutes_to_utc_midnight()
        deps = openrouter_deployments(base, llm_key)
        ts = datetime.now(UTC).isoformat(timespec="seconds")
        print(
            f"[{ts}] free usage today={usage}/{RPD} | mins->midnight={mins:.0f} | "
            f"target rpm={rpm} | OR deployments={len(deps)}"
        )
        changed = 0
        for name, mid, cur in deps:
            if cur == rpm:
                continue
            st = update_rpm(base, llm_key, mid, rpm)
            flag = "ok" if st == 200 else f"HTTP {st}"
            print(f"  {name:28s} {cur}->{rpm}  [{flag}]")
            changed += 1 if st == 200 else 0
        if not changed:
            print("  (all already at target rpm)")

    if args.once:
        step()
        return 0
    while True:
        try:
            step()
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
        import time

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
