# Issue #860 repair — db8066a3

## Frozen scope

- Assigned issue only: #860, branch `auto-860`, starting head `efd8cad0ea668a4b6ac2b8d1652777f1cc863946`, supplied base `a74a2b939a1eb4de1aaae505742a30e90f0d3f26`.
- Worktree was clean; no incoming changes to salvage.
- Inspect existing `scripts/soak/run_soak.py`, `scripts/soak/nginx-soak.conf`, `deploy/nginx.conf`, `docs/testing/soak/{m3a-load-profile.md,m3a-soak-evidence.md,evidence/}`, `tests/test_soak_promotion_gates.py`, adjacent changed persistence/API tests and production paths, repository instructions and relevant ADRs. Repair only evidence-backed defects in those paths, plus required inventory notes and reviewed `quality/vulture-baseline.json` identities if the required gate reports debt.
- No issue/PR enumeration, GitHub mutations, or integration approval.
- Scanner-derived review scope (required CI exception): `packages/maistro-core/src/maistro/identity/__init__.py`, removed `_crypto.py`/`principal.py` identities and adjacent `packages/maistro-core/tests/identity/test_seed.py`. `principal.py` was not found; source inspection skipped, obsolete ledger entries pruned per scanner evidence.

## Initial observations and assumptions

- Job directory contains no `check-*.log` files at initial inspection. Driver checks are therefore unavailable, not assumed green.
- Role is writer (assigned repair plus mandatory local commit), not read-only verifier.
- Existing short preflight evidence is not an exact-artifact four-hour soak. A fresh qualifying run is required to prove that acceptance criterion; no historical success will be inferred.

## Reviewed ledger repair

The six retained identities are the exported `ConductorSeed` methods `from_mnemonic`, `derive_named`, `did_key`, `mnemonic_words`, `zero`, plus `DerivedKey.curve`. Existing `test_seed.py` behavior checks mnemonic restoration, deterministic named derivation, curve selection, DID decoding and secret clearing. Their source definitions now live in `identity/__init__.py`; retaining this public capability is intentional. The removed lazy `__getattr__` and two Principal adapters no longer produce findings and their ledger entries are pruned. No source callers were fabricated and no rules, rationale, grants or checker code changed.

The initial exact replacement failed on whitespace without modifying the ledger; the corrected targeted edit succeeded. Only the six reported path relocations and three reported removals are intended.

No tests were added or changed: existing behavioral tests cover the retained APIs, and the exact-debt checker itself validates bookkeeping. No test-inventory delta is needed.

## Validation and outcome

- Required vulture command executed with a 1200-second timeout: FAIL (exit 1), log `worker-vulture.log` in the job directory. Unlike the prior job, current trusted base resolves to the supplied `a74a2b939a1e` and authorizes all 1373 findings. Actual candidate bookkeeping drift: six identities moved back from `identity/_crypto.py` to `identity/__init__.py`; three removed APIs remain in the ledger. Review and bank the reported identities, prune those absent, without editing policy or grants.
- Repaired vulture gate: PASS (exit 0), `worker-vulture-repaired.log`; this resolves the actual current CI failure, not the obsolete trusted-base blocker from the previous job.
- `uv run ruff check .` and `uv run ruff format --check .`: PASS, `worker-ruff.log` / `worker-format.log`.
- `uv run pytest packages/maistro-core/tests/identity/test_seed.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`: **110 passed, 5 skipped in 11.14s**, `worker-pytest.log`. All 22 seed tests ran. Five PostgreSQL integration cases skipped; no database-load proof is inferred. Task tests exercise canonical admission through the actual router, not a physical runner. The sampler regression measures a live child process. Production-middleware tests demonstrate an independent allowance on each instance for the same identity, not deployed cluster-wide limiting.
- `uv run python scripts/check-compose-secrets.py`: PASS (`worker-compose-secrets.log`).
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS (`worker-inventory.log`).
- `uv run python` evidence/ledger assertions: PASS (`worker-evidence.log`). All four frozen historical evidence packs fail both duration and exact-artifact checks. Exact JSON comparison proves only six identity relocations and three obsolete removals, leaving every other identity and policy field unchanged.
- Validation commands used 1200-second timeouts. Logs reside in `/home/dev/maistro/jobs/db8066a33f194c099aab7e77be9ada30/`. No production soak was launched: the provided reference Compose file requires external model gateway configuration and does not identify the immutable RC artifact/configuration selected for #89. Running the existing emulator longer would still fail the exact-artifact gate.
- Existing H3 evidence prose already disclaims shared limiter state; the old contradictory wording is not present. No cosmetic rewrite is needed.
- Accepted runtime/fencing/recurrence ADRs preserve canonical execution authority. Admission counts cannot establish physical-work fencing, and the load lane must not invent a reclaim/scheduler authority. ADR-085 requires per-principal rate policy but does not authorize pretending process-local counters are shared. Quality ADR-083126-5e62 distinguishes candidate bookkeeping from trusted authorization; only the explicitly permitted candidate ledger was amended. Deployment ADR-081 is Proposed, not authority to waive acceptance.

