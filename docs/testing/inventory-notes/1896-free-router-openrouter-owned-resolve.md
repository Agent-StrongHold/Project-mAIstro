---
inventory-delta:
  packages/maistro-rsi/tests: +1
---

# Free-router resolve accepts only OpenRouter-owned picks

Part of the #1896 CI-repair round: `resolve_concrete_free_model` now degrades
to `None` for any served pick whose id is not OpenRouter-owned
(`openrouter/…`). A third-party `:free` pick 404s as soon as its provider
un-free's the model — `nous/meituan/longcat-2.5-preview:free` died mid-seed
and exhausted a run's whole recovery budget — so resolution must fall back to
`DEFAULT_FREE_MODEL` instead of pinning a routable-but-dead alias.

- `test_resolve_rejects_third_party_free_picks` (+1): pins the regression —
  the exact incident model served by OpenRouter-direct must resolve to `None`.
- `test_resolve_reads_concrete_model` fixture updated (same node count): the
  happy-path served model becomes an OpenRouter-owned id so it survives the
  new guard.

No existing case is removed, renamed or moved. All cases remain offline
(stubbed `_post`); no agent, gateway or provider call is made.
