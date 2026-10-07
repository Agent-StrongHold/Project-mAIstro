Repair notes for the #718 canonical-quota cutover's develop integration (auto-718). No collected node counts moved: every change modifies existing tests in place or touches production/quality ledgers, so this note carries no `inventory-delta` block.

## What the integration got wrong, and what fixed it

1. **Two merge conflicts resolved in favor of both parents.** `container.py` keeps the
   canonical quota recording context (`new_effect_context(..., usage_log=..., quota_tracker=...)`)
   **and** develop's `bootstrap_model_bindings` call; `effect_context.py` merges both docstring
   halves (the #718 recorder params and the #1133 durability note).
2. **Binding-scoped credential routing (#1091) met Bindings that named no credential.**
   `CredentialRouter.acquire` refuses empty `credential_refs`, so every governed model call through
   `GovernedLLMClient` and `conductor._call_gateway` failed with `CredentialScopeError` before any
   HTTP — meaning the ordinary Agent/Workspace call classes #718 requires on the ledger could not
   even execute. Both constructors now authorize the deployment's registered default gateway ref
   (the exact pattern `bootstrap_model_bindings` and hive-conductor's `control_plane_binding`
   already use); acquire stays fail-closed unless that ref is registered in the Binding's own
   Workspace/Project scope.
3. **Test fixtures registered no credential.** The two quota egress tests and the governed Agent
   quota test now register the gateway credential in scope, mirroring `_effects()` in the same
   file, and the hive-conductor adapter test fakes gained the `capability_effects` /
   `provider_registry` / `llm_router` container seams the factory now reads.
4. **Complexity remediation instead of self-authorized grants.** The cutover's inline branches
   pushed `_call_gateway`, `create_agents` and `_reconcile_values_locked` over their trusted
   baselines. The governed conductor completion moved to `_governed_completion`, the factory seam
   to `_governed_llm_client`, and the disposition projection to `_settlement_fields` — all three
   blocks are back under rank C, and their stale/ratcheted ledger entries were pruned from
   `quality/radon-baseline.json`.
5. **Quality ledgers updated for the newly real wiring.** `quota_invocation_evidence` got its
   retention entry (#325, accounting/undecided like `quota_usage`); `quality/reachability-baseline.json`
   and `quality/reachability-dispositions.json` pruned `maistro.quota.recorder` /
   `maistro.quota.ambient` / `maistro.quota.reconciliation`, which are no longer unreachable:
   the recorder is installed at Invocation terminalization, so the CONNECT disposition now covers
   only the explicit-verifier half (`verify.py`, the per-provider verifiers, the SQLite snapshot).

## Validation

- Driver battery: `uv run pytest packages/maistro-core/tests/agents/test_conductor.py
  packages/maistro-core/tests/agents/test_governed_quota.py
  packages/maistro-core/tests/capabilities/test_model_chat_egress.py
  packages/maistro-core/tests/quota/test_reconciliation.py -q` (81 passed),
  `ruff check .` / `ruff format --check .`, and
  `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` all green.
- Wider: quota + capabilities + agents + runs suites (2067 passed), maistro-server (369 passed),
  hive-conductor backend (2653 passed, 1 skipped), canonical mypy (712 files clean).
- Gates: merge markers, suite inventory, durable-table retention, execution lifecycles,
  agent-store writes, model egress, wiring reads, branch independence, shipped-surface truth,
  radon and vulture ratchets, reachability + dispositions provenance.
