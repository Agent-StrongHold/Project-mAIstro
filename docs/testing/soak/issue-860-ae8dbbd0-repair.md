# Issue #860 — ae8dbbd0 repair checkpoint

## Frozen scope and initial evidence

Only issue #860, branch `auto-860`, starting head
`044c994481df07dc97d4ee6744dccb55ebfaa6c9`, assigned base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Worktree initially clean.
Read the assigned dispatch snapshot; do not refresh remote issues/PRs.
Repair candidates are `quality/vulture-baseline.json` (only actual scan debt),
`packages/maistro-core/src/maistro/persistence/pg_learnings.py` and its adjacent
`tests/persistence/test_pg_learnings.py` (supplied failure), and
`scripts/soak/run_soak.py` / `tests/test_soak_promotion_gates.py` (acceptance).
This report is the only planned change absent a reproduced defect.

Current job directory has no driver `check-*.log` files. The supplied historical
`98a11313167b41a98a420abfda80c292/check-3.log` fails on 24 schema statements versus
21 expected. Prior BLOCKED result is evidence to recheck, not acceptance proof.
Assumption: writer role applies; no immutable RC/configuration was designated.

## Executed validation

- Exact mandated vulture command: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS,
  1323 reviewed identities / 1323 findings, zero unclassified. The gate resolved
  its trusted baseline to `4aa68edc0b6b`; candidate is the assigned head.
  No ledger amendment is justified by actual findings.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q -rs`: 37 passed, 6 PostgreSQL-dependent skips. Historical failure does
  not reproduce. No speculative schema or test edit is warranted.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q -rs`: 66 passed, including two real production middleware instances,
  missing/null/preflight artifact rejection, and real child-process metrics.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified /
  19 discovered lifecycles.
- `git diff --check`: PASS.
- Executed a `uv run python` import/replay of `failed_promotion_checks` on
  `docs/testing/soak/evidence/m3a-round43-shakedown.json`: fails
  `sustain_duration` and `exact_rc_artifact`, as independently asserted.
  Recorded duration is 420.09 seconds; minimum is 14400. Also asserted
  `preflight_artifact_check()['ok'] is False`. This validates rejection, not
  the truth of the historical measurements.

## Architecture and acceptance review

Read the captured issue body (dispatch-context.json:189), adjacent production
code/tests, the load profile, ADR-081 (Proposed), ADR-085 (Accepted), and accepted
ADR-081426-1f7c / ADR-081626-f383. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: physical execution identity is
Attempt, not an admission receipt. The fencing ADR explicitly leaves expiry
reclaim undefined; this issue cannot authorize a competing reclaim authority.
ADR-085 requires principal-keyed limits but does not specify shared storage.
The replica-independent allowance requirement remains unresolved, not waived.

| Acceptance criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC workload | UNVERIFIED. `m3a-load-profile.md` describes one API key, absent LiteLLM and missing Workspace population, Graph fan-out, successful tool/model traffic, Design/Canvas and background reconciliation. Applicability to a designated RC is not established. |
| At least two deployed replicas | UNVERIFIED for RC. Two middleware instances were exercised in ASGI tests, not two deployed RC replicas. |
| Sustained saturation, reclaim, retries and leaks | UNVERIFIED. Replayed historical 420.09-second evidence fails the four-hour gate. No long-window execution this round. |
| No duplicate physical work / reconciliation | UNVERIFIED. Admission tests do not establish physical Attempt side-effect uniqueness or sustained Goal reconciliation. |
| Replica-independent rate/security/degraded behavior | Aggregate allowance claim is falsified by executed `test_replica_selection_has_an_independent_production_allowance` (both identity classes). Each instance accepts `[200, 200, 429]` for the same identity independently. `main.py:648` installs that middleware; `api/rate_limit.py:94` creates a per-instance limiter. Other RC-load security properties remain UNVERIFIED. |
| Complete metrics and thresholds | UNVERIFIED. Process-group sampler tests pass, but driver-loop lag is not application-loop lag and the profile lacks complete worker/pool/long-window evidence. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED. No deployed replica was restarted this round; boot-cleanup tests and terminal Run counts are not physical-work recovery proof. |
| Long-running exact RC/configuration | BLOCKED. No immutable RC/configuration designated. `run_soak.py:730` explicitly rejects this host-process runner as exact-artifact evidence; its rejection is exercised by the CLI regression tests. |
| Findings filed/reclassified | UNVERIFIED externally. Local historical findings cannot establish current disposition. No GitHub mutation allowed or performed. |
| Hash-tied machine/human RC evidence | UNVERIFIED. Historical evidence fails the current evaluator; this checkpoint is validation evidence, not a promotion soak. |

## Final handoff

Only this report changed. No production/test/gate/ledger changes were justified
by reproduced evidence. No tests added or modified: inventory delta is zero,
so no new inventory note is required. No existing work was discarded, no merge
or remote mutation performed. This is not a develop-sync conflict.

The supplied failure is obsolete at the assigned head: the schema test already
includes the three validation audit columns at lines 177–179. The mandated
vulture scan also passes; do not manufacture ledger changes to satisfy the repair
label. Six DB-dependent skips remain explicit limitations.

Verdict: BLOCKED. Next required input/work is a selected immutable RC and
configuration, owner resolution of replica allowance semantics, and an exact-
topology runner with physical Attempt correlation and application metrics. Then
execute the sustained window on that unchanged RC. A longer run of the existing
preflight cannot satisfy acceptance. Preserve this checkpoint with a local
commit; this is not integration approval.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 validation commands; 6 DB test skips. No additional items started.
