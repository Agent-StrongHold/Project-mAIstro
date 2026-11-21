# Issue #860 — frozen CI-repair validation (eb0167cc)

## Scope and checkpoint

- Assigned worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting head: `6d304ff25b9b920513c9a1402ebac4d11f6db5db`.
- Frozen base: `c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250`.
- Only item: #860, including the explicitly assigned vulture CI repair.
- Initial worktree was clean; no incoming edits required salvage.
- The supplied dispatch snapshot and prior result were inspected. No driver
  `check-*.log` files were present in the assigned job directory.
- Actual vulture command, not prior claims:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passed: 1342 findings match 1342 reviewed identities; zero unclassified or
  never-allowlist findings. There is no demonstrated ledger repair to make.
- Assumption: the explicit ledger-repair permission does not require inventing
  debt or changing an already matching ledger. No ledger or grant edits planned.

## Architecture review checkpoint

Read the accepted execution-runtime and lease-fencing ADRs
(`ADR-081426-1f7c`, `ADR-081626-f383`). Physical execution identity is Attempt;
the canonical Run store owns execution authority. Lease-expiry takeover is
explicitly outside the latter ADR's current contract. Do not invent reclaim
semantics or a second scheduler to satisfy the soak wording.

Production `RateLimitMiddleware` creates an `InMemoryRateLimiter` per instance
(`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30,72-78`).
The soak evaluator rejects the host-process topology as an exact RC artifact
(`scripts/soak/run_soak.py:635-646`). These remain actual blockers independent
of the passing vulture gate.

Frozen write set: this report only, unless validation demonstrates an actual
repairable failure. Existing tests will be rerun; no tests or inventory counts
are being added. Historical evidence will not be relabeled as current RC proof.

Also read accepted ADR-085 (canonical principal rate-limit identity) and
ADR-082426-82c7 (occurrence uniqueness belongs to canonical Run admission).
Admission uniqueness is not physical-work uniqueness. ADR-081 is Proposed;
its topology discussion does not supersede the accepted execution contracts.
The production Compose reference actually declares two server replicas and
shared services; the preflight is not equivalent to that artifact.

## Executed validation

All commands below ran in the assigned worktree with long timeouts. Logs from
this worker are `repair-*.log` in the assigned job directory, not driver logs.

| Command | Actual outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 2,985 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 95 passed, 6 skipped; skipped tests are not acceptance proof |
| `uv run pytest tests/test_soak_promotion_gates.py -k 'replica_selection_has_an_independent_production_allowance or four_hour_preflight_cannot_pass_cli' -q` | 5 passed, 47 deselected |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS; 4,755 unique identities; no duplicate evidence |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `uv run python scripts/check-doc-links.py` | PASS; zero broken relative links |
| `git diff --check c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250...HEAD` | PASS at the assigned starting head; prior whitespace finding is not reproduced |

An additional `uv run python` import of the current soak module evaluated the
retained `m3a-round6-shakedown.json`. Assertions passed that the failed gates are
exactly `sustain_duration` and `exact_rc_artifact`, and that the current driver's
artifact check returns false. Recorded duration is 90.43 seconds, not 14,400;
the evidence head is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this checkout.
The passing counterexamples execute real production rate-limit middleware:
the same principal/IP gets `[200, 200, 429]` independently on both instances.
They are in-process ASGI tests, not a deployed multi-replica soak.

## Acceptance audit

| #860 acceptance criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED: profile exists, but `m3a-load-profile.md:152-160` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Canvas and background reconciliation. No representative workload executed here. |
| At least two application replicas | UNVERIFIED for the RC: `deploy/docker-compose.prod.yml:26-76` declares two; tests verify config and middleware seams, not a running promoted topology. |
| Sustained saturation, reclaim, retries and leak observation | UNVERIFIED: executed evaluator rejects the historical 90.43-second window (`evidence/m3a-round6-shakedown.json:221-224`). No new long-running soak executed. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: admission tests are meaningful but do not observe physical Attempt execution. Historical occurrence probe cancels its Run (`evidence/m3a-round6-shakedown.json:11-15`); the accepted fencing ADR does not define expiry takeover. |
| Security/degraded behavior and replica-selection non-bypass | NOT MET as a cluster-wide allowance claim: two freshly passing production-middleware counterexamples (`tests/test_soak_promotion_gates.py:439-488`) show independent replica budgets. Backpressure test passes but cannot close the broader concurrency criterion. |
| Complete production telemetry with thresholds | UNVERIFIED: process-group sampler tests pass; application-loop latency, worker coverage and sustained production metrics remain absent (`m3a-load-profile.md:158-167`). Driver-loop latency is not application latency. |
| Kill/restart during active work; drain/fencing/recovery | UNVERIFIED: no current deployed recovery run. Historical rejoin/terminal counts cannot prove no physical loss or duplication. |
| Long soak of exact promoted RC/config | NOT MET: current evaluator rejects the retained evidence and `preflight_artifact_check()` always rejects host-process topology (`scripts/soak/run_soak.py:635-646`). A four-hour emulator run would not close this. |
| Findings filed/reclassified at earliest broken invariant | UNVERIFIED for completeness; historical findings exist but this run did not establish complete classification. No GitHub mutation performed or permitted. |
| Machine/human evidence bound to exact RC hashes | UNVERIFIED for current RC: historical JSON has an old commit hash and no exact application-image proof. This report records focused validation only, not new promotion evidence. |

## Handoff

Verdict: **BLOCKED** for #860 acceptance, not a vulture CI failure. Only this
report changed. No runtime, gate, ledger, grant, inventory count or historical
soak artifact was altered. Existing meaningful tests were rerun; no new tests
were necessary for a documentation-only validation checkpoint.

Next work requires a representative production-path runner and selected immutable
RC image/config, full telemetry and physical-work/recovery observations, followed
by a new long-running soak. Resolve the replica-budget acceptance discrepancy
without inventing a new authorization path or misrepresenting local enforcement.
Do not repeatedly bank an already matching ledger or rerun a short preflight as
an attempted resolution of these blockers.

Progress: checked 1 issue, done 0 acceptance completions, skipped 0 issues,
errors 0 validation-command failures; #860 remains blocked. Local commit is a
handoff only, not promotion or integration approval.
