---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

Closes the CI-repair coverage gap left by the #718 Evolve governed-egress
cutover (commit c0555611b): the new governed seam introduced four branches
that no test executed, and they are exactly the changed lines the per-file
diff-coverage gate scores on `services/evolution.py` — measured locally at
90.57% changed-line coverage, one uncovered line away from the 90% floor.

Tests added (packages/hive-conductor/backend/tests, `test_evolution_service.py`):

- `test_default_chat_model_reads_the_deployment_default`: the real
  `_default_chat_model` body (the governed tests monkeypatch it) — reads the
  deployment chat alias, and degrades to `""` (router selects) when settings
  raise, instead of crashing llm-call construction.
- `test_governed_llm_seam_yields_nothing_when_the_engine_cannot_start`:
  `get_engine()` raising RuntimeError yields no seam, so `_build_llm_call`
  keeps the documented raw fallback.
- `test_governed_llm_call_raises_a_named_diagnostic_on_malformed_gateway_bodies`:
  a governed gateway body with no choices, or with non-string content, raises
  the named `RuntimeError` diagnostics rather than returning structured junk
  the canonical cycle would read as a successful completion.
