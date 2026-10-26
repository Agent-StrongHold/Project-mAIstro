# Issue #860 — 43f575a1 repair checkpoint

## Frozen scope and first result

Writer repair of #860 only in `auto-860`, starting at
`d15529864cfb182c8212c7d30659eb0c385d6e03`, dispatch base
`c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250`. Both refs resolved locally;
the worktree was clean. No supplied `check-*.log` files existed in the job
directory. Read the captured issue acceptance and supplied prior result, not
remote GitHub state. No list refresh, remote mutation, or discarded work.

The exact requested CI scan freshly passed:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
It compared against the dispatch base and found **1,342 reviewed identities /
1,342 findings, zero unclassified, zero never-allowlist**. There is no observed
ledger defect to repair; no speculative ledger or authorization change is
justified. Log: job directory `worker-vulture.log`.

Scope remains the existing soak harness, its production seams/adjacent tests,
profile/evidence, relevant ADRs and validation of the assigned acceptance.
This note records the writer checkpoint. No tests or production files changed;
inventory delta is zero, so no new inventory note is warranted.

## Architecture and production reachability

Read accepted ADR-081426-1f7c (physical execution identity is Attempt),
ADR-081626-f383 (canonical Run store owns fencing; expiry takeover is not yet
specified), ADR-082426-82c7 (occurrence uniqueness is Run admission), and ADR-085
(principal-keyed request limiting). ADR-081 deployment topology is Proposed.
These do not authorize a second scheduler/authority or treating Run-admission
counts as physical-work proof. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`. The process-local #842 policy is not a waiver of #860's stronger
replica-selection acceptance; report that mismatch rather than invent a shared
authorization path in a soak repair.

Production `packages/maistro-server/src/maistro_server/main.py:627` installs
`RateLimitMiddleware`. Its constructor (`api/rate_limit.py:72-77`) creates an
independent in-memory limiter, explicitly documented at lines 25-30. Existing
`tests/test_soak_promotion_gates.py:439-488` exercises actual production
middleware: the same principal/client gets `[200,200,429]` separately on both
replicas. Those tests passed freshly; they are a counterexample to a shared
allowance, not a deployed-soak proof. The adjacent task backpressure test uses
the real router/queue/Run spine and also passed.

`deploy/docker-compose.prod.yml:26-29,75-76` describes two locally built server
services, not a designated immutable RC. `scripts/soak/run_soak.py:635-646`
explicitly returns `exact_rc_artifact.ok=false` for its host-uvicorn preflight.
The profile at `m3a-load-profile.md:152-165,197-201` explicitly lacks representative
user/Workspace, Graph/tool/Canvas/Goal and physical-effect/telemetry coverage.
No current exact-RC soak was executed or inferred from unit tests.

## Fresh validation

- Exact CI vulture command above: PASS; workflow arguments confirmed in
  `.github/workflows/vulture-ratchet.yml:82-85`.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2,985 files.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  PASS, 117 passed / 6 skipped (3.60 s). Skips are not acceptance evidence.
- `git diff --check c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250...HEAD`:
  PASS. Supplied historical EOF failures do not reproduce; no cosmetic fix made.

- `uv run pytest packages/maistro-server/tests -x -q`: PASS, 500 passed /
  9 skipped, 22 deprecation warnings (26.57 s).
- `uv run python scripts/check-deployment-claims.py`: PASS. This checks declared
  components exist, not deployed multi-replica behavior.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS, 4,755
  unique test identities match inventory.
- `uv run python -` importing the actual soak runner and evaluating the retained
  `m3a-round6-shakedown.json`: PASS assertions that failures are exactly
  `sustain_duration` and `exact_rc_artifact`, and that the current preflight
  artifact check returns false. The recorded duration is 90.43 seconds against
  the required 14,400; this is a fresh rejection of historical evidence, not a
  fresh soak. Log: `worker-evidence-evaluation.log`.

Commands used 1,800-second timeouts. Logs are in the supplied job directory
under `worker-*.log`. All executed validation commands passed; none proves the
missing production acceptance below.

## Acceptance audit

| # | Criterion | Executed evidence / disposition |
| --- | --- | --- |
| 1 | Representative release-candidate profile | UNVERIFIED: inspected profile documents one-key provider-less preflight, with user/Workspace, Graph/node, tool/model, Canvas/Design and background workloads missing or not justified against a selected RC. |
| 2 | At least two production replicas | UNVERIFIED: reference Compose has two services; passing two-ASGI-instance tests do not establish deployed RC replicas. |
| 3 | Sustained saturation, queue, lease/retry and leak observations | UNVERIFIED: current evaluator rejects historical 90.43-second evidence against 14,400 seconds. No new long-window load executed. |
| 4 | Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: admission-oracle tests passed; one Run identity and a cancelled schedule probe are not physical Attempt-effect proof. Accepted fencing ADR does not authorize assuming expiry takeover. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared principal allowance: existing production-middleware counterexamples pass, demonstrating fresh allowance on replica 2. Local rate-limit/backpressure tests passed; complete deployed security/degraded behavior remains UNVERIFIED. |
| 6 | All required production metrics with thresholds | UNVERIFIED: process-group sampler tests passed, including real child-resource growth, but no current application-loop, worker/container, pool/lock/queue or long-window metrics were captured. |
| 7 | Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: no current RC restart or physical-effect reconciliation run. Historical process rejoin and terminal Run counts are insufficient. |
| 8 | Long-running exact RC artifact/configuration | NOT MET: actual evaluator rejects retained evidence; production runner still sets exact-artifact check false. No immutable RC/configuration designated in the supplied assignment. |
| 9 | Findings filed/reclassified to earliest broken milestone | PARTIAL: inspected `m3a-soak-evidence.md:224-252` classifies F11/F12 as M3-A evidence-validity failures. Complete filing/reclassification UNVERIFIED; this lane prohibits GitHub mutations. |
| 10 | Machine/human evidence tied to exact promotion hashes | UNVERIFIED for current RC: historical evidence and human report exist, but the actual evaluator rejects them; no new hash-bound production soak artifact produced. |

## Handoff

**BLOCKED**. The requested vulture repair has no reproduced defect: do not amend
an already matching ledger. The prior runtime/evidence blocker is not resolved
by static gates or additional unit-test success. Only this checkpoint note
changes; no runtime, test, config, gate or ledger changes. This is not promotion
or integration approval.

Next: designate the immutable promotion RC/configuration, reconcile the
process-local rate-limit deployment contract with #860's non-bypass requirement,
complete representative production workloads and physical-effect/telemetry
oracles, then execute and publish a new >=4-hour exact-artifact soak. Merely
extending the host preflight's duration cannot satisfy acceptance.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and production soak}`.
Writer validation is complete and recorded for a local commit; issue acceptance
remains blocked. No remote mutations or destructive git operations performed.
