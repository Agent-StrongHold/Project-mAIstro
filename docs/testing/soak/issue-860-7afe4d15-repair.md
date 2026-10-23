# Issue #860 — repair checkpoint (job 7afe4d15)

## Frozen scope

- Assigned item: #860 only; branch `auto-860`, starting commit
  `84bf4f919257d4b7baf61d94a7c39214edf225b3`; provided base
  `a74a2b939a1eb4de1aaae505742a30e90f0d3f26` resolves locally.
- Initial worktree is clean; no incoming uncommitted work requires salvage.
- Inspect existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, `m3a-soak-evidence.md`, the four
  historical JSON evidence packs, production rate middleware and adjacent
  task/backpressure and PostgreSQL learning tests.
- Run the explicitly requested vulture baseline gate. Repair only evidenced
  unbanked/dead identities in its output; reviewed retained identities may be
  amended in `quality/vulture-baseline.json` under the lane's CI exception.
- Potential edits: the named harness/test/profile/evidence-summary files,
  vulture ledger if justified, this checkpoint and an inventory note if tests
  change. No unrelated branch-history deltas will be edited.
- No GitHub mutations, new execution authority, or changes to gate policy.

## Initial evidence and ambiguity

The previous job result is BLOCKED, but its validation is not assumed current.
This job directory contains no `check-*.log` files at initial inspection, so
there are no driver logs available to inspect. Run local validation instead.
The assignment identifies a repair/writer lane; proceed as writer despite the
prompt's generic verifier instructions. No exact RC image digest or promotion
configuration was supplied; do not invent one or label host-process shakedowns
as production promotion evidence.

## Fresh findings

- Requested vulture gate: **FAIL**, exit 1 (`worker-vulture.log` in the job
  directory). 1377 findings, zero unclassified/unreachable findings. Nine
  identities differ from trusted base `430139cb729e` (six relocated crypto API
  identities, lazy import hook, two Principal adapters); six old paths are absent.
  The output reports no candidate bookkeeping delta. The checker explicitly
  says candidate `--update` cannot authorize the trusted-base debt.
- Accepted ADRs read: runtime 081426-1f7c, fencing 081626-f383, recurrence
  082126-f69c, rate policy 085, quality provenance 083126-5e62. Deployment ADR-081
  remains Proposed. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt;
  admission/process rejoin are not physical-work/recovery evidence. No new
  execution or authorization authority is justified.
- The supplied obsolete H3 shared-store prose finding is not reproduced:
  `m3a-soak-evidence.md` already calls H3 partial and disclaims cluster-wide
  non-bypass. Production `rate_limit.py:25-30` still explicitly provides
  independent per-process allowances, so the acceptance mismatch remains.
- The checker automatically chose `430139cb729e`, not the supplied develop
  ref. Inspect provenance once to distinguish merge-base selection from missing
  candidate ledger banking; do not weaken or override the trusted-base gate.

## Validation results

All logs below are in job directory
`/home/dev/maistro/jobs/7afe4d150a2243489f540c514de282f9`.

- `uv run ruff check .`: PASS (`worker-ruff.log`).
- `uv run ruff format --check .`: PASS (`worker-format.log`).
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **88 passed, 5 skipped**, 13.79 seconds (`worker-pytest.log`). PostgreSQL
  integration skips are not database evidence. Real production middleware
  regressions prove separate allowances for authenticated and unauthenticated
  identities on two instances, not a deployed multi-replica soak. The sampler
  regression exercises an actual child process; the task router/backpressure
  test uses a real canonical admission spine but no physical runner.
- `uv run python scripts/check-compose-secrets.py`: PASS
  (`worker-compose-secrets.log`).
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS
  (`worker-inventory.log`). No tests changed, so no inventory delta is needed.
