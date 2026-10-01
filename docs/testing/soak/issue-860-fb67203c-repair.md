# #860 — develop merge and exact-debt-ledger repair

## Scope and disposition

**BLOCKED; not promotion evidence.** Started at
`e2037399a1d4ad35ee2f69466e956cdc024ab60f` with an unfinished merge of
`430139cb729ec1bbf51a5e77ef602b8192f5d594`. Incoming staged and conflict diffs
were preserved outside the worktree in `../incoming-860-staged.patch` and
`../incoming-860.patch`. Read-only fetch confirmed origin/develop was that same
merge parent. Merge commit `47cc4fbb8` preserves both proxy protections:
no passive-health ejection for application 503s, and develop's 2-second connect
timeout / two upstream tries. All incoming staged changes were preserved.

Job: `/home/dev/maistro/jobs/fb67203c135f4f4e952863017178e156`.
No driver `check-*.log` files were present at the initial job-directory snapshot.
Prior green claims were not used as validation. New `worker-*.log` files there
record this round's actual checks.

## Reviewed ledger delta

The required Vulture scan found nine unbanked identities and six obsolete
entries after the merge. Only `quality/vulture-baseline.json` was amended:

- Move `DerivedKey.curve` and five `ConductorSeed` methods from `identity/__init__.py`
  to `identity/_crypto.py`. These are existing exported crypto APIs, not dead
  implementations; seed/lifecycle tests exercise restore, named derivation,
  DID encoding, mnemonic export, zeroization and curve selection.
- Retain `identity.__getattr__`: Python's lazy import hook keeps `Principal`
  importable without the optional crypto dependency. Extra-guard tests exercise
  this real import boundary.
- Retain `Principal.from_legacy_dict` and `to_legacy_dict`: explicit public
  migration adapters in the new canonical principal API. The import/fitness
  tests exercise `from_legacy_dict`; no production caller or direct test of
  `to_legacy_dict` was established here. It is retained as declared compatibility
  surface, not represented as production execution evidence.

No rule, whitelist, grant or gate was weakened. Candidate bookkeeping now
matches all 1377 findings, with no unclassified/unreachable finding. **The
trusted-base ratchet still fails**: develop's ledger has not authorized these
nine identity keys. This lane's permission to amend the candidate ledger does
not authorize a grant or changing the trusted base. Do not delete live public
APIs or insert fake callers to silence that result. Separate reviewed upstream
authorization/bookkeeping is required.

## Executed validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  **60 passed**. Includes the added production-proxy directive regression and
  actual production middleware counterexample to cluster-wide rate allowance.
- `uv run pytest packages/maistro-core/tests/identity packages/maistro-core/tests/fitness/test_principal_identity.py -x -q`:
  **72 passed**.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **28 passed, 5 skipped**. Skipped PostgreSQL integration legs are not live DB
  evidence; no database or load environment was started by this repair.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **FAIL**, trusted-base authorization only after candidate ledger repair.
- `uv run python scripts/check-compose-secrets.py`: PASS, eight Compose files.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS, 4326 tests.
- Direct `uv run python` invocation of `failed_promotion_checks` on the four
  frozen historical packs (`m3a-soak-evidence.json`, `m3a-repair-validation.json`,
  `m3a-round5-final.json`, `m3a-round6-shakedown.json`): all rejected for both
  duration and exact artifact. Assertions passed; last two observed durations
  are 90.17s and 90.43s, not 14400s.
- `git diff --check`: PASS.

## Acceptance disposition (all ten criteria)

| Criterion | Current executed evidence / limitation |
|---|---|
| Representative profile | PARTIAL: `m3a-load-profile.md` defines mix/thresholds but explicitly lacks multiple users/Workspaces, graph fan-out, successful model/tool work, Design/Canvas and sustained Goal reconciliation. UNVERIFIED as representative RC coverage. |
| Two deployed replicas | Historical host-uvicorn preflight only; no current production Compose replicas exercised. UNVERIFIED. |
| Sustained saturation/reclaim/backoff/leak observations | No new sustained run; old shakedown is 90.43s. UNVERIFIED. |
| No duplicate physical work | Admission oracle regression passes, not physical Attempt execution/reconciliation proof. UNVERIFIED. |
| Security/rate/degraded concurrency and replica-selection non-bypass | NOT MET: executed production limiter regression grants each replica a separate allowance to the same identity. Proxy regression preserves 503 semantics but is not a live concurrency test. |
| Complete telemetry and thresholds | Process-group sampler tests pass, but no application-loop/worker/pool/long-window RC telemetry was captured. UNVERIFIED. |
| Active-work kill/restart, fencing and recovery | Historical exit/rejoin is not physical-work recovery evidence; no new run. UNVERIFIED. |
| At least four hours of exact RC artifact/config | CLI regression rejects otherwise-passing four-hour host-preflight evidence; no qualifying Compose-artifact soak exists in the examined evidence packs. UNVERIFIED. |
| Findings filed/reclassified to earliest invariant | Existing F1–F12 local classifications inspected; external filing UNVERIFIED and prohibited in this lane. |
| Human/machine evidence tied to exact hashes | Historical packs preserved; no new qualifying RC artifact/config/commit evidence. UNVERIFIED. |

Accepted runtime/fencing/recurrence ADRs (081426-1f7c, 081626-f383,
082126-f69c) remain authoritative: a schedule admits canonical Runs, admission
uniqueness is not physical-work uniqueness, and no parallel scheduler or
execution authority was introduced. ADR-081 is Proposed, not an acceptance
waiver. Any merged runtime/config change invalidates earlier artifact soak
claims. The production RC must be selected and a representative four-hour
Compose-artifact run executed after the rate-limit contract mismatch is resolved.

## Handoff

Focused repair files: `deploy/nginx.conf` (merge resolution),
`tests/test_prod_stack_boot_contract.py`, `quality/vulture-baseline.json`,
`docs/testing/inventory-notes/m3a-860-develop-merge-policy.md`, and this report.
No new package runtime code, external issue mutation, or push was performed.
Item checkpoint: checked 1 (#860), done 0 (acceptance blocked), skipped 0,
errors 1 (trusted-base Vulture gate). Merge conflict and candidate-ledger
bookkeeping are repaired; next is authorized upstream ledger review plus RC
profile/artifact selection and real sustained acceptance execution. Neither
passing regressions nor this local handoff approves integration or promotion.
