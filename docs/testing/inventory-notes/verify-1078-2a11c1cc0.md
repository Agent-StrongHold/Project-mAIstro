# verify-1078-2a11c1cc0

> This note carries **no `inventory-delta:` block**: it adds and removes no
> tests, and the gate (ADR-082526-547c) reads an absent key as zero movement.
> It moves no test counts.

Verification record for lane L1078 (#1078 — [adversarial][#1041] Reconcile
credential-routing consumer proof and #58 closure evidence) at exact head
`2a11c1cc006a977ee76281307767319773d4fb62` (branch `auto-1078`, develop base
identical). The job's driver produced **no** `check-*.log` files and
`manifest.checks` was empty; every claim below was executed first-party at the
exact head. The tree needed no change; this note is the durable record.

## Issue context (from dispatch evidence, frozen)

Issue #1078's bounded checklist asks for reconciliation, not new runtime work:
the original allegation (PR #1041 at `f49aefe6` shipped the credential pool
with zero production consumers) is conceded stale — the in-issue refutation
(comment `5573799861`, 2026-09-07: "REFUTED (ADR-decided): ADR-063 pool
governs; configured endpoints seed it; env var is documented fallback, not
bypass") points at the #1079 wire-up, which landed on develop as `f695d491f`
("Wire governed model egress into production composition (#1079) (#1522)",
visible in `model_chat.py` history; linked PR #1091 itself closed unmerged).
`git log f49aefe6..HEAD -- capabilities/credential_routing.py` is empty — the
seam module is unchanged since #1041; the consumers arrived around it.

## Item 1 — Runtime (not import) reproduction of the shipped path: PROVEN

Instrumented `CredentialRouter.acquire`/`record_outcome` with spies and drove
the real composition (`create_container` → `build_node_resolver` →
`LlmSummarizeNode.run` → `ModelChatEgress.invoke` → routed resolver/executor)
via a scratch script (kept out of the tree, `/tmp`):

- `acquire` WAS entered — `('ws-prod', 'project-prod', 'litellm',
  ('litellm-gateway',))`: Binding Workspace/Project scope plus the
  Binding-authorized `credential_refs`. The issue's original repro sketch
  ("`acquire` is never entered") no longer holds.
- The physical model call authenticated with the **pool-issued** credential
  (`endpoint.api_key == 'test-litellm-key'`, the `litellm_key`-seeded pool
  record) while `MAISTRO_LLM_API_KEY=test-secret` was set in the environment —
  the env var did not bypass the pool (fallback only; see item 4).
- Success outcome was folded back: `record_outcome(..., error=None)` recorded
  for the same scope/key id.
- Supporting suite: `uv run pytest
  packages/maistro-core/tests/test_model_egress_container_composition.py -q`
  → 20 passed (configured bootstrap, empty-config authorizes nothing,
  disabled-binding refusal, governed invocation through real authorities).

Residual against #58/ADR-063: none concrete found at this head. Pool selection
remains default-strategy (`round_robin`) with one bootstrap-registered key —
multi-key pools need operator configuration surface that #1079 deliberately
scoped out (`model_binding_bootstrap.py` docstring, Finding 4 refusal of custom
refs); that is a feature boundary, not a consumer defect.

## Item 2 — Binding-scoped selection, outcome-driven rotation/refusal, secret containment: PROVEN

- `uv run pytest packages/maistro-core/tests/capabilities/test_credential_routing.py
  packages/maistro-core/tests/test_model_egress_container_composition.py -q`
  → 20 passed. Covers: scoped selection on the governed Invocation
  (`TestRoutedInvocation`), rotation reacting to real outcomes, exhaustion →
  `CapabilityUnavailable` with soonest recovery, fail-closed Bindings without
  refs, refs-not-named denial, foreign-workspace denial,
  non-declaring-provider refusal (`Unavailable`), bare-provider executor
  passthrough, and `TestSecretContainment` (secrets never enter
  Invocation/event records; `CredentialBackedProvider.__repr__` shows key id
  only; `ResolvedBinding.from_provider` carries no secret).
- `uv run pytest packages/maistro-core/tests/credentials -q` → 136 passed
  (scoped acquisition incl. cross-workspace/cross-project denials; outcome
  rotation: 429 cools ≤60s honoring Retry-After, 402 cools an hour, 401/403
  block permanently, transients rotate nothing; exhaustion clock accounting).
- `uv run pytest packages/maistro-core/tests/capabilities -q` → 716 passed,
  7 skipped (whole capabilities suite, collateral safety).
- Production enforcement points: `model_chat.py:507-512` (executor
  `TypeError`s without a `CredentialBackedProvider`),
  `model_chat.py:526-528` (both seams wrapped),
  `credential_routing.py` resolver (`CredentialScopeError` durable,
  `PoolExhaustedError` → typed `Unavailable`).

## Item 3 — Reachability disposition + ADR-063 claims reconciled: VERIFIED

- `docs/adr/ADR-063-credential-pool-and-rotation.md:274` marks the alleged
  false claim ("#58 wired the pool into the canonical Invocation path …")
  **"Superseded by the 2026-09-02 note above"**, and the 2026-09-02 note
  (lines 279+) describes the actual mechanism: selection at Provider
  resolution, rotation at real Invocation outcomes, anchors moved to
  `maistro.credentials.router`, `execute_with_pool` retry loop removed.
- `uv run python scripts/check-reachability.py` (CI argv,
  `.github/workflows/quality.yml:1056`) → exit 0: 1364 production modules,
  169 unreachable. No credentials module appears in
  `quality/reachability-baseline.json`'s unreachable list — the pool/router
  left the unreachable baseline and now have real consumers
  (`model_chat.py:526`, `image_generation.py:234`, `pm_polling.py:40,75`,
  `extensions/tool_skill/execution.py:254`), so the disposition prune is
  substantively justified, not just import-metric-consistent.
- `uv run python scripts/check-reachability-dispositions.py` (CI argv,
  `quality.yml:1351`) → exit 0: 49 groups, 147 CONNECT / 20 LIBRARY / 2 RETIRE.
- `uv run python scripts/check-ac-state.py` → exit 0; `quality/ac-state.json`
  shows ADR-063: 32/32 own criteria at `covered`, modules mapped
  `maistro.credentials.pool` (17) + `maistro.credentials.router` (15),
  consistent with the measurement notes.

## Item 4 — Allegation disposition recorded: CONFIRMED REFUTED, INDEPENDENTLY

The in-issue recording ("REFUTED (ADR-decided) … Falsification pass
2026-09-07") is factually accurate at this head, per the first-party runs
above. The decisive falsification datum: with `MAISTRO_LLM_API_KEY` set to a
different secret, the shipped node path still authenticated with the
pool-issued key — env vars are fallback construction inputs
(`llm_summarize.py:203`), not a routing bypass; configured bindings + seeded
pool credentials govern (`model_binding_bootstrap.py` registers
`litellm_key` under `litellm-gateway` and backfills empty `credential_refs`).
Required CI: `check-reachability.py`, `check-reachability-dispositions.py`,
`check-ac-state.py` all exit 0 with CI argv at this head.

## Item 5 — Two gate ideas remain proposals: COMPLIANT

No consumer-proof prune requirement exists in
`scripts/check-reachability-dispositions.py` and no grant-expiry /
first-consumer-issue policy exists in `scripts/check-ratchet-provenance.py` —
neither proposal was smuggled into a gate, so no separate policy disposition
was required and none was recorded. The #1053 grant for
`effect_context.py::credential_routing` remains in
`quality/ratchet-authorizations.json` while `quality/vulture-baseline.json`
carries **0** `credential_routing` rows: the banked identity was retired by
real consumption, which is the honest end-state that proposal feared never
arriving.

## Gate runs that could not apply

- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 1 with "the base revision resolves to
  HEAD itself (2a11c1cc006a) … comparison could not fail": in this lane
  develop base == head, so the ratchet has no base to diff. Environmental
  N/A, not a defect; the scan itself reported `unclassified: 0`.
- `uv run ruff check .` and `uv run ruff format --check .` → both exit 0
  (3181 files formatted), hygiene intact.

## Residual observations (recorded, not repaired — cosmetic)

1. `ADR-063-credential-pool-and-rotation.md:274` says "Superseded by the
   2026-09-02 note **above**" but the 2026-09-02 note appears below it in the
   file (line 279). Semantics are unambiguous; a pointer-direction nit only.
2. The refutation comment's "documented fallback" phrasing is loose: the env
   fallback's behavioral precedence (pool wins) is proven and the bootstrap
   docstring documents the seeding, but no doc sentence says "env var is the
   fallback" verbatim. Behavioral acceptance is unaffected.

## Verdict

All five checklist items of #1078 verified against reachable production
behavior at exact head `2a11c1cc0`. The original allegation is refuted at
this head: the shipped Container → model Invocation path enters
`CredentialRouter.acquire` at runtime, selects within Binding-authorized
refs, rotates on real outcomes, refuses fail-closed, and contains secrets.
No tree change was required; the writer artifact is this note.
