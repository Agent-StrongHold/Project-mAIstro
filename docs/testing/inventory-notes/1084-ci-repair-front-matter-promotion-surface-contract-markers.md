---
inventory-delta:
  packages/maistro-core/tests: 0
  packages/maistro-server/tests: 0
  packages/hive-conductor/backend/tests: 0
  tests: 0
---

# #1084 CI-repair round: registry front matter, promotion-surface closure, contract markers, bench ledger honesty

Repairs the merge-queue gate failures at head `43782bc7` (develop base
`4de7e906d`). No tests were added or removed — every suite's collected node
count is unchanged, verified with `scripts/check-suite-inventory.py` against
the recorded baseline for `packages/maistro-core/tests`,
`packages/hive-conductor/backend/tests`, and `packages/maistro-server/tests`.

## 1. Validate ADR/spec front-matter (Registry CI)

`docs/specs/SPEC-285-model-egress-incremental-streaming.md` shipped with two
front-matter defects:

- missing the required `layer:` field (the sole `lint --strict` error across
  442 files). Added `layer: Ability`, matching the document this spec
  `implements`-family anchors on (`SPEC-081226-6b46` and sibling `SPEC-284` /
  `ADR-105`, all `Ability`).
- `implements: [maistro-engine#SPEC-081226-6b46]` cited an `AC Defined`
  document as governing authority, which is a NEW citation exception the
  citation-status ratchet cannot authorize in-branch (grants are read from the
  merge base). Moved the SPEC twin to `related:` and emptied `implements: []`
  (the convention every other active document follows for AC-Defined specs;
  the Accepted ADR twin stays in `substrate:`).

## 2. Promotion-surface closure regression

The #1084 convergence merge authored
`capabilities/effect_context.py` → `quota/default_tracker.py`, putting a new
module on the promotion path. `default_tracker.py`'s `TYPE_CHECKING` import of
`maistro.protocols.quota` is still an import edge to the AST-walking gate, and
`maistro/protocols/__init__.py` eagerly imports the memory/learning/runs
graph — one edge grew the closure from develop's 278 modules to 697, with 383
unprotected findings. A candidate baseline row cannot approve itself
(provenance reads grants from the merge base), so the fix removes the
reachability instead: the ambient registry (`get/set_default_quota_tracker`)
moved into `quota/recorder.py` — already on the reviewed surface for the same
recording concern, already imported by `effect_context` — typed
`Any | None` exactly like the recorder's own `quota_tracker` parameter.
`quota/default_tracker.py` is deleted; its three test import sites follow the
move. Closure is back to develop's exact 278 / 74 tolerated
(`check-promotion-surface.py` and its provenance wrapper both pass with no
candidate-approved expansion).

## 3. Contract markers for SPEC-285

SPEC-285 declares `boundary` + `behavioral` contracts; the declared kinds were
unproven because none of its listed tests carried the ADR-032 marker. Marked
the tests that genuinely pin each contract:

- `test_llm_http_adapter.py::test_chat_completions_stream_yields_parsed_chunks`
  → `boundary` (the one transport seam: endpoint, Authorization, parsed
  chunk shape),
- `test_llm_http_adapter.py::test_stream_records_usage_on_the_governed_ledger`
  → `behavioral` (governed accounting across a live stream),
- `test_model_chat_egress.py::test_stream_reaches_the_consumer_while_the_invocation_is_running`
  → `behavioral` (structural incrementality handshake),
- `test_model_chat_egress.py::test_stream_abandonment_never_leaves_a_completed_invocation`
  → `boundary` (the seam cannot fabricate lifecycle state).

358 → 358 reviewed gaps; no ledger rows.

## 4. Bench ledger honesty (`tests/test_bench_speculative_parallel.py`)

The bench encoded pre-convergence semantics: a 503 was expected to
terminalize the Invocation UNKNOWN. The converged gateway deliberately raises
`LlmHttpError` (an `EffectNotApplied`) for received HTTP error statuses, and
the canonical Invocation state machine terminalizes proven-no-effect as
FAILED (retryable) — only cancellation/unproven outcomes are UNKNOWN. The
bench now counts FAILED explicitly (`count_invocations`, `StrategySummary.
invocations_failed`) and the two stale tests assert the converged contract;
`test_counts_a_third_status_as_other` pins the new counts shape.

## 5. Fake-signature drift

`test_model_egress_container_composition.py`'s local `execute_model_chat`
fake lacked the production `on_chunk` observer parameter (SPEC-285 seam), so
the container-composition test failed with an unexpected-keyword TypeError.
The fake now mirrors the real signature.
