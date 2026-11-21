# Issue #860 current-head validation

Starting HEAD was `2d0a80ad7cd11793ca476b0ebd1b11a7a0362915` on branch
`auto-860`; worktree was clean. The frozen dispatch snapshot identifies only
issue #860. The assigned job directory contains no `check-*.log` files, so no
driver-run checks were available to trust. The prior result was read but its
claims were independently checked below.

## Executed checks

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS: 1,315 reviewed identities,
  1,315 findings, `unclassified: 0`, `never_allowlist: 0`; no ledger change.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` — PASS: 93 passed (one Starlette deprecation warning).
- Current evaluator applied to `docs/testing/soak/evidence/m3a-round109-shakedown.json` — failed gates are exactly `sustain_duration` and
  `exact_rc_artifact`; recorded sustain is 420.05 seconds and historical
  evidence identifies commit `5a59c724a20ef1241d57c048df90758f2c2e1e25`.
- Current `preflight_artifact_check()` — `ok=false`, topology
  `host-uvicorn-preflight`, reason: it is not the exact production Compose image
  and configuration.

One first evaluator probe exited nonzero due to looking for `git_head` at the
wrong JSON level. The corrected probe reads identity under `hashes` and produced
the results above; this was a validation-script lookup error, not a product
failure.

## Acceptance disposition

All ten issue criteria remain unproven for final promotion. The current profile
explicitly leaves concurrent users/Workspaces, Graph/node fan-out, successful
tool/model calls, Design/Canvas, sustained Goal reconciliation, physical
Attempt fencing and application/container-level telemetry open or out of scope
(`docs/testing/soak/m3a-load-profile.md`, “Remaining representative-profile
gaps”). Historical two-replica evidence is bounded preflight evidence and cannot
satisfy the exact-RC Compose or four-hour duration gates. No selected immutable
RC/configuration or production soak runner is present in the assigned inputs.
The round-109 profile/evidence records process-local rate limiting; therefore
replica-selection non-bypass is also not established.

Accepted ADR-081226-a66b keeps logical execution and physical attempts under the
canonical Run → NodeRun → Attempt lifecycle; ADR-082426-82c7 binds schedule
uniqueness to the occurrence on the canonical Run; no competing scheduler or
execution authority is proposed. ADR-085 establishes per-principal limiting,
not a shared cross-replica counter. No tests were added, so there is no suite
inventory delta.

Disposition: BLOCKED pending a selected exact production artifact/configuration,
representative workload, and fresh >=14,400-second production soak with complete
telemetry and artifact-bound machine/human disposition. No GitHub actions were
taken.
