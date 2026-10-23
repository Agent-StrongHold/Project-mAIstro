# Issue #860 repair checkpoint — dbf45f19

## Frozen scope

- One assigned item: #860, branch `auto-860`, starting head
  `fd72efc60c0547183bf68528f226da2fed797ddc`, base
  `4c78db163f03c8f4410c90e3ad2c1dc328cc87f1`; both resolved locally.
- Worktree `/home/dev/Git/wt/auto-860` started clean. No salvage necessary.
- Inspect existing soak profile/evidence, harness, adjacent promotion tests,
  rate-limit implementation, relevant ADRs, and the requested vulture gate.
  Modify only this report and evidence-backed #860 repairs (including the
  expressly permitted vulture ledger if that gate identifies retained debt).
- Job directory contains no `check-*.log` files at initial inspection; supplied
  driver results cannot be verified. Do not infer a pass.
- Prior result file exists and will be read. No issue/PR re-enumeration or GitHub
  mutations will be performed.

## Ambiguity and assumption

This is the assigned writer/CI-repair round, not a read-only verifier round.
A host preflight cannot substitute for the exact RC artifact/configuration
promotion soak. A missing RC identity is a blocker, not permission to invent one.

## Progress

Scope frozen; repository instructions read; production and test review pending.

## Salvage continuation — job 3d2f201b

This preceding checkpoint was found untracked and preserved unchanged above.
Backups: `../incoming-860-3d2f201b.patch` and
`../incoming-860-3d2f201b-handoff.md` (outside the worktree).

Current frozen scope: issue #860 only, branch `auto-860`, starting head
`fd72efc60c0547183bf68528f226da2fed797ddc`, assigned base
`f5fa43771103d140c7d485959e914aa8fce33079`; both refs resolved locally.
Inspect the existing profile/evidence, production limiter, harness, adjacent
promotion tests, relevant ADRs and explicit vulture CI gate. Only evidence-backed
repairs, the authorized ledger if necessary, and this salvaged report are writable.
This is a writer round; no GitHub mutations or invented RC identity.

Initial results: repository instructions and prior job result read. No
`check-*.log` files exist in the assigned job directory, so driver claims cannot
be confirmed. The current evidence pack already retracts the historical shared
limiter claim and marks wrapper-only RSS measurements invalid; do not redo those
repairs. The profile explicitly excludes promotion signing by the host harness.
Validation and production-path/test review follow below.

### Executed validation checkpoint

- Explicit vulture command passed: 1,368 findings, 1,368 reviewed identities,
  zero unclassified/never-allowlist. The checker independently selected trusted
  base `4c78db163f03`; this is not the assigned comparison base. No gate override
  or ledger amendment is justified by this result.
- `uv run ruff check .` and `uv run ruff format --check .`: exit 0.
- Focused pytest (PG learnings, task concurrency backpressure, soak promotion
  gates, production-stack boot contract): exit 0; detailed counts below after
  reading the log.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format
  '{{.ServerVersion}}'`: exit 1, cannot connect to daemon. No stack was launched.
- Read accepted ADR-081426-1f7c (Attempt runtime mechanics), ADR-081626-f383
  (durable fencing), ADR-085 (principal limits), and ADR-083126-5e62 (quality
  evidence authority). Reconciliation: do not introduce a second scheduler or
  authorization path; durable admission is not physical-work uniqueness, and
  fencing ADR explicitly does not grant implicit lease-expiry takeover.
- Production limiter constructs its own `InMemoryRateLimiter` per instance;
  six-path rejection tests do not prove replica-selection non-bypass. Existing
  regressions test this distinction. Existing docs already correct the prior
  overclaim; no cosmetic rewrite or guessed scanner repair was made.

### Final executed results

Logs are under `/home/dev/maistro/jobs/3d2f201b63424cfc88b37b8eea85dbf0/`.
These are worker runs, not the absent driver `check-*.log` files.

| Command | Result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; `worker-vulture.log` |
| `uv run ruff check .` | PASS; `worker-ruff-check.log` |
| `uv run ruff format --check .` | PASS, 2,738 files; `worker-ruff-format.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 88 passed, 5 skipped in 4.08s; `worker-pytest.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests` | PASS, 485 collected; `worker-inventory.log` |
| `uv run python -` importing the actual `failed_promotion_checks` evaluator and asserting duration/artifact failures for the four existing evidence JSON packs | PASS: all four rejected; `worker-evidence-audit.log` |

