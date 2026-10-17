# Issue #860 — befd670b repair validation and blocked handoff

## Frozen scope and reconciliation

- Only assigned item: #860 on `auto-860`, starting HEAD
  `118ebd85dda3d69666b82811357a6bbf36e72672`, base
  `4df9dd9bde4c6d03fccd1466cf9d6827a8fd4aa8`. Initial worktree was clean.
- Writer/CI-repair lane. Inspected the existing soak profile, evidence, runner,
  adjacent tests and production middleware; no GitHub mutations.
- No driver `check-*.log` files existed in the supplied job directory at start.
  Commands below were executed afresh, not inferred from prior claims.
  The supplied prior result was read and reports BLOCKED.
- ADR-085 is Accepted: limits are principal-keyed; it does not establish a shared
  counter. ADR-081 is Proposed, not an accepted waiver of deployment proof.
  Accepted ADR-081626-f383 places fencing authority in the canonical Run store.
  Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; admission counts and
  process rejoin cannot substitute for physical Attempt fencing/recovery proof.
- The prior shared-limiter wording finding no longer reproduces:
  `m3a-soak-evidence.md` now explicitly says state is process-local and identifies
  the replica-selection acceptance mismatch. No cosmetic rewrite is needed.

## Fresh validation

All commands used a timeout of at least 600 seconds. Logs are in
`/home/dev/maistro/jobs/befd670b12944ddaa54e2a85c83b7c45/`.

| Command | Executed outcome | Log |
|---|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1371 findings / 1371 reviewed identities; unclassified=0, never_allowlist=0 | `check-vulture.log` |
| `uv run ruff check .` | PASS | `check-ruff.log` |
| `uv run ruff format --check .` | PASS; 2720 files already formatted | `check-format.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | PASS; 88 passed, 5 skipped in 5.59s | `check-pytest.log` |
| `uv run python scripts/check-compose-secrets.py` | PASS; 8 tracked Compose files | `check-compose.log` |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS; 4320 cases | `check-inventory.log` |
| `uv run python -` (import current `failed_promotion_checks`, assert duration/artifact rejection, SHA-256 each frozen pack below) | PASS; all four packs rejected | `check-historical-packs.log` |
| `git diff --check` | PASS | terminal output |

Five PostgreSQL tests skipped because `MAISTRO_TEST_PG_DSN` was not configured;
no live database or production soak claim follows from this validation. The
vulture CI failure does not reproduce, so there are no measured unbanked identities
to amend. No runtime/configuration, ledger, grant, test or raw evidence changes.
No tests added; no test inventory delta required.

Historical evidence hashes freshly computed (these are not new soak results):

| Pack in `evidence/` | Sustained seconds | SHA-256 |
|---|---|---|
| `m3a-soak-evidence.json` | top-level field absent | `f9a3e0f594188f3008ccd614b92bc02dfcdd26925122b41a1c12a369848241be` |
| `m3a-repair-validation.json` | top-level field absent | `076cd80bd6e295ce99bb33f6045426a80f9ba68294d4f9be86549d3fdfb0fec5` |
| `m3a-round5-final.json` | 90.17 | `47fcdd3ddaad286d6498027af7b64f91bb89f35aa0c85ccac35e9b824791a89f` |
| `m3a-round6-shakedown.json` | 90.43 | `19813c32aa5229489cc44e52d9bf91b83906f176085b370815d3539d95cd880b` |

## Every acceptance criterion

| Criterion | Current evidence and disposition |
|---|---|
| Representative RC load profile | PARTIAL: `m3a-load-profile.md` specifies traffic/thresholds but explicitly lacks concurrent users/Workspaces, graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker workloads. Applicability to a selected RC remains UNVERIFIED. |
| At least two production replicas | Compose contract tests pass; `deploy/docker-compose.prod.yml:26,75` defines two replicas. Actual exact-RC multi-replica load execution UNVERIFIED. |
| Sustained saturation, growth, reclaim, retries, leaks, shutdown | Historical packs freshly fail `sustain_duration`; long-window observations UNVERIFIED. |
| No duplicate physical work; Goal reconciliation | Admission-oracle tests pass with mock HTTP receipts; backpressure test uses the real router and in-memory canonical spine without running physical work. The schedule preflight cancels its probe Run without execution. Physical-work uniqueness/reconciliation UNVERIFIED. |
| Rate/security/degraded non-bypass | NOT MET: `tests/test_soak_promotion_gates.py:480-486` executes real middleware and obtains `[200,200,429]` independently on each replica for the same identity (both authenticated and unauthenticated cases). Middleware is installed at `packages/maistro-server/src/maistro_server/main.py:588`; its documented scope is process-local (`api/rate_limit.py:25-30`). Full concurrent security/degraded behavior remains UNVERIFIED. |
| Complete telemetry with thresholds | Live Linux child-memory/descriptor sampler regression passes; this is not app-loop, container/worker census, pool saturation, query/lock, queue or long-window error evidence. Full telemetry acceptance UNVERIFIED. |
| Active-work replica kill/restart and drain/fencing/recovery | Historical process exit/rejoin cannot prove in-flight physical-work recovery. UNVERIFIED. |
| Long-running exact RC artifact/configuration soak | UNVERIFIED: current runner deliberately emits `exact_rc_artifact.ok=false` (`scripts/soak/run_soak.py:635-645,1465`). Existing packs fail both artifact and >=14400s duration gates. No immutable promotion image/configuration supplied. |
| Load findings filed/reclassified | Local F1–F12 records preserved; external filing UNVERIFIED. GitHub mutations prohibited in this lane. |
| Hash-tied machine/human evidence | Historical hashes verified above, human limitations preserved. Qualifying RC-image/config-bound soak evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not promotion-ready. This commit changes only this validation record;
it does not resolve the missing release experiment. Re-running the host preflight
for four hours would still fail the exact-artifact requirement.

Next owner must identify the immutable #89 RC image and frozen configuration,
resolve the replica rate-budget acceptance mismatch, complete representative
workloads and physical Attempt/recovery oracles plus telemetry, then run at least
14400 seconds on that exact topology. Any code/runtime-config change requires a
new soak. An authorized owner must triage/file the local findings before promotion.

Checkpoint: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0
assigned issues; errors 0 validation command failures. Local reporting is complete;
issue acceptance remains blocked. No push, PR, merge, or issue closure action.
