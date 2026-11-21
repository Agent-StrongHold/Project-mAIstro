# Issue #860 — CI repair validation (job e895573d)

## Frozen scope and decision

Assigned issue #860 only, branch `auto-860`, starting head
`80a68267b52455262d6059f1153bb89e13335f80`, supplied develop base
`30144ad0f508a6ee5d67c719ed04df5692fb64ea`; both resolve locally.
The assigned worktree was clean on entry. No supplied `check-*.log` files
existed in the job directory; this round executes and records fresh checks.
Dispatch evidence and the supplied prior result were read without refreshing
GitHub. This is the writer lane, not the read-only verifier lane.

The exact requested vulture command already passes: 1,338 reviewed identities
match 1,338 findings, zero unclassified and zero never-allowlist findings.
Its default trusted merge base is `cd5618223cbd`. A second run with
`RATCHET_BASE_REV=30144ad0f508a6ee5d67c719ed04df5692fb64ea` also passes;
`git merge-base` independently confirms that same trusted merge base.
No unbanked identity was reported. The explicit ledger-edit exception does not
justify inventing a scanner finding or making a cosmetic ledger amendment.
Write scope therefore remains this evidence checkpoint only. Validation found
no actionable CI regression. No test additions or edits; no inventory delta.

`uv sync --locked --extra dev` passed. The initial
`git diff --check 30144ad0f508a6ee5d67c719ed04df5692fb64ea...HEAD`
passed; the historical whitespace findings did not reproduce.

## Architecture and acceptance boundaries

Read repository instructions, the load profile, promotion driver and adjacent
promotion tests, the production rate-limit middleware, and relevant ADRs.
Accepted ADR-085 requires principal-keyed limits; it does not authorize a new
authentication path. Accepted ADR-081626-f383 assigns execution authority to
canonical Attempt leases, not admission counters. Accepted ADR-082526-b36a
adds heartbeat/reclaim through that same authority; a single admission race
does not prove sustained physical-work recovery. Accepted ADR-073126-c4e1
requires final artifacts already validated as the RC. ADR-081 is **Proposed**,
not an accepted waiver for absent deployment evidence. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no authority or gate changes.

The current runner explicitly reports `exact_rc_artifact.ok=false`
(`scripts/soak/run_soak.py:635-646`). It cannot certify the promoted Compose
artifact even after four hours. The profile explicitly identifies missing
users/Workspaces, Graph/tool/Canvas and reconciliation coverage, application
loop latency and physical-work recovery (`m3a-load-profile.md:150-164`).
The production middleware constructs `InMemoryRateLimiter` independently in
each instance (`packages/maistro-server/src/maistro_server/api/rate_limit.py:72`).
These are reachable implementation boundaries, not stale verifier assertions.

## Validation results

All commands below were executed in the assigned worktree and exited 0.
Logs are in job directory
`/home/dev/maistro/jobs/e895573d13fa419c8aa7ac7c5a508aad/`.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | Locked environment synchronized. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,338 reviewed identities / findings; also passes with supplied `RATCHET_BASE_REV` above. |
| `uv run ruff check .` | All checks passed. |
| `uv run ruff format --check .` | 2,943 files already formatted. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` | 60 passed. |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 23 passed. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 34 passed, 6 skipped (no configured PostgreSQL integration). |
| `uv run python scripts/check-backlog-consistency.py` | 168 items consistent. |
| `git diff --check 30144ad0f508a6ee5d67c719ed04df5692fb64ea...HEAD` | No whitespace failures in inherited branch changes. |

A `uv run python` probe imported the current driver, loaded retained
`docs/testing/soak/evidence/m3a-round6-shakedown.json`, and asserted that
`failed_promotion_checks` includes `sustain_duration` and `exact_rc_artifact`.
It also asserted `preflight_artifact_check()['ok'] is False`. Assertions pass;
this is successful **rejection**, not a passing soak. Observed duration is
90.43 seconds against 14,400 required. Retained `git_head` at JSON line 70 is
`b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned source head.

## Acceptance assessment

| Issue criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED: profile explicitly lacks users/Workspaces, fan-out, successful tools/models, Canvas and sustained reconciliation. Unit tests cannot fill that gap. |
| At least two application replicas | UNVERIFIED for production: Compose contract tests and two ASGI middleware instances pass, not a deployed replica soak. |
| Sustained saturation, queues, leases, retry, leaks | UNVERIFIED: retained duration fails current evaluator; no new long production run. |
| Schedule/task/Run/Attempt/Goal physical-work safety | UNVERIFIED: admission probe regression tests pass, but admission identities do not prove execution fencing or Goal reconciliation under load. |
| Security/rate/degraded behavior not bypassable by replica selection | NOT MET for a shared allowance: `test_replica_selection_has_an_independent_production_allowance` passes for authenticated and unauthenticated identities; each replica returns 200,200,429 independently. The real app installs this middleware at `maistro_server/main.py:593`. Backpressure tests pass but do not establish deployed security under load. |
| Complete telemetry and explicit thresholds | UNVERIFIED in production: real wrapper/child sampler test passes; application loop latency, detached worker counts and long-window measurements remain absent. |
| Active-work replica kill/restart, drain/fencing/recovery | UNVERIFIED: no production recovery experiment executed; process rejoin alone would not prove physical-work safety. |
| Long soak of exact RC/configuration | NOT MET by available evidence: current evaluator rejects both duration and artifact. No immutable RC image/configuration selected and exercised in this round. |
| Findings classified before promotion | Backlog consistency passes; completeness UNVERIFIED. Existing evidence remains preserved; no GitHub mutation or issue closure. |
| Human/machine evidence bound to exact hashes | UNVERIFIED for current production artifact: retained shakedown targets an older commit. This checkpoint and local logs identify source validation only. |

## Handoff

Issue #860 remains **BLOCKED**. No scanner or whitespace repair was reproduced;
`quality/vulture-baseline.json`, production code, tests and gates are unchanged.
The only changed file is this checkpoint, committed locally; no push.
No new tests require an inventory note.

Required next work: select an immutable RC/configuration, resolve the demonstrated
replica-selection allowance gap through the canonical security seam, implement
representative production-path workloads and telemetry, then execute at least
four hours plus active-work recovery on that exact artifact. Do not dispatch
another speculative vulture-ledger repair for a passing scan. This report is
not a production soak, an acceptance waiver, or integration approval.

Progress: checked 1 assigned issue; done 1 bounded validation/handoff; skipped 0
issues; errors 0 in executed checks. Acceptance remains incomplete; PostgreSQL
integration skips and absent production soak are explicit residual risks.
