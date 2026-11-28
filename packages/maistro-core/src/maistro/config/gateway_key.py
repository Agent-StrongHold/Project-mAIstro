"""The one effective model-gateway credential precedence (#1824, #2247).

Both shipped compositions — the engine (`maistro-server`) and Hive
(`hive-conductor`) — must answer "which credential does this deployment's
model egress authenticate with?" identically. Before #2247 the engine read
`LITELLM_API_KEY` and fell back to the bundled master key while Hive read
`MAISTRO_LLM_API_KEY` first: a deployment that set both aliases to *different*
values got split-brain credential state — the engine presented one key to the
gateway and Hive presented another, so the two halves of one installation
authenticated (and were rate-limited, billed and logged) as two different
callers.

**Owner-decided precedence matrix** (first non-empty leg wins; an empty
string at any leg is *unset* and falls through, so a blanked variable never
shadows a configured one). The aliases, in precedence order, are
`MAISTRO_LLM_API_KEY`, `LITELLM_API_KEY`, `LITELLM_PROXY_KEY`,
`LITELLM_MASTER_KEY`:

1. vault `MAISTRO_LLM_API_KEY` — Hive-only leg (the engine has no vault);
   the deployment's own model key stated in the conductor vault (SPEC-003
   vault-first);
2. `MAISTRO_LLM_API_KEY` from settings/environment — the key this
   deployment intentionally named for its own model authority, so it outranks
   the compatibility aliases below;
3. vault `LITELLM_API_KEY` — Hive-only leg;
4. `LITELLM_API_KEY` from settings/environment — what the shipped compose
   file derives from `LITELLM_MASTER_KEY` for every container;
5. bare-env `LITELLM_PROXY_KEY` — the supported LiteLLM proxy spelling some
   deployments state directly;
6. bare-env `LITELLM_MASTER_KEY` / the bundled master-key setting — the
   bundled proxy's own key, the last fallback before nothing;
7. `None` — absent model configuration. Callers treat this as fail-closed:
   no credential is registered or dispatched, never a placeholder key.

A vault-less composition (the engine) passes ``None`` for the vault legs; a
vault-backed one (Hive) resolves them through its own vault first and hands
the winner here. Either way the *ordering* — the thing two compositions can
drift on — is decided in this one function, not reassembled per call site.
The ordering itself is pinned by
`packages/maistro-core/tests/config/test_gateway_key.py`, by Hive's
`test_effective_gateway_key.py`, and by the engine's
`TestInstalledGatewayCredential` — the three suites a drift would have to
get past.
"""

from __future__ import annotations


def effective_gateway_key(
    *,
    maistro_key: str | None = None,
    litellm_key: str | None = None,
    proxy_alias: str | None = None,
    master_alias: str | None = None,
) -> str | None:
    """Resolve the effective gateway credential from the matrix's four legs.

    Leg order *is* the precedence matrix: ``maistro_key`` (vault or env,
    per the caller's composition) → ``litellm_key`` → ``proxy_alias`` →
    ``master_alias``. An empty string at any leg falls through to the next,
    and a fully unconfigured deployment gets ``None`` — never ``""`` — so a
    caller can distinguish "unset" from a real empty value and fail closed
    rather than dispatch a blank bearer token.
    """
    for leg in (maistro_key, litellm_key, proxy_alias, master_alias):
        if leg:
            return leg
    return None
