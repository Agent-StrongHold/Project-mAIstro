"""Turn the OpenRouter *free router* into stable, gateway-routable genome models.

The free router (``openrouter/free``) picks a RANDOM ``:free`` model per call —
ideal as a $0 random-model SELECTOR, useless as a genome model directly: it
re-randomises every call, so a genome could never be scored against a *stable*
model. This module converts one router pick into a pinned, routable alias:

  1. RESOLVE — ask OpenRouter *directly* which concrete ``:free`` model the router
     serves. The litellm gateway can't tell us: it echoes the requested alias
     (``model == "openrouter/free"``) and caches, so the pick is invisible in-band.
  2. REGISTER — add that concrete model to the litellm gateway via the admin API
     as a first-class alias ``openrouter/<model>`` bound to the OpenRouter
     credential. Required, not cosmetic: the bare ``openrouter/*`` wildcard carries
     no credential and 401s on tag config, whereas an explicit registration (the
     same shape as the hand-added ``:free`` aliases) routes cleanly.
  3. PIN — hand back the routable alias for the caller to pin onto a genome node.

Every step degrades to ``None`` (and the caller to a known-good default), so a
seeding run never breaks on a gateway or network hiccup — it just falls back to
its configured roster. All calls are synchronous (seeding is synchronous); the
credential/keys are read from the environment at call time, never baked in.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence

import httpx
import structlog

from maistro_rsi.gateway import _gateway_base, _gateway_key

logger = structlog.get_logger()

# Roster tokens that mean "use the free router as a random-model selector" rather
# than a model to score directly. Matched against --models entries.
FREE_ROUTER_ALIASES = frozenset({"openrouter/free", "openrouter/openrouter/free", "or-free-router"})

# A concrete, verified-routable free model used when resolution/registration is
# unavailable (no OpenRouter key, gateway down) — keeps a free-only roster from
# collapsing to the un-pinnable sentinel.
DEFAULT_FREE_MODEL = "openrouter/openai/gpt-oss-120b:free"

_OPENROUTER_DIRECT = "https://openrouter.ai/api/v1/chat/completions"
# What we send to OpenRouter-direct to make it pick a random free model. The
# gateway registers this under the `or-free-router` / `openrouter/openrouter/free`
# aliases; direct, it is just `openrouter/free`.
_FREE_ROUTER_PRESET = "openrouter/free"

FreeSelector = Callable[[], "str | None"]


def resolve_concrete_free_model(
    *, preset: str = _FREE_ROUTER_PRESET, timeout: float = 60.0
) -> str | None:
    """Ask OpenRouter *directly* for one random ``:free`` model id (its ``data.model``).

    Returns ``None`` if ``OPENROUTER_API_KEY`` is unset, the call fails, or the
    response names no concrete model (or just echoes the preset back).
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        resp = httpx.post(
            _OPENROUTER_DIRECT,
            json={
                "model": preset,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        served = resp.json().get("model")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("free_router_resolve_failed", error=str(exc))
        return None
    if not isinstance(served, str) or not served or served == preset:
        return None
    return served


def _discover_openrouter_credential(base: str, key: str, timeout: float) -> str | None:
    """The litellm credential name new aliases must bind to (else they 401 on the
    tag-gated wildcard). Overridable via ``LITELLM_OPENROUTER_CREDENTIAL``;
    otherwise the first credential named ``openrouter/*``."""
    override = os.environ.get("LITELLM_OPENROUTER_CREDENTIAL")
    if override:
        return override
    try:
        resp = httpx.get(
            f"{base}/credentials", headers={"Authorization": f"Bearer {key}"}, timeout=timeout
        )
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    creds = payload.get("credentials") or payload.get("data") or []
    for c in creds:
        name = c.get("credential_name", "") if isinstance(c, dict) else ""
        if name.startswith("openrouter/"):
            return name
    return None


def register_gateway_alias(
    concrete: str,
    *,
    base: str | None = None,
    key: str | None = None,
    credential: str | None = None,
    timeout: float = 30.0,
    known: set[str] | None = None,
) -> str | None:
    """Register ``openrouter/<concrete>`` on the gateway bound to the OpenRouter
    credential and return the routable alias. A no-op (returns the alias) when it
    is already present in ``known``. Returns ``None`` only if the gateway/credential
    is unreachable or registration is rejected for a reason other than "exists"."""
    # ALWAYS prepend the LiteLLM `openrouter/` provider prefix. The concrete id
    # comes from OpenRouter-direct as a bare ``<provider>/<model>`` — including
    # OpenRouter-OWNED models like ``openrouter/sonoma-dusk-alpha:free``, whose
    # own leading ``openrouter/`` is part of the model id, NOT the LiteLLM prefix.
    # Skipping the prefix there would make LiteLLM strip that segment and route
    # ``sonoma-dusk-alpha:free`` (a different, non-existent model).
    alias = f"openrouter/{concrete}"
    base = (base or _gateway_base()).rstrip("/")
    key = key or _gateway_key()
    if not base or not key:
        return None
    if known is not None and alias in known:
        return alias
    credential = credential or _discover_openrouter_credential(base, key, timeout)
    if not credential:
        return None
    body = {
        "model_name": alias,
        "litellm_params": {"model": alias, "litellm_credential_name": credential},
    }
    try:
        resp = httpx.post(
            f"{base}/model/new",
            json=body,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        logger.warning("free_alias_register_failed", alias=alias, error=str(exc))
        return None
    if resp.status_code >= 400:
        # A duplicate name is fine — the model is already routable. Anything else
        # is a real failure the caller should fall back from.
        already = resp.status_code == 409 or "exist" in resp.text.lower()
        logger.warning("free_alias_register_status", alias=alias, status=resp.status_code)
        return alias if already else None
    if known is not None:
        known.add(alias)
    logger.info("free_alias_registered", alias=alias)
    return alias


def select_and_pin_free_model(
    *, known: set[str] | None = None, timeout: float = 60.0
) -> str | None:
    """One end-to-end pick: resolve a random concrete free model and make it
    routable. ``None`` if any leg is unavailable (caller falls back)."""
    concrete = resolve_concrete_free_model(timeout=timeout)
    if not concrete:
        return None
    return register_gateway_alias(concrete, known=known, timeout=timeout)


def make_free_selector(*, timeout: float = 60.0) -> FreeSelector:
    """Build the per-genome selector used at seeding: each call yields a freshly
    resolved-and-pinned concrete free alias (or ``None`` to trigger the default).

    ``known`` starts EMPTY and accumulates only the aliases *we* register this
    session — deliberately NOT seeded from ``fetch_known_models()``: the gateway's
    ``/v1/models`` includes the whole wildcard-expanded OpenRouter catalog, so a
    concrete model almost always "already exists" there yet routes via the
    credential-less ``openrouter/*`` wildcard and 401s on tag config. Only an
    explicit credential-bound registration routes; so we must register every fresh
    pick, and only skip a model we ourselves already registered this run."""
    registered: set[str] = set()

    def selector() -> str | None:
        return select_and_pin_free_model(known=registered, timeout=timeout)

    return selector


def _pick_distinct(selector: FreeSelector | None, count: int) -> list[str]:
    """Up to ``count`` DISTINCT concrete free aliases from ``selector`` (the free
    catalog is finite and the router/cache can repeat a pick, so de-dup and cap
    the attempts). Falls back to a single ``DEFAULT_FREE_MODEL`` if nothing
    resolves — keeps a free-only roster routable."""
    picks: list[str] = []
    seen: set[str] = set()
    attempts = 0
    while len(picks) < count and attempts < count * 4:
        attempts += 1
        p = selector() if selector else None
        if p is None:
            break
        if p not in seen:
            seen.add(p)
            picks.append(p)
    return picks or [DEFAULT_FREE_MODEL]


def expand_free_router(
    models: Sequence[str] | None,
    selector: FreeSelector | None,
    *,
    free_count: int = 1,
    resolved: set[str] | None = None,
) -> list[str] | None:
    """Return ``models`` with every free-router sentinel replaced by ``free_count``
    concrete, pinned free aliases — so the roster gains a spread of distinct,
    stable, $0 models to seed and evolve on. A no-op when no sentinel is present.
    Falls back to ``DEFAULT_FREE_MODEL`` when the selector yields nothing. The
    result is de-duplicated (a model already literal in the roster, or surfaced
    twice by the router, appears once)."""
    if not models:
        return list(models) if models is not None else None
    if not any(m in FREE_ROUTER_ALIASES for m in models):
        return list(models)
    out: list[str] = []
    for m in models:
        if m in FREE_ROUTER_ALIASES:
            picks = _pick_distinct(selector, max(1, free_count))
            out.extend(picks)
            if resolved is not None:
                resolved.update(picks)
        else:
            out.append(m)
    seen: set[str] = set()
    deduped: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            deduped.append(x)
    return deduped


def main(argv: list[str] | None = None) -> int:
    """Host-side roster expansion for the launcher: resolve+register the free-router
    sentinel into concrete $0 aliases and print the expanded roster (the container
    can't do this — its env has the gateway key but not OPENROUTER_API_KEY).

        python -m maistro_rsi.free_router --roster "or-free-router,cerebras-glm-4.7" --free-count 2
        -> openrouter/<a>:free,openrouter/<b>:free,cerebras-glm-4.7
    """
    import argparse
    import sys

    # Keep stdout clean: the caller captures the expanded roster from stdout, so
    # send all structlog output (registration logs) to stderr.
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))

    parser = argparse.ArgumentParser(prog="maistro_rsi.free_router")
    parser.add_argument("--roster", required=True, help="Comma-separated genome-models roster.")
    parser.add_argument(
        "--free-count", type=int, default=2, help="Concrete free models per sentinel (default 2)."
    )
    args = parser.parse_args(argv)
    models = [m.strip() for m in args.roster.split(",") if m.strip()]
    selector = make_free_selector() if any(m in FREE_ROUTER_ALIASES for m in models) else None
    out = expand_free_router(models, selector, free_count=args.free_count) or []
    print(",".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
