---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-1084 develop-sync conflict resolution (develop `4de7e906d`)

Completed the develop sync the previous round left mid-flight: merged
`origin/develop` (`4de7e906d`, one commit past the previously merged
`e20e9f52e`) into `auto-1084` (`bc58b6eae`, the SPEC-285 streaming repair
head) and resolved everything in place. No tests were added or removed by the
resolution itself; test counts are unchanged from the recorded inventory.

## Textual conflict (one file)

`packages/hive-conductor/backend/adapters/maistro_core.py` — develop's #1824
fail-closed credential work collided with this branch's #1084 convergence:

- Took the branch's side for the three structural hunks: develop's
  `_HttpOpenAILLMClient` (with its new `_require_credential()` guard and the
  `LLMProviderError`/`shared_client` imports that served it) stays deleted —
  the adapter composes no model transport of its own; the roster receives
  `container.model_chat_client` (kept as a direct attribute read per the
  wiring-reads gate) with `build_model_chat_client` as the container-shaped
  test-seam fallback.
- Took develop's side for the credential hunk: `_construct_runtime` now
  resolves the deployment credential through the one effective-key contract
  (`services.secrets.effective_llm_gateway_key`, the #1824 precedence matrix)
  instead of `maistro_llm_api_key` alone. The contract feeds
  `AgentConfig.litellm_key`, which is the api_key on every governed door
  (roster fallback client, `AdmittedModelCalls`, `ModelChatEgress`), so
  #1824's "no placeholder, no drift" semantics survive the deletion of the
  legacy client. Dropped develop's `model = settings.maistro_model` — its
  only consumer was the deleted client. Adapted the carried comment to name
  the governed doors rather than the deleted "legacy client".

## Semantic conflicts (no textual marker, reconciled in tests)

- `test_effective_gateway_key.py` (develop's) asserted the deleted
  `_HttpOpenAILLMClient`: refusal-before-dispatch on empty key, sanitized
  refusal message, `runtime.llm._key`. Rewritten to pin the same #1824
  guarantees in their #1084 structural form: the adapter defines no
  `_HttpOpenAILLMClient`, imports no `shared_client`, bears no placeholder
  literal or HTTP-header composition, resolves keys only through the
  effective-key contract; the two runtime-level tests keep the effective-key
  and empty-key endpoints assertions against the governed composition
  (`runtime.llm._egress._endpoint.api_key`). The former dispatcher-passage
  coverage (bearer token on the wire) is superseded by the governed provider
  adapter suites in maistro-core.
- `test_dag_model_tools.py` / `test_legacy_dag_node_container_composition.py`
  (develop's, from the M2-A capabilities work) patch
  `model_chat.execute_model_chat` with the pre-SPEC-285 signature; merged
  production passes the `on_chunk` streaming observer. The four substitution
  fakes now accept `on_chunk: Any = None` (unset for these non-streaming
  calls) — same reconciliation the b728bca8a repair applied to the bridge
  fakes.
- `test_maistro_core_adapter.py` (branch's) patched
  `services.secrets.maistro_llm_api_key` to blank the credential; the seam
  the adapter now reads is the contract, so the patches target
  `services.secrets.effective_llm_gateway_key` (also hermetic against a
  developer's `LITELLM_API_KEY` environment).

## Validation

- `uv run pytest packages/hive-conductor/backend/tests -q` → 3947 passed,
  26 skipped, 0 failed.
- `uv run pytest packages/maistro-core/tests/capabilities -q` → 767 passed,
  8 skipped.
- `uv run pytest packages/maistro-core/tests/graph packages/maistro-core/tests/runs -q`
  → 3549 passed, 480 skipped, 4 xfailed.
- `uv run pytest packages/maistro-core/tests/agents/test_conductor.py
  packages/maistro-server/tests/api/test_conductor_agent.py -q` → 80 passed.
- `uv run pytest packages/maistro-server/tests -q` → 645 passed, 8 skipped.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run python scripts/check-wiring-reads.py` → matches baseline (the
  `Container.model_chat_client` direct read survives).
- `uv run python scripts/check-model-egress.py` → OK, 16 physical callers, no
  candidate-approved expansion.
- `uv run python scripts/check_direct_effects.py` → 51 sites, all
  dispositioned.
- `uv run python scripts/check-suite-inventory.py` → ok, 21 suites match.
- `uv run pytest tests/ packages/maistro-design/tests -q` → 6385 passed,
  145 skipped, 5 failed — all five verified identical on the pre-merge head
  `bc58b6eae` (temp detached worktree, removed after):
  `tests/test_check_promotion_surface.py` ×3 and
  `tests/test_bench_speculative_parallel.py` ×2. Both are pre-existing branch
  conditions, not merge-introduced; the promotion-surface gap (383 modules
  reachable from the promotion path, vs develop's clean audit) can only be
  closed by `maistro_rsi/sensitive_paths.py` patterns or
  `quality/promotion-surface-baseline.json` entries — an owner-reviewed
  ledger/policy action outside this lane's authority.
- In-lane repairs surfaced by the full root suite:
  - `docs/specs/SPEC-285-model-egress-incremental-streaming.md` (this lane's
    own spec) carried `status: Implemented` without the required
    `## Acceptance Criteria` section (`tests/tools/test_lint_lifecycle.py`);
    added the section, naming the four structural streaming proofs plus usage
    and one-authority criteria.
  - `tests/test_check_model_egress.py::test_discover_sites_surfaces_reachability_classes_from_the_shipped_tree`
    still pinned base-era census quals: `execute_model_chat` (renamed by
    SPEC-285 to `_post_model_chat`/`_dispatch_adapter_model_chat`) and
    `services.chat_completion` as a reachable escape (its physical calls are
    gone by design since #1084 — census entry and all). Re-pinned to the
    shipped truth; the census itself and its ledger were already consistent.
- `uv run mypy --strict packages/maistro-core/src` → Success (826 files), the
  CI-gated scope. (`mypy packages/maistro-server/src` non-strict reports the
  known pre-existing `maistro_canvas.canvas.store` import-stub error outside
  the gated scope; pyright is a CI-only regression ratchet, not runnable
  here.)
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1326 reviewed
  identities, ledger consistent after the merge).
- `uv run python scripts/check-radon-baseline.py` → exit 0;
  `check-execution-lifecycles.py`, `check-ratchet-provenance.py`,
  `check-reachability.py` (green after the merge — the previously red
  `admission_identity` condition is resolved on this develop tip),
  `check-image-pins.py`, `check-route-permissions.py`,
  `check-shipped-surface-truth.py`, `check-workflow-inventory.py`,
  `check-frontend-typed-client.py`, `check-durable-table-inventory.py`,
  `check-branch-independence.py`, `check-ac-state.py`,
  `check-reachability-dispositions.py` → all exit 0.
- `quality/*.json` merge audited per the row-loss hazard: staged ledgers are
  identical to `origin/develop` except this lane's own
  `direct-effect-call-sites.json`/`model-egress.json` (branch census, gate-
  verified against the merged tree).
- Not run here: `check-license-inventory.py` (requires syft SBOM artifacts
  built in the release/security workflows; its policy file came from develop
  unchanged and no dependency surface changed in the resolution).
