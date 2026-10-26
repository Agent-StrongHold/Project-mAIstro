# Issue #860 repair checkpoint — 0159386d

## Frozen scope

Only issue #860, assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting HEAD `75db0d68dd99ce71b626124c84b2ac5f7431b067`;
comparison base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Starting worktree is clean. No sync conflict is present.

Process the supplied dispatch snapshot only. Inspect the soak harness,
its adjacent tests, production paths they exercise, relevant ADRs, and the
explicit vulture gate. Potential edits: this report; genuine dead code or
reviewed retained identities reported by that gate in
`quality/vulture-baseline.json`. No speculative gate or runtime changes.

Current job directory contains no `check-*.log` files. Prior result reports
BLOCKED; that claim is not treated as fresh validation. The branch contains
extensive inherited changes, preserved as received.

## Progress

- Exact starting HEAD and clean status verified.
- Repository instructions and prior result read.
- Ambiguity: dispatch `issue` is a number, not the issue body; inspect the
  supplied `sources` object rather than refetching GitHub.
- Required vulture command passed: 1323 reviewed identities / 1323 findings,
  zero unclassified and never-allowlist findings. No ledger amendment is
  justified by this scan (trusted merge base reported as `4aa68edc0b6b`).
- Issue body located in the supplied sources snapshot: ten acceptance criteria,
  including physical-work uniqueness, non-bypassable replica security, and an
  unchanged exact-RC soak. No GitHub refetch performed.
- Historical `98a11313/check-3.log` inspected: schema fence expected 21 DDL
  statements but observed 24. Fresh reproduction pending.
- Read adjacent soak tests and load profile. They explicitly distinguish host
  preflight and admission probes from exact-RC physical execution evidence.
  Acceptance review and focused tests completed below.

## Executed validation

All commands ran in the assigned worktree against the starting code; this round
changes only this report.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323/1323 identities; exact workflow scan arguments |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs` | 103 passed, 6 skipped in 2.34 s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files formatted |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 53 consumers; existing regex escape warnings only |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

The historical schema-count failure does not reproduce. All six skips require
`MAISTRO_TEST_PG_DSN` and therefore provide no live PostgreSQL evidence. No new
tests or suite-count changes were made; no inventory delta is required. No
unbanked vulture identities exist to justify a ledger amendment. These focused
checks are not a validation of every inherited branch change.

## Architectural reconciliation

Read Accepted ADR-081226-a66b (one Run/NodeRun/Attempt lifecycle),
ADR-081626-f383 (canonical-store execution leases and stale-writer fencing),
ADR-082426-82c7 (occurrence uniqueness on the Run, not a second claim store), and
ADR-085 (canonical per-principal request limits independent of token quota).
No execution or authorization authority was introduced or changed. In particular,
occurrence admission uniqueness is not physical execution uniqueness. Lease
expiry/reclaim must respect the accepted lease contract, not be invented by the
load harness to satisfy the issue wording.

## Acceptance evidence (all ten issue criteria)

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `scripts/soak/run_soak.py:1375` uses one credential; the mix at line 1383 covers health/task/receipt/metrics, not concurrent Workspaces, Graph fan-out, successful model/tool work, Design/Canvas or background-worker coverage. The profile explicitly records these gaps. |
| Two supported application replicas | **UNVERIFIED** for the RC topology. Existing tests use ASGI middleware instances and one real sampler child process; neither is a deployed two-replica RC soak. |
| Sustained pool/queue/reclaim/retry/leak/shutdown observations | **UNVERIFIED**. The child-process sampler regression passed, but no new sustained production load was run. |
| No duplicate physical work, including schedules/Run/Attempt/Goal paths | **UNVERIFIED**. `scripts/soak/run_soak.py:1044` cancels the schedule admission probe without executing its Run; admission-only success cannot prove physical effects or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed through replica selection | **NOT PROVEN**. Freshly passing `tests/test_soak_promotion_gates.py:439` reproduces independent allowances for the same identity on both real production limiter instances, for authenticated and unauthenticated requests. The middleware is actually registered at `packages/maistro-server/src/maistro_server/main.py:648`; process-local semantics are explicit at `api/rate_limit.py:32`. Local 429 enforcement is not a shared budget. |
| Complete telemetry with thresholds | **UNVERIFIED**. Sampler tests pass; `scripts/soak/run_soak.py:1421` measures driver-loop lag, not application-loop lag. No complete RC worker/DB contention/queue/timeout telemetry was collected. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. Existing boot-cleanup tests pass; the process exit/rejoin path at `scripts/soak/run_soak.py:1439` does not reconcile physical effects or stale Attempt ownership. |
| Long unchanged exact-RC soak | **UNVERIFIED / BLOCKED**. `scripts/soak/run_soak.py:730` explicitly rejects its host preflight as exact-RC evidence. Fresh four-hour synthetic CLI regression cases fail closed as designed. No exact RC image/configuration was selected or soaked. |
| Findings filed/reclassified to earliest broken invariant | Gaps recorded locally in this report and existing profile. External disposition **UNVERIFIED**; no GitHub mutation authorized. |
| Machine/human evidence bound to exact image/package/commit/config | **UNVERIFIED** for the RC. Historical artifacts preserved unchanged; this report is focused validation, not a new machine-readable production soak. |

## Handoff

**BLOCKED for issue acceptance.** No current CI failure was reproduced and no
speculative runtime or ledger repair is justified. The previous BLOCKED state is
confirmed, not resolved. Resolving it requires a selected exact-RC deployment,
representative production workloads and physical execution/recovery oracles,
resolution of the replica-rate-limit acceptance mismatch, complete application
telemetry, and a new unchanged-artifact long soak. A longer run of the existing
host preflight cannot resolve the explicit artifact gate. Do not redispatch a
clean-ledger repair as a substitute for that work.

Only `docs/testing/soak/issue-860-0159386d-repair.md` changed this round.
No push, PR, issue mutation, merge, or gate weakening performed.
Progress: checked 1, done 0 (acceptance incomplete), skipped 0, errors 0 validation
command failures. Next: resolve the production acceptance blockers above.

