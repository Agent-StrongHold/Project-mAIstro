---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
---
# issue-1087-evolve-governed-egress

Issue #1087 keeps the shipped Evolve path on the canonical model egress.
The service adapter test exercises an operator-declared model Binding,
canonical model-chat execution, and Invocation correlation to Run, NodeRun,
and Attempt. The canonical graph contract tests verify that contextual model
calls receive the physical evaluation/finalization NodeRun identity and that
failed physical work cannot publish domain mutations (test-level deltas are
itemized in `auto-1087-6da5.md`; none are counted here because that note
already banks this issue's backend test additions against develop's merged
#1064/#1065 baseline).

Repair note: after develop merged #1079's production composition
(f695d491), the two service-adapter integration tests
(`test_build_llm_call_uses_canonical_egress_and_correlates_invocation`,
`test_run_one_cycle_shipped_path_records_governed_invocation`) failed with
`CredentialScopeError` because their `AgentConfig` declared model Bindings
with no deployment gateway secret. The governed egress refusing before any
transport is the correct fail-closed behavior Evolve inherits; the tests now
declare `litellm_key` exactly as a real deployment does, so
`bootstrap_model_bindings` registers the scoped credential and the
shipped-path assertions hold through the governed boundary. No production
code changed and no test was added or removed.

After the develop merge, the maestro-core model-egress composition tests
(`test_model_egress_container_composition.py`) are develop's own superset —
including the disabled-Binding kill-switch and blank-scope validators — so
this issue carries no additional core test delta beyond it.

The direct-egress inventories remove `services.evolution`; the standalone
`maistro_evolve.providers.openai_compatible` adapter remains an intentionally
unreachable library boundary and is not used by production Evolve entry
points.

Verification note (independent, head fc54aa8e = 31e111d45 + develop 8bb344e32
merge): re-ran test_evolution_service.py, test_evolution_canonical_graph.py,
test_evolution_recovery.py, test_evolution_recovery_cadence.py, and
maistro-core test_model_egress_container_composition.py -> 83 passed;
`ruff check .` clean; check-model-egress.py OK (services.evolution pruned,
22 callers, no expansion), reachability and wiring-read gates OK. Invocation
effect-key dedup (invocation.py: COMPLETED returns prior result,
CREATED/RUNNING/UNKNOWN block, only FAILED is retriable under a later
Attempt) plus the deterministic per-NodeRun finalize marker and the
fail-closed `_recovery_resolver` keep replay from double-executing model
effects or double-applying domain mutations. PR #1313 body and branch
commit messages contain no premature closure keywords (Refs only).

Verification note (repair-phase re-run, clean tree at head 22d3833d =
fc54aa8e + inventory-note provenance commit; the prior verification's
evidence was rejected only because its worktree changed mid-run, not for
any check failure): re-executed at this exact head -- pytest
test_evolution_service.py + test_evolution_canonical_graph.py +
test_evolution_recovery.py + test_evolution_recovery_cadence.py -> 77
passed, then test_model_egress_container_composition.py +
test_evolution_persisted_pair_plan.py + test_evolution_canonical_edge_cases.py
-> 24 passed; `ruff check .` and `ruff format --check .` clean;
check-model-egress.py OK (baseline 23 -> candidate 22 direct callers,
services.evolution pruned, no unauthorized expansion), check-reachability.py
OK (1115 modules, ledger matches), check-wiring-reads.py OK (11 unread,
ledger matches), check-suite-inventory.py OK (2658 recorded for
hive-conductor/backend/tests). Confirmed in source: zero httpx/aiohttp/
requests/urllib usage across services/evolution*.py; Invocation stamped
with binding workspace/project + run/node_run/attempt (invocation.py);
maistro_evolve.providers.openai_compatible imported only by its own package
re-export, with no production wiring.

Verification note (independent review, job 45176b2b, clean tree at head
76ca31eaa): re-executed pytest on test_evolution_service.py +
test_evolution_canonical_graph.py + test_evolution_recovery.py +
test_evolution_recovery_cadence.py + test_evolution_persisted_pair_plan.py +
test_evolution_canonical_edge_cases.py -> 95 passed; maistro-core
test_model_egress_container_composition.py -> 6 passed; `ruff check .` clean;
check-model-egress.py OK (baseline 23 -> candidate 22 direct callers,
services.evolution pruned, no expansion) and direct-effect inventory matched
(48 sites); check-reachability.py, check-wiring-reads.py, and
check-suite-inventory.py all OK. Source-confirmed each acceptance criterion:
per-call effect keys (`evolve.model:{node}:{n}:{digest}`) under
ModelChatEgress -> effects.invocations.invoke; Invocation stamped with
binding workspace/project + run/node_run/attempt (invocation.py invoke());
effect-key dedup (COMPLETED returns prior, CREATED/RUNNING/UNKNOWN block,
FAILED retriable); provider timeout terminalizes UNKNOWN and the
first_failure latch + _raise_model_failure keep failed physical work from
publishing evaluation/finalize mutations (faulted marker ->
FinalizeReconciliationRequired); recovery is wired (start/stop_evolution
bracket the cadence), fail-closed via _recovery_resolver/EvolveRecoveryBlocked
with resume-strand NodeResolverUnavailable terminalizing FAILED, and
serialized on the shared cycle_lock;
maistro_evolve.providers.openai_compatible has no new wiring (only its own
package re-export plus a pre-existing import in executable_terminal_runner.py
that no production module imports; unchanged from base 8bb344e32). The
shipped-path integration test enters _EvolutionService._run_one_cycle with
real create_container composition (only the httpx transport stubbed) and
asserts Invocation correlation without hand-built Provider/Binding. PR #1313
body and branch commit messages carry no closure keywords (Refs only).