The five skips require `MAISTRO_TEST_PG_DSN` pointing at a migrated database;
no live PostgreSQL result is claimed. No new tests were added or changed, so no
inventory delta is required. The ASGI regression executes production limiter
instances and observes `[200, 200, 429]` independently on each replica for the
same identity (both authenticated and unauthenticated). This is meaningful
counterevidence to shared enforcement, not live multi-replica soak evidence.

### Acceptance accounting (all ten criteria)

1. **Representative profile — PARTIAL.** Profile exists, but its lines 152–166
   explicitly lack concurrent users/Workspaces, graph fan-out, successful
   tool/model calls, Design/Canvas and background/Goal workloads. Applicability
   to the selected RC remains UNVERIFIED.
2. **Two application replicas — PARTIAL.** Executed production-stack contract
   tests pass; Compose defines two replicas. Live exact-RC execution UNVERIFIED.
3. **Sustained saturation/reclaim/retry/leak/restart observation — UNVERIFIED.**
   Audited packs fail duration. Round 6 records 90.43s versus 14,400s required
   (`m3a-round6-shakedown.json:221–224`).
4. **Physical-work uniqueness / Goal reconciliation — UNVERIFIED.** Historical
   schedule evidence is admission-only; the queued probe is cancelled without
   executing physical work. Unit admission/backpressure passes do not close it.
5. **Concurrent security/degraded enforcement without replica bypass — NOT MET.**
   Production `rate_limit.py:25–30,73–78` explicitly implements independent
   allowances; executed regression `test_replica_selection_has_an_independent_production_allowance`
   reproduces another allowance on replica 2. Other RC security/degraded paths
   remain UNVERIFIED under sustained load.
6. **Complete telemetry and explicit thresholds — PARTIAL.** Existing profile
   specifies some thresholds. Application event-loop lag, complete worker
   census, long-window pool/lock/queue/error observations remain UNVERIFIED.
   Process-group sampler regression passed, but historical wrapper-only RSS/FD
   measurements cannot prove application leak freedom.
7. **Kill/restart active-work drain/fencing/recovery — UNVERIFIED.** Historical
   process exit/rejoin is not correlated physical Attempt recovery evidence.
8. **Long-running exact RC artifact/configuration soak — NOT MET.** All four
   historical packs fail current duration/artifact gates. The host driver returns
   `exact_rc_artifact.ok=false` (`scripts/soak/run_soak.py:635–645`). No exact RC
   image digest/configuration was assigned; Docker daemon is unreachable.
9. **Load findings classified/filed before promotion — PARTIAL.** Existing F1–F12
   evidence records local findings and milestone attribution; external filing
   UNVERIFIED. GitHub mutations are prohibited; none performed.
10. **Hash-bound machine/human soak evidence — PARTIAL.** Existing JSON and
    narrative were inspected and rejected by the actual promotion evaluator.
    Qualifying exact-RC evidence remains UNVERIFIED; no fresh soak is claimed.

### Disposition and next action

**BLOCKED**, not merge-ready. The requested CI failure did not reproduce, and
historical evidence misstatements cited by the assignment were already repaired.
Do not amend a passing ledger, invent a cluster-wide limiter in this lane, or
relax the promotion gate. Only this preserved checkpoint/report changed in this
round; source, tests, runtime config, ledger, and historical evidence are intact.

Owner handoff: provide the immutable RC image/configuration and reachable Docker
infrastructure; resolve the rate-limit acceptance/deployment mismatch and missing
representative workload/physical-fencing probes; then execute and publish a new
at-least-four-hour exact-RC soak. A longer host-emulator run cannot close #860.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0
assigned issues; errors 1 infrastructure probe (Docker unavailable). CI checks
passed; five database integration tests skipped. Local report commit required
before handoff; no remote mutations.
