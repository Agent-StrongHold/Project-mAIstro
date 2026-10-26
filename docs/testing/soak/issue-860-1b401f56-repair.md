# Issue #860 — repair checkpoint (job 1b401f56)

## Frozen scope

Only issue #860, branch `auto-860`, assigned worktree `/home/dev/Git/wt/auto-860`.
Starting HEAD verified as `79adeb9c246d51409ea21fe53bb329260fc76a9c`; base
`f5fa43771103d140c7d485959e914aa8fce33079`. Incoming worktree clean.
Review scope: existing `scripts/soak/run_soak.py`, its promotion tests,
`docs/testing/soak/{m3a-load-profile,m3a-soak-evidence}.md`, existing evidence,
production rate limiter/deployment configuration, and adjacent changed-package tests.
Write scope: this checkpoint; substantive repairs only if demonstrated by checks.
`quality/vulture-baseline.json` is conditionally in scope for the explicitly assigned
CI repair, but only if the required gate reports unbanked identities.

## Initial executed results

- Required vulture baseline command completed successfully: 1368 reviewed identities,
  1368 findings, zero unclassified / never-allowlist findings. No ledger amendment
  justified; do not fabricate debt changes.
- Job directory contains no `check-*.log` files at initial inspection. Driver checks
  are unavailable, not assumed green. Run relevant checks directly.

## Ambiguity and assumption

The prompt includes verifier and writer instructions; explicit lane assignment is
repair/writer, so focused repairs and a local commit are required. No RC image digest
or deployable RC configuration was supplied. Do not invent promotion evidence.

## Reviewed evidence and current blocker

- Independently executed `DOCKER_HOST=unix:///var/run/docker.sock docker info`:
  daemon unreachable (`Cannot connect to the Docker daemon`). Docker client exists,
  but this environment cannot currently execute the production Compose soak.
- Prior result artifact was read, not adopted as fresh validation. Its BLOCKED
  conclusion is consistent with the newly observed infrastructure failure.
- Existing H3 text already correctly disclaims shared-state/non-bypass evidence;
  the prior finding quoting a shared canonical limiter store is stale. Production
  `rate_limit.py:25-30` still explicitly implements independent replica budgets.
- Read repository AGENTS/CLAUDE and ADR-081 (Proposed), accepted lifecycle
  ADR-081226-a66b and accepted fencing ADR-081626-f383. Reconciliation: preserve
  canonical Goal -> Graph -> Run -> NodeRun -> Attempt. Admission uniqueness is
  not physical execution uniqueness; fencing ADR explicitly does not define
  lease-expiry takeover. Do not invent reclaim authority to satisfy this issue.
- Profile explicitly documents missing concurrent users/Workspaces, fan-out,
  successful providers, Design/Canvas, Goal reconciliation, application-loop
  measurements and physical fencing evidence. These remain blockers, not waived
  acceptance. Four-hour duration alone cannot promote the host preflight.

## Executed validation

All commands executed in the assigned worktree against the starting code.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1368 reviewed, 0 unclassified |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 2738 files |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 88 passed, 5 skipped; all skips require `MAISTRO_TEST_PG_DSN` |
| `uv run python scripts/check-deployment-claims.py` | PASS; component existence only, not live deployment |
| `uv run python scripts/check-execution-lifecycles.py` | PASS; 19 classified lifecycles |
| `uv run python scripts/check-merge-markers.py` | PASS |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info` | FAIL; daemon unreachable |

An inline `uv run python` probe loaded `scripts/soak/run_soak.py` with `runpy`
and applied `failed_promotion_checks` to the four frozen historical evidence
packs. Assertions that **both** `sustain_duration` and `exact_rc_artifact` fail
passed for every pack: `m3a-soak-evidence.json`, `m3a-repair-validation.json`,
`m3a-round5-final.json`, and `m3a-round6-shakedown.json`. Last two recorded
90.17 and 90.43 seconds respectively, not 14400. Raw evidence remains unchanged.

The executed regression `test_replica_selection_has_an_independent_production_allowance`
uses the real production middleware and observes `[200, 200, 429]` independently
on both instances for the same identity, for both authenticated and unauthenticated
cases. This falsifies cluster-wide non-bypass, not local limiter enforcement.
ASGI instances are not live application replicas or sustained concurrency evidence.

## Acceptance audit

| #860 criterion | Fresh validation and disposition |
| --- | --- |
| Representative profile | PARTIAL: profile inspected; concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal workloads explicitly missing. Exact RC applicability UNVERIFIED. |
| At least two application replicas | Compose declares both; boot-contract tests pass. Live exact-RC execution UNVERIFIED; Docker unavailable. |
| Sustained load observing saturation/reclaim/retry/leaks | UNVERIFIED; existing packs rejected by executed duration gate. Sampler subprocess regression passes but is not a long-window observation. |
| No duplicate physical work; reconciliation | UNVERIFIED; historical admission counts do not prove physical fencing, scheduled execution, or Goal reconciliation. |
| Security/rate/degraded behavior; replica-selection non-bypass | NOT MET for non-bypass: executed production-middleware regression demonstrates independent allowances. Sustained production security/degraded behavior UNVERIFIED. |
| Complete telemetry and explicit thresholds | PARTIAL: profile has thresholds, but application-loop/worker and full production observations remain UNVERIFIED. |
| Active-work kill/restart with drain/fencing/recovery | UNVERIFIED; process exit/rejoin in historical preflight cannot prove in-flight physical work preservation. |
| Long-running exact-RC soak; re-soak after changes | NOT MET: all four existing packs rejected; host preflight always rejects artifact gate (`run_soak.py:635-645`). No RC image/configuration supplied. |
| Findings filed/reclassified before promotion | PARTIAL: existing F1-F12 records inspected, including milestone classification; external filing UNVERIFIED and prohibited in this lane. |
| Machine/human evidence tied to exact artifact hashes | PARTIAL: historical packs present and reviewed; promotion-eligible artifact evidence UNVERIFIED. |

## Handoff / remaining work

Verdict: **BLOCKED**, not integration approval. No runtime, test, gate, ledger or
historical evidence edits. Only this validation handoff is added; no collection
change, so no inventory delta is needed. Existing meaningful regressions were run.

Required next inputs/work: restore Docker availability; supply the selected RC
image digests/configuration and provider setup; resolve the independent-limiter
acceptance mismatch with deployment owners; complete a representative exact-Compose
runner and physical-work/telemetry oracles; then execute at least four hours on
the frozen RC and publish hash-bound evidence. Do not rerun the host preflight and
call it promotion evidence. No scheduler, execution authority, event authority,
Goal store, authorization path, or reclaim contract was introduced.

Campaign checkpoint: checked 1 issue, done 0, skipped 0, errors 1 (Docker prerequisite);
CI-repair check complete with no unbanked identities. Next: operator/RC handoff above.
Local commit contains this report; no push or GitHub mutation performed.