- Requested `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  FAIL as recorded above. Repeated with the **supplied resolved** base via
  `RATCHET_BASE_REV=a74a2b939a1eb4de1aaae505742a30e90f0d3f26`: same FAIL
  (`worker-vulture-assigned-base.log`). `git merge-base` of that base and HEAD
  is `430139cb729ec1bbf51a5e77ef602b8192f5d594`; provenance selection is
  explained, not an unresolved ref or a sync conflict. No fetch/merge performed.
- Direct `uv run python` invocation of `failed_promotion_checks` on the frozen
  four historical packs: PASS rejection assertions (`worker-evidence.log`).
  Every pack fails both `sustain_duration` and `exact_rc_artifact`. This is
  evidence validation, not another soak.

Commands used 600/1200-second tool timeouts. No production deployment or new
soak was launched: no immutable RC/configuration was supplied, and the existing
host-process driver explicitly cannot sign promotion at any duration.

## Ledger reconciliation

The lane authorizes candidate ledger repair, not trusted grant changes.
Inspection confirms the six relocated crypto identities plus Python's lazy
`__getattr__` export hook and two legacy Principal adapters are already in
`quality/vulture-baseline.json:500,956-963`; old crypto paths are absent.
These are retained compatibility/public APIs, not demonstrated dead work.
Deleting them or introducing artificial source callers to silence Vulture would
not be an evidence-based #860 repair. The scanner reports no candidate delta;
there is nothing left to amend in that ledger. The trusted-base gate still
requires a separately reviewed authorization. No gate, ledger, grant, runtime,
configuration or historical raw evidence was changed.

## Acceptance disposition

| # | Criterion | Fresh evidence / outstanding proof |
|---|---|---|
| 1 | Representative RC workload | PARTIAL: inspected profile defines mix/thresholds but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and sustained Goal reconciliation. Completeness UNVERIFIED. |
| 2 | At least two production application replicas | `deploy/docker-compose.prod.yml` declares two services; the existing driver boots host processes. Exact RC deployment UNVERIFIED. |
| 3 | Sustained saturation, growth, reclaim, retries, leaks, shutdown | All four historical durations rejected by executed gate; sustained RC behavior UNVERIFIED. |
| 4 | Schedule/task/Run/Attempt physical-work uniqueness and Goals | Admission-oracle tests passed; no physical Attempt/lease or Goal soak. UNVERIFIED. |
| 5 | Concurrent security/degraded behavior and replica-selection non-bypass | NOT MET: executed real-middleware regression shows each replica grants the same identity another allowance. `main.py:542` installs that middleware in production. Full security/degraded soak UNVERIFIED. |
| 6 | Complete telemetry with thresholds | Profile and real process-group sampler regression inspected/executed; application-loop, workers, pool saturation and sustained telemetry UNVERIFIED. |
| 7 | Active-work kill/restart, drain/fencing/recovery | Historical process exit/rejoin and terminal counts are insufficient; physical-work recovery UNVERIFIED. |
| 8 | Four-hour exact-RC artifact/configuration soak | Historical packs mechanically rejected; `run_soak.py:635-645` always fails exact-artifact gate. UNVERIFIED. |
| 9 | Findings filed/reclassified at earliest invariant | Existing local classifications preserved. External filing UNVERIFIED; GitHub mutations prohibited. No new load-discovered runtime defect in this round. |
| 10 | Hash-tied machine/human qualifying soak evidence | Historical packs preserved; fresh validation tied to the starting head. Qualifying RC soak evidence UNVERIFIED. |

## Final handoff

**BLOCKED.** Only this report changed; this local commit is a handoff, not
integration approval. The old prose and candidate-ledger repairs are already
present, so repeating them would be cosmetic and would not resolve the actual
blockers. The provided previous BLOCKED condition remains unresolved.

Next: trusted-base authorization requires its authorized owner; the release
owner must resolve the rate-limit acceptance mismatch, supply immutable RC
images/configuration, complete the representative production-topology runner
and execute >=14400 seconds with physical-work/recovery oracles and complete
telemetry. Do not run the preflight for four hours and relabel it as promotion
proof. Every code/runtime-config change requires a new RC soak.

Checkpoint: checked 1, done 0 (acceptance blocked), skipped 0, errors 1
(vulture trusted-base gate, reproduced with both default and assigned base).