## Acceptance review

| # | Criterion | Executed evidence and disposition |
|---|---|---|
| 1 | Representative RC load profile | PARTIAL. `m3a-load-profile.md` defines mix/thresholds, but explicitly omits concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal reconciliation. Representative completeness UNVERIFIED. |
| 2 | Two supported production replicas | `deploy/docker-compose.prod.yml:25-81` declares two application services; boot-contract tests pass but do not deploy them. Exact-RC two-replica execution UNVERIFIED. |
| 3 | Sustained saturation, queues, leases, retries, leaks and shutdown | Historical packs fail current duration/artifact gates. No new sustained production traffic; UNVERIFIED. |
| 4 | Physical-work uniqueness, schedule/task/Run/Attempt admission, Goals | Admission oracle/backpressure tests pass; they neither execute physical Attempts across replicas nor reconcile Goals under load. Full criterion UNVERIFIED. |
| 5 | Concurrent security/degraded behavior, no replica-selection bypass | NOT MET: executed `test_replica_selection_has_an_independent_production_allowance` proves the same identity gets two allowances. `main.py:542` installs this process-local middleware. Full security/degraded soak UNVERIFIED. |
| 6 | Complete telemetry and explicit thresholds | Profile has partial thresholds; live-child sampler regression passes. Application-loop, worker census, pool saturation and long-window telemetry remain UNVERIFIED. |
| 7 | Kill/restart during active work, drain/fencing/recovery | Historical rejoin/terminal counts are not physical-work or stale-writer evidence. Active-work RC recovery UNVERIFIED. |
| 8 | >=4h exact RC artifact/configuration soak | All four historical packs rejected by executed `failed_promotion_checks`; round 6 records only 90.43s. `run_soak.py:635-645` explicitly rejects its host-process topology at any duration. UNVERIFIED. |
| 9 | Findings filed/reclassified at earliest broken invariant | Existing local F1–F12 classifications retained. External filing UNVERIFIED; GitHub mutations prohibited. No fresh load-discovered runtime finding claimed. |
| 10 | Hash-tied machine/human soak evidence | Historical packs preserved, not relabelled. This validation is tied to starting head plus the reviewed ledger diff; it is not a soak. Qualifying exact-RC evidence UNVERIFIED. |

## Final handoff

**BLOCKED for #860 promotion acceptance; the assigned vulture CI repair is complete.** Changed files: `quality/vulture-baseline.json` and this report only. No runtime, configuration, tests, gate policy, grants or raw historical evidence changed. `git diff --check` passed. The writer commit is a local handoff, never integration approval.

The prior trusted-base CI blocker does not reproduce at this head and is not carried forward as a risk. Remaining blockers require a release-owner-selected immutable RC image/configuration, a representative production-topology runner with physical-work/recovery oracles and full telemetry, resolution of the rate-limit non-bypass mismatch, and a new >=14400-second soak. Any code/runtime-config change requires another soak. Do not relabel a longer emulator run as exact-artifact proof.

Checkpoint: checked 1 assigned issue; done 1 CI repair; skipped 0 issues; errors 0 outstanding validation commands (initial vulture failure repaired). Acceptance remains blocked. Next: release-owner prerequisites and genuine RC soak, not further candidate ledger changes.
