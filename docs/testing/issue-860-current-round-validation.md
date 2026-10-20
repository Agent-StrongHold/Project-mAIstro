# Issue #860 current-round validation

## Scope and frozen state

- Assigned item: issue #860 only, branch `auto-860`.
- Starting HEAD: `c1c1fa1e9c4c54295db2386877ae451be9f0f3b8`; worktree initially clean.
- Dispatch develop base resolves to `9417bb2f4ac84447278639c9d8b747f6c8371970`; this branch is one commit behind that ref and has no merge conflict. The supplied prior block was a soak/CI-evidence block, not a develop-sync conflict; no merge was attempted.
- Job directory contained no `check-*.log` files. Prior result JSON was inspected, but its claims were independently rechecked below.
- Read repository instructions and accepted ADR-062 (Graph Execution Protocol). Preserve canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`; no competing execution, authorization, or persistence authority is added.

## Fresh commands and results

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, 1326 reviewed findings / 1326 current findings; zero unclassified and zero never-allowlist identities. No vulture ledger amendment is warranted.
- `uv run python scripts/check-reachability.py` — FAIL: `maistro.runs.admission_identity` is newly unreachable.
- `uv run python scripts/check-ratchet-provenance.py` — FAIL solely through its nested reachability gate, reporting that same unapproved, absent-from-candidate-baseline identity.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — PASS, 84 passed. This is gate/harness test evidence, not a production soak.

The reported unreachable module's own docstring (`packages/maistro-core/src/maistro/runs/admission_identity.py`) explicitly describes it as an inactive contract leaf and says a separately reviewed future integration will introduce the runtime consumer. `packages/maistro-core/src/maistro/runs/__init__.py` does not export it, and production source has no import/callsite. Adding an artificial import solely to satisfy reachability would falsely imply that the contract is wired; adding an unauthorized disposition/grant or editing unrelated ratchet policy is also out of scope. Therefore the real CI failure is recorded, not papered over. It needs a legitimate later integration or a separately authorized disposition. This round is not MERGE-READY.

The prior exact-vulture-ledger repair direction is reconciled with the current run: this required scan is clean; the only fresh scanner failure is reachability, so changing `quality/vulture-baseline.json` would be both irrelevant and forbidden.

## Issue acceptance status

The issue's ten acceptance criteria remain release evidence requirements. Source/test inspection and the fresh 84-test run do not substitute for deployed evidence:

1. Representative RC workload — UNVERIFIED. `docs/testing/soak/m3a-load-profile.md` explicitly leaves concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work out of its current profile.
2. At least two production replicas — UNVERIFIED; ASGI middleware tests are not deployed replicas.
3. Sustained saturation, queue/reclaim/retry behavior and leak/shutdown observations — UNVERIFIED; no production soak run in this round.
4. Exactly-once/fenced physical work and Goal reconciliation — UNVERIFIED; admission or schedule claims are not physical Attempt execution/fencing evidence.
5. Replica-selection non-bypass — NOT PROVEN. `tests/test_soak_promotion_gates.py::test_rate_probe_with_production_middleware` exercises real middleware instances but asserts each instance's independent budget; it demonstrates the multi-replica gap, not a shared production budget.
6. Required telemetry and explicit thresholds — UNVERIFIED for a production measurement window.
7. Active-work restart, drain, fencing and recovery — UNVERIFIED; no active deployed work was killed/restarted.
8. Long exact-RC/configuration soak — UNVERIFIED. `scripts/soak/run_soak.py` says the host-process preflight always fails `exact_rc_artifact`; historical short/stale evidence cannot prove this criterion.
9. Load findings classified at the earliest broken invariant — UNVERIFIED for findings from a future candidate RC soak.
10. Machine/human-readable evidence bound to exact artifact/config hashes — UNVERIFIED for the RC artifact; no new production evidence pack was created.

No tests were added, so no inventory-delta note is applicable. No source, runtime configuration, reachability ledger, vulture ledger, baseline or authorization was changed. No GitHub mutations were performed.

## Disposition

**BLOCKED / NEEDS-REPAIR.** The exact vulture debt is clean; reachability CI fails for the intentionally inactive but un-dispositioned module; and the production soak acceptance is still unproven. Next work must address the reachability identity through legitimate integration/authorized governance and provide a representative, multi-replica exact-RC soak with the required telemetry and recovery evidence. Checked: 1 assigned item; completed implementation repair: 0; skipped: 0; errors: 2 failing gates; acceptance complete: 0.
