---
inventory-delta:
  packages/maistro-core/tests: +25
  packages/hive-conductor/backend/tests: +4
---

# auto-846 CI repair — fail-closed branch proofs for #846

Local reproduction of the CI finding at 0d6b3ec508dc ("Coverage gate
(publish-set floor + diff coverage) = failure") showed the aggregate floor was
never the problem: the per-file diff gate flagged the #846 repair code itself —
the fail-closed branches of `HarnessSessionManager`, the governed Invocation
composition root, `RuleBasedRepair`'s effect boundary, and the Conductor
self-repair wiring — as changed-but-uncovered. This note records the tests that
exercise those shipped degraded paths, plus the inventory delta they cost.

New files:

- `packages/maistro-core/tests/capabilities/test_harness_manager_fail_closed.py`
  (+19): drives the real manager through every shipped degraded branch —
  gate-factory admission, read-only refusal when no policy/factory exists
  (send/stream/stop/`send_invocation`), revoked-Binding start and stop,
  provider swap and provider-pin mismatch at invocation time, unhealthy
  provider at invocation time, foreign-capability and config-carrying
  Bindings on a cached session, provider-contract violations, and the
  fail-closed `ValueError` when a Binding pins a provider that never matches.
  No test in the file reaches a provider call on a denied path.
- `packages/maistro-core/tests/capabilities/test_governed_invocation_delegation.py`
  (+5): policy narrowing via `with_policy_evaluator`, delegated
  `discover_ambiguous` and provider-backed reconciliation through the governed
  composition root (including the UNKNOWN-settles-silently audit rule), the
  re-encountered PENDING approval (same durable request, re-audited, no
  provider call), and the rule that a granted approval cannot force a policy
  DENY into an allow.

Extended files:

- `test_self_repair_provider_gaps.py` (+1): the governed effect boundary
  itself refuses (`no governed infra_action`) when an actor reaches it without
  an invoker.
- `test_capabilities_wiring.py` (+4): self-repair registration fails closed
  with no monitor provider, with a BindingStore lacking the boot seam, and
  when the boot Binding was revoked; and the shipped guarded invoker refuses a
  BindingStore that resolves a redirected identity, with no provider call.

## Validation evidence (local, this head)

- `uv run ruff check .` / `ruff format --check .`: clean.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: 1404 reviewed identities,
  0 unclassified, 0 never-allowlist — ledger clean.
- Publish-set coverage floor: core+canvas+evolve+rsi+bootstrap producers
  re-run locally under `coverage run --branch`; `coverage report
  --fail-under=87` → TOTAL 91% (was 90% before these tests).
- `scripts/check-diff-coverage.py coverage.xml --base <merge-base 730857f1c1b9>`:
  was `FAIL: 4 file(s) below the diff-coverage floor` at the round's start;
  after these tests: `ok: every measured file this change touches is at or
  above 90% lines / 80% branch arcs`.
- Full producer battery green locally: core 10634 passed, canvas 399, evolve
  645, rsi 786, bootstrap 233, server 401, turing 190+69, design 351, registry
  257, hive-conductor 2859, root/scripts 4013.

## Known environment artifact (not a product defect)

`test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_fallback`
assumes `127.0.0.1:1` refuses instantly (asyncpg `_connect` does not retry
OSError). On this WSL2 host the mirrored-network firewall silently drops the
SYN, so the connect hangs into asyncpg's own 60s timeout and trips the
suite's `--timeout=30`. The test passes in isolation and would pass on a CI
runner where the port refuses; no source or gate change was made for it.
