# Issue #860 — bounded repair 99dc28bd

## Frozen scope

- Worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `084533b81041fd5a4dc97c149e4040409dfdb38d`; supplied develop
  base `e1b13dcd15dedd637404c38dfe1900921aba2b8c` resolves locally.
- One issue only: #860. No remote mutations or integration approval.
- Starting worktree clean; no incoming uncommitted work to salvage.
- Process the supplied schema-fence failure, required exact Vulture scan, and
  existing soak acceptance checks. Candidate edits limited to
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `quality/vulture-baseline.json` (only reviewed scan findings), this report,
  and `docs/testing/inventory-notes/m3a-860-99dc28bd-repair.md` if tests change.
  Adjacent production/tests/docs are read-only evidence.
- No check-*.log files present in this job directory at start. Supplied prior
  check-3.log reports schema-fence body length 24 versus 21 expected statements.
- Ambiguity: dispatch calls this a repair despite prior BLOCKED acceptance.
  Proceed with evidence-based CI repair, independently assess acceptance, and
  retain BLOCKED if no exact promoted RC/configuration is available.

## Progress

- Supplied schema failure is stale at the assigned HEAD: executed current
  `test_pg_learnings.py` passes (37 passed, 6 skipped). The independent ordered
  DDL assertion already includes the three Gauntlet audit columns at lines
  175–177. No repair to working production code or tests is justified.
- Required exact Vulture scan passes: 1332 reviewed identities / 1332 findings,
  zero unclassified or forbidden. No ledger amendment is justified.
- Current job logs: `worker-schema.log`, `worker-vulture.log`.
- Existing profile and promotion tests explicitly distinguish host preflight
  from exact-artifact promotion. Continue focused checks, not speculative edits.
- Supplied develop is not an ancestor of HEAD; merge base resolves to
  `1df433bf5ece482eac97c2966620fe43bc557af9`. No merge conflict is present and
  no develop-sync repair was requested by the prior BLOCKED result. Preserve
  existing branch history; do not treat its broad two-tree diff as new work.

## Architecture reconciliation

Read accepted ADR-081226-69ee (Graph/NodeRun/Attempt), ADR-081626-f383
(Attempt fencing), ADR-082526-b36a (lease renewal/reclamation),
ADR-082826-08f0 (recovery dispositions), and ADR-085 (principal-keyed limits).
The later recovery contracts govern over the earlier fencing ADR's historical
statement that takeover is undefined: restart does not permit stealing a live
lease, and recovery must use the canonical lifecycle. No alternate scheduler,
Goal store, event authority, or authorization path is introduced.

ADR-081 is **Proposed**, not accepted; its topology prose cannot waive issue
acceptance. The actual Compose reference defines two server replicas at
`deploy/docker-compose.prod.yml:26-76`. It is not itself a designated immutable
RC. ADR-085 requires principal-keyed limits but does not specify the distributed
storage implementation. Existing process-local semantics are documented at
`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30`; reconciling
those semantics with #860's non-bypass criterion needs an explicit production
contract, not an invented second authorization path.

## Executed validation

Commands used `uv run` with 1000–1200 second tool timeouts. Logs are under
`/home/dev/maistro/jobs/99dc28bdb6134b35b63412fc5114b796/`.

| Command | Outcome / log |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; `worker-schema.log` |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1332 identities; `worker-vulture.log`; matches quality workflow lines 1013–1016 |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 104 passed; `worker-focused.log` |
| `uv run ruff check .` | PASS; `worker-ruff.log` |
| `uv run ruff format --check .` | PASS, 3105 files; `worker-format.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 28182 unique identities; `worker-inventory.log` |
| `uv run python scripts/check-backlog-consistency.py` | PASS; `worker-backlog.log` |
| `uv run python -` (current soak evaluator imported with importlib) | Asserted historical round-6 evidence fails duration and exact-artifact gates; `worker-acceptance.json` |
| `git diff --check` | PASS |

The evaluator check loaded `evidence/m3a-round6-shakedown.json`, called
`failed_promotion_checks`, and asserted both `sustain_duration` and
`exact_rc_artifact` were failures. Observed duration is 90.43 seconds versus
14400 required. It also asserted `preflight_artifact_check()['ok'] is False`.
This is validation of preserved evidence, **not a new live soak**.

## Acceptance disposition

| #860 criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md:153-172` explicitly lists missing users/Workspaces, fan-out, successful model/tool and Design/Canvas/background traffic. No immutable promotion artifact/configuration designated in the assignment. |
| At least two application replicas | UNVERIFIED live. Compose defines two; executed middleware tests use two ASGI instances, not production containers. |
| Sustained saturation, growth, reclaim, retry and leak observation | UNVERIFIED. Re-evaluated evidence lasts 90.43 seconds; no sustained production workload executed this round. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED. Admission-probe tests pass but do not establish physical execution. Profile lines 195–204 acknowledge a single schedule race followed by cancellation without execution. |
| Security/degraded/rate limiting cannot be bypassed by replica choice | NOT MET for a shared principal allowance. Executed `test_soak_promotion_gates.py:439-488` exercises real middleware with identical principal/IP on both instances: each returns `[200, 200, 429]`. Other security/degraded behavior under sustained load remains UNVERIFIED. |
| Complete telemetry with explicit thresholds | UNVERIFIED. Sampler tests pass; no current production observations. Profile lines 153–172 acknowledge driver versus application loop latency and remaining worker/pool/reclaim gaps. |
| Kill/restart during active work; drain/fencing/recovery | UNVERIFIED. Boot cleanup tests pass, but no active-Attempt interruption experiment was run. |
| Long-running exact RC/configuration soak | NOT MET by evaluated evidence. Both duration and artifact gates fail. Driver at `scripts/soak/run_soak.py:730-741` unconditionally declares host preflight, never exact production Compose artifact. |
| Findings filed/reclassified before promotion | UNVERIFIED. Local findings recorded here; backlog consistency does not establish filing completeness. No GitHub mutation permitted or performed. |
| Hash-bound machine/human production evidence | UNVERIFIED. Historical artifacts and this validation report cannot certify an unselected RC. |

## Handoff

**BLOCKED** on production acceptance; neither supplied CI finding currently
requires repair. Only this report changed. No code, test, inventory, ledger, or
grant edits are justified by executed checks. No tests added, so no inventory
note is required. Existing work is preserved; no live deployment was started.

Next: designate the immutable RC/configuration and representative workload,
resolve aggregate rate-limit semantics, then run at least four hours against
that exact production topology with physical-work/recovery oracles and complete
telemetry. Do not redispatch the stale 21-versus-24 schema assertion as a repair.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC production
acceptance prerequisites}. Validation handoff complete, issue acceptance not
complete; local commit required, never integration approval.
