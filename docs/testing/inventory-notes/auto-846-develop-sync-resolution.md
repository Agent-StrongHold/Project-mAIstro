# auto-846 develop-sync merge resolution

inventory-delta:
  added: 0
  removed: 0
  modified: 1
  note: >
    No test inventory change; this round resolved the preserved origin/develop
    sync conflict and revalidated the #846 surface on the merged tree.

## What this round did

Incoming block: "develop sync conflict preserved in worktree; resolve before
verification." The worktree was mid-merge with `MERGE_HEAD=ca4caec7d`
(origin/develop) and exactly one unmerged path:

- `packages/maistro-core/tests/capabilities/test_harness_runner.py`

### Conflict and resolution

develop added two tests (#1158 provenance labeling, multi-turn override
reconstruction) directly above the test that #846 had renamed. Resolution kept
both sides:

- kept develop's `test_trusted_system_turn_is_labeled_context_never_scanned_content`
  and `test_harness_refuses_override_reconstructed_across_untrusted_turns`
  (the merged `_StubWarden` already records `contexts`, so they run as-is);
- kept #846's renamed `test_safe_wrapper_passthrough_and_default_deny`
  (fail-closed `DenyAllGate` default; `AllowAllGate` no longer exists under
  `packages/*/src` — grep only matches historical corpus JSON in
  maistro-evolve benchmark data, not code).

Merge committed as `0df6373c3`.

## Post-merge validation (all on 0df6373c3)

- `uv run pytest packages/maistro-core/tests/capabilities/test_harness_runner.py -q` → 23 passed
- `uv run ruff check .` / `uv run ruff format --check .` → clean
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0, no unbanked identities (no ledger amendment needed; the round changed test code only)
- `uv run pytest packages/maistro-core/tests -q` → 10425 passed, 700 skipped, 1 xfailed
- `uv run pytest packages/hive-conductor/backend/tests -q` → 2816 passed, 6 skipped
- `scripts/check-cross-package-imports.py`, `check-compliance.py`,
  `check-backlog-consistency.py`, `check_enumerations.py`,
  `check_direct_effects.py` (45 sites, all dispositioned) → exit 0

## #846 surface re-check on the merged tree

- `routes/harness.py:_configured_harness_policy` — explicit `BudgetRule(count=0)`
  deny-action policy; route never constructs a manager with `policy=None`.
- `harness_manager.py:_admission_unavailable` — missing Invocation wiring or
  policy → typed `Unavailable` (503), never a direct provider fallback.
- `_Session` stores `provider_name` only; provider re-resolved per operation.
- `RuleBasedRepair` holds a read-only monitor + `effect_invoker` callable;
  `capabilities_wiring.py` re-resolves binding + provider inside the Invocation
  resolver at effect time.
- `governed_invocation.py:226-227` policy outage → deny with rule
  `invocation.fail-closed`; line 312 emits the
  `capability.invocation.policy_decision` audit event.
