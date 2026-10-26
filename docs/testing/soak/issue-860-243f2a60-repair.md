# Issue #860 — bounded CI repair and acceptance review

## Frozen scope

- Issue: #860 only; writer lane `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `fb88bb6843b110293d39705889eb0a74fe88c6c7` (verified; clean).
- Assigned base: `28614700bd9ab0223eac06924a204af4a5cc25d9`.
- Evidence snapshot: job `243f2a603ae34b90b0ebc91ef71931ae` dispatch-context.json,
  supplied prior result `9451a3078c744e668ae54e00c9ea3cb4/result.json`, and
  reported failed check `98a11313167b41a98a420abfda80c292/check-3.log`.
- Edit scope: this report; `quality/vulture-baseline.json` only for actual
  reviewed identities from the prescribed scan; issue-860 soak implementation
  and adjacent tests only if an actual defect requires a focused repair.
- No GitHub mutations, new execution authority, grants or unrelated repairs.

## Initial observations and assumptions

The supplied prior result is BLOCKED and is not proof of current acceptance.
The current job directory contains no driver check-*.log files at start.
This is a writer/CI-repair lane, not a verifier-only lane. Ledger amendment is
explicitly permitted, but is not authorization to weaken debt gates.
The exact promotable RC artifact/configuration is not identified in the lane
brief; do not substitute host-process smoke traffic for production soak proof.

## Progress

- Verified assigned worktree HEAD and clean status; no incoming edits to salvage.
- Read repository instructions and the captured issue acceptance body.
- `uv sync --locked --extra dev`: PASS (248 resolved, 206 checked).
- Prescribed vulture command: PASS, 1,328 reviewed identities/findings,
  zero unclassified/never-allowlist; `/tmp/860-243f-vulture.log`. No actual
  scanner finding warrants a ledger edit.
- Historical check-3.log is a schema-test failure (24 statements versus 21),
  not a vulture failure. Fresh `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**, `/tmp/860-243f-schema.log`. It does not reproduce.
- Profile explicitly says the runner is a host-process preflight, not an exact
  RC deployment, and lists representative-traffic and physical-work gaps.
- A docs lookup for `docs/adr/README*` returned not found; skipped, used the
  existing `docs/README.md` map instead.
- Read accepted ADR-032, ADR-062 (including retired entry-point warning),
  ADR-081626-f383, the soak evaluator and tests, production rate middleware,
  and current schema-fence test. Durable lease authority/stale-writer rejection
  is not a blanket exactly-once physical-side-effect guarantee. Preserve
  `Goal -> Graph -> Run -> NodeRun -> Attempt`; no alternate authority added.
- Focused soak/boot/gitleaks/backpressure/rate tests: **108 passed**;
  `/tmp/860-243f-focused.log`.
- `uv run ruff check .`: PASS; `/tmp/860-243f-ruff.log`.
- `uv run ruff format --check .`: PASS, 3,151 files;
  `/tmp/860-243f-format.log`.
- Inventory, merge-marker, ratchet-provenance and shipped-surface checks: PASS.
  Inventory: 17 suites, 28,959 unique identities, zero duplicate evidence.
  Provenance: 50 consumers have explicit provenance; existing contract gaps
  remain ledgered, not newly proven behavior. Logs:
  `/tmp/860-243f-{inventory,markers,provenance,surfaces}.log`.
- Executed the current evaluator against
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`: rejects
  `sustain_duration` and `exact_rc_artifact`. Duration 420.08 seconds versus
  required 14,400. Asserted both failures and the current runner's false
  artifact result; `/tmp/860-243f-artifact.log`.

## Executed commands

All validation commands used 1,200-second timeouts (dependency sync: 1,000).
No full-tree pytest collection or production soak was attempted.

```text
uv sync --locked --extra dev
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q
uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-suite-inventory.py
uv run python scripts/check-merge-markers.py
uv run python scripts/check-ratchet-provenance.py
uv run python scripts/check-shipped-surface-truth.py
uv run python -  # import current evaluator; assert round-30 rejection
```

## Acceptance disposition

| #860 criterion | Freshly checked evidence / remaining gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `m3a-load-profile.md:153-172` explicitly lacks multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal/worker traffic. No selected RC scope justifies those omissions. |
| At least two production replicas | **UNVERIFIED live.** Existing tests exercise two production middleware instances through ASGI, not immutable production replicas. `run_soak.py:328` launches host uvicorn. |
| Sustained saturation, reclaim, retry/backoff, memory/FD/process leaks and shutdown | **UNVERIFIED.** Sampler regression passes, including real wrapper/child resource growth, but a unit test is not sustained production load; evaluated historical window is only 420.08 seconds. |
| No duplicate physical work across admission/schedules/Attempts/Goal reconciliation | **UNVERIFIED.** Tests validate receipt identities and probe accounting, not physical side effects. `run_soak.py:1050-1067` cancels the schedule probe Run rather than executing it; profile acknowledges the missing sustained Goal reconciliation. |
| Concurrency security/degradation without replica-selection bypass | **NOT PROVEN.** Executed `tests/test_soak_promotion_gates.py:439-488` demonstrates two independent allowances for one identity. `main.py:648` installs production `RateLimitMiddleware`; `api/rate_limit.py:95-100` creates process-local state. Local enforcement tests pass; no cluster-wide allowance is proven. |
| Complete production telemetry and thresholds | **UNVERIFIED.** Current profile documents driver-loop rather than application-loop measurements and missing worker/saturation/reclaim/long-window observations (`m3a-load-profile.md:153-172`). Threshold documentation and sampler tests do not supply deployment observations. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Boot-cleanup tests pass but no live active Attempt kill/recovery was executed. Process rejoin and terminal Run counts cannot prove no loss/duplication. |
| Long exact-RC/config soak, repeated after changes | **NOT MET by evaluated evidence.** Current evaluator rejects round 30; `run_soak.py:730-741` always rejects host preflight artifact equivalence. No immutable RC/config is specified for a new promotion run. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED for completeness.** Existing historical findings preserved. No new load run and no GitHub mutations; local validation is not issue filing or promotion approval. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for promotion.** Historical machine-readable evidence fails artifact gate; this human report is deterministic validation, not production soak evidence. |

## Final disposition and handoff

**BLOCKED for #860 acceptance.** The supplied deterministic failure is stale;
there is no actual unbanked identity or failing focused regression to repair.
No ledger amendment, gate weakening or speculative production change is justified.
Six schema tests skipped; their live PostgreSQL behavior is not proven this round.
The exact-RC runner/profile/physical-work/telemetry prerequisites remain unresolved,
not waived by green unit tests. Accepted lease fencing governs authoritative
Attempt persistence and does not itself promise exactly-once external effects.
Process-local rate enforcement must not be relabeled replica-independent.

Changed file: only this report. No production, tests, runtime config, historical
evidence, ledgers or grants modified. No new tests, so no inventory delta.
Local commit required; no push, PR, issue mutation or integration approval.

Next: select immutable RC image/configuration and supported workload scope;
provide production-path physical-work and telemetry oracles; resolve the
replica-selection acceptance gap; run the at-least-four-hour exact-artifact soak.
Repeating a deterministic CI-repair lane cannot supply those prerequisites.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC production acceptance prerequisites}.
