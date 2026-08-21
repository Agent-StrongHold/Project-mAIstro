"""Discover, benchmark, and select the best LiteLLM models for builders routing.

Two tiers, two different probes:

  fast    — latency ≤ 3s, simple add() correctness test
  capable — latency ≤ 20s, multi-step fibonacci reasoning test

Scoring: quality_pass * 1000 / latency_ms
         (ties broken by cost: cheaper model wins)

Quota/cost data is fetched from /model/info and folded into the output.
Cache lives at ~/.config/maistro/builders/model_cache.json, TTL 24 h.

Standalone:
    python -m maistro_bootstrap.builders.model_selector [--top N]
    python -m maistro_bootstrap.builders.model_selector --models gemini-flash cerebras-llama3.1-8b
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CACHE_PATH = Path.home() / ".config" / "maistro" / "builders" / "model_cache.json"
CACHE_TTL_SECONDS = 86_400  # 24 h

_SKIP_KEYWORDS = (
    "embed",
    "imagen",
    "image",
    "flux",
    "tts",
    "whisper",
    "dall-e",
    "video",
    "sora",
    "kling",
    "seedance",
    "kontext",
    "codestral-embed",
    "e5-mistral",
    "gemini-embedding",
)

_FAST_LATENCY_CAP_S = 3.0
_CAPABLE_LATENCY_CAP_S = 20.0
_MAX_CONCURRENT = 12

# ---------------------------------------------------------------------------
# Tiered quality probes
# ---------------------------------------------------------------------------

# Fast: trivial — every working model should pass; latency is the differentiator.
_FAST_PROBE: dict[str, str] = {
    "prompt": (
        "Write ONLY a Python function called `add` that takes two integers and returns their sum. "
        "No imports. No explanation. No markdown fences. Just the function definition."
    ),
    "test": "print(add(3, 4))",
    "expected": "7",
}

# Capable: multi-case reasoning — models that hallucinate base cases fail here.
_CAPABLE_PROBE: dict[str, str] = {
    "prompt": (
        "Write ONLY a Python function called `fibonacci` that returns the nth Fibonacci number "
        "(0-indexed: fibonacci(0)=0, fibonacci(1)=1, fibonacci(2)=1, fibonacci(10)=55). "
        "No imports. No explanation. No markdown fences. Just the function definition."
    ),
    "test": "print(fibonacci(0))\nprint(fibonacci(1))\nprint(fibonacci(10))",
    "expected": "0\n1\n55",
}


# ---------------------------------------------------------------------------
# Gateway helpers
# ---------------------------------------------------------------------------


def _base_url() -> str:
    return (
        os.environ.get("LITELLM_URL")
        or os.environ.get("LITELLM_BASE_URL")
        or os.environ.get("LITELLM_PROXY_URL")
        or ""
    ).rstrip("/")


def _api_key() -> str:
    return os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("LITELLM_PROXY_KEY") or ""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}"}


def _is_text_model(model_id: str) -> bool:
    low = model_id.lower()
    return not any(kw in low for kw in _SKIP_KEYWORDS)


def discover_models(client: httpx.Client) -> list[str]:
    resp = client.get(f"{_base_url()}/v1/models", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", []) if _is_text_model(m["id"])]


def fetch_model_info(client: httpx.Client) -> dict[str, dict[str, Any]]:
    """Return per-model quota + cost from /model/info.

    Keys returned per model:
      input  — cost per input token (USD)
      output — cost per output token (USD)
      rpm    — requests per minute limit (from litellm_params)
      tpm    — tokens per minute limit
      max_budget      — budget cap (USD) per budget_duration
      budget_duration — '1d', '30d', etc.
    """
    info_map: dict[str, dict[str, Any]] = {}
    try:
        resp = client.get(f"{_base_url()}/model/info", headers=_headers(), timeout=10)
        resp.raise_for_status()
        for entry in resp.json().get("data", []):
            mid = entry.get("model_name") or entry.get("id", "")
            if not mid:
                continue
            mi = entry.get("model_info") or {}
            lp = entry.get("litellm_params") or {}
            info_map[mid] = {
                "input": mi.get("input_cost_per_token") or 0.0,
                "output": mi.get("output_cost_per_token") or 0.0,
                "rpm": lp.get("rpm"),
                "tpm": lp.get("tpm"),
                "max_budget": lp.get("max_budget"),
                "budget_duration": lp.get("budget_duration"),
                "max_tokens": mi.get("max_tokens"),
            }
    except Exception as exc:
        logger.debug("could not fetch model info: %s", exc)
    return info_map


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


def _run_code_probe(
    model: str,
    client: httpx.Client,
    probe: dict[str, str],
    timeout: float,
) -> bool:
    """Ask the model to write code, execute it, return True iff output matches."""
    try:
        resp = client.post(
            f"{_base_url()}/v1/chat/completions",
            headers=_headers(),
            json={
                "model": model,
                "messages": [{"role": "user", "content": probe["prompt"]}],
                "max_tokens": 256,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        code = resp.json()["choices"][0]["message"]["content"].strip()
        if code.startswith("```"):
            code = "\n".join(line for line in code.splitlines() if not line.startswith("```"))
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(code + "\n" + probe["test"] + "\n")
            tmp = f.name
        proc = subprocess.run(  # nosec B603
            [sys.executable, tmp],
            capture_output=True,
            text=True,
            timeout=5,
        )
        Path(tmp).unlink(missing_ok=True)
        return proc.stdout.strip() == probe["expected"]
    except Exception:
        return False


def _probe_model(
    model: str,
    client: httpx.Client,
    probe: dict[str, str],
    latency_cap_s: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "model": model,
        "latency_ms": None,
        "quality_pass": False,
        "score": 0.0,
        "error": None,
    }
    # Latency probe
    t0 = time.monotonic()
    try:
        resp = client.post(
            f"{_base_url()}/v1/chat/completions",
            headers=_headers(),
            json={
                "model": model,
                "messages": [{"role": "user", "content": "pong"}],
                "max_tokens": 4,
            },
            timeout=latency_cap_s,
        )
        resp.raise_for_status()
        result["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
    except Exception as exc:
        result["error"] = f"latency: {exc}"
        return result
    # Quality probe
    result["quality_pass"] = _run_code_probe(model, client, probe, latency_cap_s)
    # Score: quality wins, latency breaks ties
    if result["quality_pass"]:
        result["score"] = round(1000 / result["latency_ms"], 4)
    else:
        result["score"] = round(0.1 / result["latency_ms"], 6)
    return result


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


def _sweep(
    models: list[str],
    client: httpx.Client,
    probe: dict[str, str],
    latency_cap_s: float,
    model_info: dict[str, dict[str, Any]],
    label: str,
    *,
    verbose: bool,
) -> list[dict[str, Any]]:
    if verbose:
        print(f"\n{label}…")
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT) as pool:
        futs = {pool.submit(_probe_model, m, client, probe, latency_cap_s): m for m in models}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            r["info"] = model_info.get(r["model"], {})
            results.append(r)
            if verbose:
                _print_result(i, len(models), r)
    return results


def _winners(results: list[dict[str, Any]], cap_ms: float) -> list[dict[str, Any]]:
    passed = [
        r for r in results if r["latency_ms"] and r["latency_ms"] <= cap_ms and r["quality_pass"]
    ]
    return sorted(passed, key=lambda r: r["score"], reverse=True)


def run_benchmark(
    models: list[str] | None = None,
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    """Probe models with tier-appropriate tests. Returns results dict."""
    with httpx.Client(timeout=_CAPABLE_LATENCY_CAP_S + 5) as client:
        if models is None:
            if verbose:
                print("Discovering models…")
            models = discover_models(client)
            if verbose:
                print(f"  {len(models)} text-generation models found")
        if verbose:
            print("Fetching quota + cost data from /model/info…")
        model_info = fetch_model_info(client)
        fast_results = _sweep(
            models,
            client,
            _FAST_PROBE,
            _FAST_LATENCY_CAP_S,
            model_info,
            f"FAST sweep (latency ≤ {_FAST_LATENCY_CAP_S}s + add() probe)",
            verbose=verbose,
        )
        capable_results = _sweep(
            models,
            client,
            _CAPABLE_PROBE,
            _CAPABLE_LATENCY_CAP_S,
            model_info,
            f"CAPABLE sweep (latency ≤ {_CAPABLE_LATENCY_CAP_S}s + fibonacci probe)",
            verbose=verbose,
        )

    return {
        "fast": _winners(fast_results, _FAST_LATENCY_CAP_S * 1000),
        "capable": _winners(capable_results, _CAPABLE_LATENCY_CAP_S * 1000),
        "fast_all": sorted(fast_results, key=lambda r: r["score"], reverse=True),
        "capable_all": sorted(capable_results, key=lambda r: r["score"], reverse=True),
    }


def _quota_str(info: dict[str, Any]) -> str:
    parts = []
    if info.get("rpm"):
        parts.append(f"{info['rpm']}rpm")
    if info.get("max_budget") and info.get("budget_duration"):
        parts.append(f"${info['max_budget']}/{info['budget_duration']}")
    return "  " + "  ".join(parts) if parts else ""


def _print_result(i: int, total: int, r: dict[str, Any]) -> None:
    info = r.get("info", {})
    quota = _quota_str(info)
    if r["latency_ms"]:
        q = "pass" if r["quality_pass"] else "fail"
        print(f"  [{i:3}/{total}] {r['model']:52s} ✓ {r['latency_ms']:6.0f}ms q={q}{quota}")
    else:
        print(f"  [{i:3}/{total}] {r['model']:52s} ✗ {r['error']}")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def save_cache(results: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": time.time(),
        "fast_model": results["fast"][0]["model"] if results["fast"] else None,
        "capable_model": results["capable"][0]["model"] if results["capable"] else None,
        "fast_top5": [r["model"] for r in results["fast"][:5]],
        "capable_top5": [r["model"] for r in results["capable"][:5]],
        "fast_all": results.get("fast_all", []),
        "capable_all": results.get("capable_all", []),
    }
    CACHE_PATH.write_text(json.dumps(payload, indent=2))
    logger.info("model cache written to %s", CACHE_PATH)


def load_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text())
        if not isinstance(data, dict):
            return None
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_SECONDS:
            return None
        return data
    except Exception:
        return None


def best_model(tier: str = "capable") -> str:
    """Return the best cached model for a tier; runs benchmark if stale."""
    cache = load_cache()
    if cache and cache.get(f"{tier}_model"):
        return str(cache[f"{tier}_model"])

    if not _base_url() or not _api_key():
        return (
            os.environ.get("MAISTRO_BUILDERS_MODEL")
            or os.environ.get("DEFAULT_MODEL")
            or "google-gemini-2.5-flash"
        )

    logger.info("model cache stale — running benchmark (background)")
    try:
        results = run_benchmark(verbose=False)
        save_cache(results)
        winners = results[tier]
        return (
            winners[0]["model"]
            if winners
            else (os.environ.get("DEFAULT_MODEL") or "google-gemini-2.5-flash")
        )
    except Exception as exc:
        logger.warning("benchmark failed (%s) — using env default", exc)
        return os.environ.get("DEFAULT_MODEL") or "google-gemini-2.5-flash"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description="Benchmark LiteLLM models for builders routing")
    parser.add_argument("--models", nargs="*", help="Specific model IDs (default: all)")
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args()

    results = run_benchmark(models=args.models, verbose=True)
    save_cache(results)

    sep = "=" * 68
    print(f"\n{sep}")
    print(f"FAST tier  (latency ≤ {_FAST_LATENCY_CAP_S}s, add() probe):")
    for i, r in enumerate(results["fast"][: args.top], 1):
        qs = _quota_str(r.get("info", {}))
        print(f"  {i:2}. {r['model']:52s} score={r['score']:.3f} lat={r['latency_ms']:.0f}ms{qs}")
    if not results["fast"]:
        print("  (none within latency cap)")

    print(f"\nCAPABLE tier (latency ≤ {_CAPABLE_LATENCY_CAP_S}s, fibonacci probe):")
    for i, r in enumerate(results["capable"][: args.top], 1):
        qs = _quota_str(r.get("info", {}))
        print(f"  {i:2}. {r['model']:52s} score={r['score']:.3f} lat={r['latency_ms']:.0f}ms{qs}")

    print(f"\nCache: {CACHE_PATH}")
    if results["fast"]:
        print(f"Best fast model:    {results['fast'][0]['model']}")
    if results["capable"]:
        print(f"Best capable model: {results['capable'][0]['model']}")
