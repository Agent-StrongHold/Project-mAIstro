# Issue #860 repair — ce66fe93

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `10780e5413e038e36f206150d9909237868e9dac`, assigned base
  `68079320f8df9bdad827467490c0735dde7c03c1`.
- Initial worktree clean; no incoming uncommitted work to salvage.
- Inspect existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, `m3a-soak-evidence.md`, the four
  historical JSON evidence packs, adjacent production rate-limit/task/persistence
  code and tests, relevant deployment/execution/rate-limit ADRs.
- Execute required vulture per-identity check. Amend
  `quality/vulture-baseline.json` only for actual reviewed findings if any;
  no speculative gate or unrelated runtime changes.
- Output file: this note. Test additions, if needed, require an inventory note.
- Ambiguity: prompt includes both verifier and writer instructions. Assigned
  repair and mandatory local commit identify this as the writer lane.
- Job directory had no `check-*.log` files at initial inspection. Previous
  result is context only, not fresh acceptance evidence.

## Progress

- Required vulture check executed successfully: 1372 findings / 1372 reviewed
  identities, unclassified=0, never_allowlist=0. No unbanked identities or removed
  identities were reported; no ledger amendment is justified.
- Existing profile and summary already retract shared-limiter and exact-artifact
  claims. The prior wording defect does not reproduce. No cosmetic rewrite.
- Existing production middleware regressions assert a fresh allowance per replica;
  these need fresh execution, not reinterpretation as cluster-wide enforcement.
- No immutable RC image/configuration is identified in the assignment. Assume no
  authority to designate a different artifact as the #89 candidate. The host
  preflight explicitly cannot qualify even at four hours. Remaining acceptance
  must be recorded honestly rather than manufacturing promotion evidence.
- Fresh validation: `uv run ruff check .` PASS; `uv run ruff format --check .`
  PASS (2712 files); targeted pytest (command below) 88 passed, 5 skipped in
  10.83s. Skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL proof claimed.
- Architecture reconciliation: accepted ADR-081426-1f7c makes physical execution
  identity the Attempt ID, ADR-081626-f383 makes the canonical Run store the lease
  authority, and ADR-082126-f69c rejects a second scheduler/runtime. Admission
  deduplication is not physical-work deduplication. Accepted ADR-085 requires
  principal-keyed rates but does not establish shared counters. ADR-081 remains
  Proposed. No competing execution or authorization authority introduced.

## Executed commands

All validation used 600–1200-second tool timeouts; outcomes recorded from this
worker's tool output, not from absent driver logs.

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run ruff check .
uv run ruff format --check .
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs
```

The passing suite executes the real production middleware's independent-allowance
regression (both identity classes), the real task router with canonical in-memory
admission/backpressure, the schema-lock SQL-order test double, a live Linux child
resource sampler and production Compose contract tests. These are not a live
multi-replica RC soak. No tests changed; no inventory delta is required.

Additional executed checks:

- `uv run python scripts/check-compose-secrets.py`: PASS, eight tracked files.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS, 4320 cases.
- `uv run python -`: imported the current `failed_promotion_checks`, parsed the
  four frozen historical JSON packs and asserted each fails `sustain_duration`
  and `exact_rc_artifact`. PASS. Run 5 = 90.17s, run 6 = 90.43s, minimum 14400s;
  the earlier two packs omit top-level sustained duration. No raw pack modified.

Freshly computed SHA-256 identities (evidence files under `evidence/`):

| File | SHA-256 |
|---|---|
| `m3a-soak-evidence.json` | `f9a3e0f594188f3008ccd614b92bc02dfcdd26925122b41a1c12a369848241be` |
| `m3a-repair-validation.json` | `076cd80bd6e295ce99bb33f6045426a80f9ba68294d4f9be86549d3fdfb0fec5` |
| `m3a-round5-final.json` | `47fcdd3ddaad286d6498027af7b64f91bb89f35aa0c85ccac35e9b824791a89f` |
| `m3a-round6-shakedown.json` | `19813c32aa5229489cc44e52d9bf91b83906f176085b370815d3539d95cd880b` |

## Acceptance disposition

| Criterion | Fresh evidence / remaining requirement |
|---|---|
| Representative RC profile | PARTIAL: profile defines traffic and thresholds, but `m3a-load-profile.md:152` explicitly lacks multi-user/Workspace, graph fan-out, successful tool/model, Design/Canvas and Goal workloads. Representative completeness UNVERIFIED. |
| At least two application replicas | Compose defines two replicas; executed boot-contract tests pass. Live exact-RC multi-replica execution UNVERIFIED. |
| Sustained saturation, queue growth, lease reclaim, retries, leaks and shutdown | All four historical packs rejected by current duration gate. Long-window observations UNVERIFIED. |
| No duplicate physical work across replicas | Admission probe tests pass, but do not execute physical Attempts. `m3a-load-profile.md:196` states the scheduled probe Run is cancelled without execution. Physical-work and Goal reconciliation proof UNVERIFIED. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET: freshly executed production middleware test at `tests/test_soak_promotion_gates.py:480-486` demonstrates independent `[200,200,429]` allowances. Production installs this middleware at `packages/maistro-server/src/maistro_server/main.py:588`. Full concurrent security/degraded soak UNVERIFIED. |
| Complete telemetry with thresholds | Live child sampler regression passes; application event-loop latency, full worker census, sustained pool/query/lock/error telemetry UNVERIFIED. |
| Active-work kill/restart, drain/fencing/recovery | Historical process rejoin does not prove recovery of physical Attempts. UNVERIFIED. |
| Long-running exact RC artifact/configuration | Current runtime output unconditionally records failed artifact check at `scripts/soak/run_soak.py:1465`; all four packs also fail duration. UNVERIFIED. |
| Findings filed/reclassified before promotion | Existing local F1–F12 classifications preserved; no fresh load run/findings claimed. External filing UNVERIFIED (GitHub mutations prohibited). |
| Machine/human evidence tied to exact hashes | Historical pack hashes checked above; qualifying immutable image/config-bound RC soak evidence UNVERIFIED. |

## Handoff

**BLOCKED**. The explicitly requested CI failure does not reproduce; the earlier
H3 wording defect is already corrected. This round changes only this validation
report; runtime, configuration, tests, ledger/grants and historical evidence are
unchanged. No speculative repair or release certification.

Next owner must identify the immutable #89 RC image and frozen production
configuration/model gateway, resolve the rate-policy/non-bypass mismatch, supply
representative workloads and physical Attempt/fencing/recovery oracles with
complete telemetry, then run at least 14400 seconds on that exact artifact. Any
code/runtime-config change requires a fresh soak. A short host preflight cannot
resolve these blockers. Existing local findings require authorized external
triage before promotion.

Checkpoint: checked 1 assigned issue, done 0 acceptance-complete issues, skipped
0 assigned issues, errors 0 validation command failures. Validation/reporting
complete; acceptance blocked. Commit this report locally, without pushing.
