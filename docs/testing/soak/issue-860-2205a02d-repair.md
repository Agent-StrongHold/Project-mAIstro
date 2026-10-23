# Issue #860 — repair checkpoint (2205a02d)

## Frozen scope

- Issue: #860 only; branch `auto-860`, assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD verified: `f3ee435022bb15fcb3fbe44999641eef38c8e892`; worktree clean.
- Supplied base: `2779c99a72b464f9399306dfc40e6ce82a76b59e`.
- Process only the supplied dispatch snapshot; no remote mutations or new issue enumeration.
- Repair targets: exact vulture scan findings in `packages/*/src` and reviewed retained identities in `quality/vulture-baseline.json`; this report. Existing soak runner, tests, evidence, profile, relevant ADRs and CI scripts are inspection/validation inputs, not a new implementation campaign.
- Assumption: this is the writer CI-repair round explicitly permitting vulture ledger amendments. A ledger repair does not satisfy the multi-hour production soak acceptance criteria.
- Job directory contains no `check-*.log` files at initial inspection; run independent validation.

## Progress

The requested exact vulture scan executed successfully: 1,342 findings match
1,342 reviewed identities, zero unclassified and zero never-allowlist findings.
No unbanked identity exists to repair; changing code or the ledger would be
unsupported by this scan. The gate selected base `c560d4ccad82` (recorded as
reported, not confused with the supplied develop base).

Read the supplied issue body, latest captured comments, prior result, repository
instructions, existing load profile and promotion-gate tests. The previous
BLOCKED report is evidence to recheck, not an acceptance waiver. No tests or
production code have been changed; no inventory delta is needed.

## Executed validation

All commands ran in the assigned worktree with long timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0, exact CI arguments verified in `.github/workflows/vulture-ratchet.yml`.
- `git diff --check 2779c99a72b464f9399306dfc40e6ce82a76b59e...HEAD`: exit 0; supplied base resolves. Historical trailing-blank-line finding does not reproduce against this base.
- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0, 2,985 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 75 passed in 3.20 seconds. Includes real production middleware replica-selection counterexample, direct-replica probes, subprocess sampler, CLI artifact rejection and admission backpressure tests; not a deployed soak.
- `uv run python scripts/check-ratchet-provenance.py`: exit 0, 49 consumers have explicit provenance; delegated gates passed (existing syntax/CORS warnings only).
- `uv run python scripts/check-shipped-surface-truth.py`: exit 0.
- `uv run python -` independently imported the current runner and evaluated `evidence/m3a-round6-shakedown.json`: asserted failed checks exactly `['sustain_duration', 'exact_rc_artifact']`, observed duration 90.43 seconds, historical head `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`. Assertion command exited 0 because rejection was expected; this is a failed promotion evaluation, not a passing soak.
- `git diff --check`: exit 0; final status showed only this new report.

## Architecture reconciliation

Read accepted ADR-081226-a66b (canonical lifecycle) and ADR-081626-f383
(Attempt lease/fencing). No competing execution authority or scheduler is
introduced. Admission identity uniqueness is not physical-work uniqueness.
The accepted fencing ADR explicitly does not define lease-expiry takeover;
#860 cannot silently add such authority to make a soak pass. The profile cites
ADR-081, but its front matter is **Proposed**, not an accepted promotion waiver.
`deploy/docker-compose.prod.yml` is a two-server reference topology, not an
identified immutable release candidate. Its presence is not deployment proof.

## Acceptance recheck

| #860 criterion | Current evidence / result |
| --- | --- |
| Representative load profile | UNVERIFIED. Profile exists, but `m3a-load-profile.md:152-164` identifies missing users/Workspaces, Graph fan-out, successful tools/models, Canvas and Goal/background-worker workloads. |
| At least two application replicas | UNVERIFIED for the exact RC. Compose declares two servers; retained evidence is host-process preflight, not the Compose application artifact. |
| Sustained saturation, reclaim, retry and leak observations | UNVERIFIED. Retained shakedown is 90.43 seconds, not the required 14,400; no new live soak executed. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED. One schedule-admission race and terminal Run counts do not demonstrate physical Attempt fencing; profile lines 197-200 explicitly acknowledge this. |
| Security/degraded behavior and replica non-bypass | NOT MET for a cluster-wide allowance. Executed production middleware test gets `[200, 200, 429]` independently on both replicas for the same authenticated or pre-auth identity. Local semantics are intentional in `rate_limit.py:25-30`; they do not prove the stronger issue criterion. Other security/degraded tests pass locally, not under a sustained deployed workload. |
| Complete telemetry with thresholds | UNVERIFIED. Existing driver measurements and subprocess sampler tests cannot establish application-loop latency, worker counts or production leak behavior; profile lines 157-164 distinguish them. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED. Historical process exit/rejoin is not proof of no lost/duplicated physical work; no new active-work deployment fault injection. |
| Long-running exact RC artifact/config | NOT MET. `run_soak.py:635-646` always rejects its host-process topology; CLI tests confirm even four-hour synthetic evidence cannot override that check. |
| Findings classified to earliest milestone invariant | UNVERIFIED completeness. Existing findings are retained; this round makes no GitHub mutations and does not claim all load findings are dispositioned. |
| Machine/human evidence bound to exact current hashes | UNVERIFIED for current RC. Retained JSON names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head, and lacks promoted application-image identity. This report is validation evidence only. |

## Decision and handoff

The exact-debt-ledger repair has no reproducible failure and needs no ledger
amendment. Overall #860 remains **BLOCKED**, not merge-ready. Resolving the
promotion blocker requires an identified immutable RC/configuration, a runner
that actually exercises it, justified representative workloads and complete
telemetry, plus at least four hours of fresh load and physical-work recovery
observations. Re-running the host emulator cannot meet that prerequisite.
The rate-budget scope also needs explicit reconciliation with the issue's
non-bypass requirement, not a fabricated success or a weakened gate.

Checkpoint: checked 1 assigned issue, done 0 acceptance-complete issues,
skipped 0, validation errors 0; next: exact-RC production-soak prerequisites.
Only this report is changed in this round; existing source, tests and ledger
are preserved. Local commit required before handoff.
