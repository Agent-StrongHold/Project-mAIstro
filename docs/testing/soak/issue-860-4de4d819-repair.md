# Issue #860 — repair round 4de4d819

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting head `b8d11d02c11c841f15d4f3acd540dd13da4a669b`;
  supplied base `b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`.
- Only issue #860; no GitHub mutations, ref updates, or unrelated repairs.
- Initial worktree clean; no incoming edits to salvage.
- Job directory has no `check-*.log`; run fresh validation instead.
- Process: exact vulture CI scan, retained soak harness/production admission
  evidence and adjacent tests, acceptance report, local commit.
- Candidate edits limited to this report and (only if scanner evidence requires)
  `quality/vulture-baseline.json` or genuinely dead identities reported by it.
  Test additions would require an inventory note. No test additions planned.
- Ambiguity: dispatch is a CI repair but prior result is acceptance-blocked.
  Proceed by independently checking CI and acceptance; passing CI must not be
  presented as proof of a production soak. No sync conflict was present.

## Results

Exact requested vulture command exited 0: 1,338 findings / 1,338 reviewed
identities, zero unclassified and zero never-allowlist findings. No ledger
amendment or dead-code repair is supported by that output. Its default base
resolved to `cd5618223cbd`; repeat with the explicit assigned base to avoid
mistaking that default for the dispatch's integration comparison.

Source review confirms the existing runner is a host-process preflight, not a
production Compose runner (`m3a-load-profile.md:16-24`). Its profile explicitly
leaves representative traffic and production instrumentation incomplete. Fresh
acceptance tests and explicit-base CI checks executed: exact vulture scan with
`RATCHET_BASE_REV=b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`, repository ruff
check/format, soak/boot contract tests, adjacent task-backpressure/learning-store
tests and supplied-base `git diff --check` all exited 0. Full outputs are
`check-*.log` in the assigned job directory. Detailed counts follow below.

## Architecture reconciliation

Read repository instructions, ADR-081 (Proposed), ADR-085 (Accepted),
ADR-081626-f383 (Accepted) and ADR-082126-f69c (Accepted). Recurrence must create
canonical Runs, not a second scheduler; Attempt authority remains the canonical
store's lease/fencing token. The accepted per-principal rate-limit ADR does not
supply a waiver for #860's replica-selection criterion. Current middleware
explicitly documents independent per-process allowances. Preserve the existing
`Goal -> Graph -> Run -> NodeRun -> Attempt` model and report that limitation,
not invent a replacement authorization or execution path for this CI repair.

## Executed validation

All commands used `uv run` and a 1,200-second command timeout. Logs are in
`/home/dev/maistro/jobs/4de4d819da01461abd39300201d0872f/`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, twice (default and explicit assigned base); 1,338 reviewed / observed identities; no ledger edits warranted |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 2,943 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` | 60 passed |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 35 passed, 6 skipped; skipped tests are not PostgreSQL integration proof |
| `uv run python scripts/check-ratchet-provenance.py` | PASS |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-backlog-consistency.py` | PASS |
| `git diff --check b672b799aba6d3db9edc3e1be18b1a3335dd3bc0...HEAD` | PASS; prior EOF finding not reproduced |
| `uv run python` importing the current evaluator against retained round-6 evidence | PASS: asserts rejection for `sustain_duration` and `exact_rc_artifact`; see `check-retained-evidence.log` |

The explicit-base gates used
`RATCHET_BASE_REV=b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`.
`git merge-base` confirms the gate's `cd5618223cbd` baseline is the merge base
of that supplied ref and HEAD, not a lost environment override. These checks
validate this branch, not an unperformed integration merge.

## Acceptance ledger

| #860 criterion | Fresh review / executed evidence | Status |
| --- | --- | --- |
| Representative users/Workspaces and request/Graph/tool/Canvas/background mix | `m3a-load-profile.md:152-165` explicitly identifies absent traffic classes; no promotion workload executed | UNVERIFIED |
| At least two production application replicas | `deploy/docker-compose.prod.yml:26-78` defines two, but runner `preflight_artifact_check()` rejects its host topology; passing boot contract tests are static/configuration checks | UNVERIFIED |
| Sustained saturation, queues, expiry/reclaim, retry, leaks, shutdown | Re-evaluated retained evidence: 90.43 seconds versus 14,400 required; no new sustained run | UNVERIFIED |
| No duplicate physical work for schedule/task/Run/Attempt and Goal reconciliation | Admission tests validate receipt evidence, not physical execution; profile lines 197-200 explicitly limit the cancelled schedule probe | UNVERIFIED |
| Security/rate/degraded behavior cannot be bypassed by replica selection | Executed both parameterizations of `test_replica_selection_has_an_independent_production_allowance`: same identity receives `[200,200,429]` independently on both real middleware instances (`tests/test_soak_promotion_gates.py:437-488`); production installs that middleware at `maistro_server/main.py:593` | NOT MET for the stated non-bypass requirement |
| Complete PostgreSQL/application-loop/worker/RSS/fd/queue/error telemetry and thresholds | Sampler tests passed, but profile lines 156-165 distinguish process-group/driver measurements from application/container observations; no fresh production series | UNVERIFIED |
| Kill/restart during active work proves drain/fencing/recovery | Retained process exit/rejoin is insufficient to establish physical-work fencing; no production active-work restart executed | UNVERIFIED |
| Long soak of exact RC artifact/configuration | Fresh evaluator rejects retained evidence on duration and artifact; `scripts/soak/run_soak.py:635-646` correctly hard-fails host preflight | NOT MET |
| Classify findings to earliest broken milestone invariant | Existing backlog is consistent (gate passes); complete under-load finding classification not proven without representative execution | UNVERIFIED |
| Publish machine/human evidence tied to exact promoted hashes | Retained JSON names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not assigned head; no new image/config-bound production evidence | UNVERIFIED |

Passing tests above prove harness safeguards and counterexamples, not an RC
promotion. Existing production behavior is unchanged. No test was added and no
inventory delta is required. No ledger, grant, gate, or historical evidence was
modified.

## Handoff

**BLOCKED** for #860 acceptance. The assigned CI defect does not reproduce;
changing the ledger or code to manufacture a repair would not be evidence-led.
This round changes only this report and commits it locally. It does not claim
issue completion or integration approval.

Next work requires an exact-RC Compose workload with the omitted representative
surfaces and telemetry, plus resolution of replica-selection non-bypass at the
canonical security seam, followed by at least the profile's four-hour soak and
active-work recovery assertions. Re-running this same CI-only lane cannot
supply that evidence. Do not reinterpret preflight or unit-test success as a
waiver. No Docker services were changed and no GitHub action was taken.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues;
skipped 0 issues; validation command errors 0. CI review complete; acceptance
blocked as above.
