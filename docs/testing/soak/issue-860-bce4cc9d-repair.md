# Issue #860 — bce4cc9d CI repair checkpoint

## Frozen scope

- Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `6a46d5b43b50db4e10a5b969af799c7ac0811a95`.
- Supplied base: `b3662bb3719a0bd8d0285fe1515a7f1f39d34c8a`.
- Repair targets: actual identities reported by the mandated vulture scan,
  `quality/vulture-baseline.json` if reviewed retained debt requires amendment,
  and this evidence note. Adjacent source/tests and ADRs are inspection and
  validation scope; no new runtime authority or deployment claims are planned.
- Initial worktree clean; no uncommitted salvage needed.
- No `check-*.log` files in the supplied job directory at start.
- Prior result is BLOCKED, not acceptance evidence for this run.

## Assumptions and progress

The explicit CI-repair assignment permits vulture ledger amendments, but does
not authorize grants, weakened gates, or treating a short host-process preflight
as an exact-artifact RC soak. A four-hour soak of an unspecified RC cannot be
claimed from static/unit validation. Findings will be based on fresh commands.

The mandated command `uv run python scripts/check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exited 0:
1338 reviewed identities matched 1338 findings, zero unclassified and zero
never-allowlist findings. No dead-code or ledger repair is supported by this
scan, so no ledger amendment is justified. The scanner reports its default
comparison base as `94781cf6b708`, distinct from the supplied dispatch base;
this is not a claim of validation against that supplied base.

Fresh validation: `uv run ruff check .` passed; `uv run ruff format
--check .` passed (2920 files); `uv run pytest
tests/test_soak_promotion_gates.py -x -q` passed (52 tests). The supplied base
resolves, and `git diff --check
b3662bb3719a0bd8d0285fe1515a7f1f39d34c8a...HEAD` passed. Previously reported
trailing-blank failures are not reproduced against this assigned base.

The passing tests include counterexamples, not acceptance of cluster-wide
rate limiting: both authenticated and unauthenticated identities get fresh
allowances on a second production middleware instance. Production registers
that middleware in `packages/maistro-server/src/maistro_server/main.py:593`.

## Final validation

- `uv run pytest packages/maistro-server/tests -x -q`: 495 passed,
  8 skipped, 22 deprecation warnings. Skipped cases are not acceptance evidence.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- `uv run python scripts/check-suite-inventory.py`: passed, 14 suites,
  26020 unique collected identities. No tests changed or added; no inventory
  delta note is needed.
- Repeated the exact vulture command with
  `RATCHET_BASE_REV=b3662bb3719a0bd8d0285fe1515a7f1f39d34c8a`: passed;
  the provenance resolver still selected `94781cf6b708` as comparison base.
- Loaded `scripts/soak/run_soak.py` using `uv run python` and evaluated
  `docs/testing/soak/evidence/m3a-round6-shakedown.json` with the current
  `failed_promotion_checks`: failures are `sustain_duration` and
  `exact_rc_artifact`; recorded duration is 90.43 seconds. Current
  `preflight_artifact_check()` returns `ok: false` and
  `topology: host-uvicorn-preflight`.

## Architecture reconciliation

Read repository `AGENTS.md`, the documentation authority map, deployment
ADR-081, accepted lifecycle ADR-081226-a66b, and accepted lease/fencing
ADR-081626-f383. ADR-081 is **Proposed**, not an accepted authority overriding
the issue. Accepted lifecycle/fencing decisions retain canonical execution
ownership: Goal -> Graph -> Run -> NodeRun -> Attempt. No alternate scheduler,
authority, authentication path, or store is introduced. A count of admitted
Runs is not evidence of unique physical Attempt execution; neither unit tests
nor a short preflight waive the exact-artifact soak requirement.

## Acceptance audit

| #860 criterion | Fresh evidence / disposition |
|---|---|
| Representative users/Workspaces and workload profile | PARTIAL: `m3a-load-profile.md` defines a preflight mix but explicitly omits multi-user/Workspace, Graph/tool/Canvas and Goal workload coverage (lines 152-165). Complete RC profile UNVERIFIED. |
| Two application replicas | Existing direct-origin tests passed. Live exact-RC replicas UNVERIFIED; no live deployment run this round. |
| Sustained saturation, queue/reclaim/retry/leak observations | UNVERIFIED. Current evaluator rejects the 90.43-second historical evidence. |
| Schedule/task/Run/Attempt and Goal exactly-once physical work | Probe regression tests passed, but sustained production physical-work fencing and Goal reconciliation UNVERIFIED. |
| Security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared principal budget: both production-middleware identity cases reproduce `[200, 200, 429]` independently on each replica (`tests/test_soak_promotion_gates.py:439-488`). Local enforcement is not cluster-wide enforcement. |
| Required metrics with thresholds | Sampler and fail-closed measurement tests passed; complete RC telemetry, especially application-loop latency and worker counts, UNVERIFIED. |
| Kill/restart during active work proves fencing/recovery | UNVERIFIED; no live kill/restart under load performed. |
| Long-running exact RC artifact/configuration soak | NOT MET: `run_soak.py:635-647` rejects the host-process topology; historical evidence fails duration and artifact checks. |
| Findings filed/reclassified before promotion | Local backlog consistency passed; external filing/completeness UNVERIFIED. GitHub mutations prohibited. |
| Machine/human evidence bound to exact hashes | Historical pack evaluated and rejected; current RC hash-bound soak evidence UNVERIFIED. This note is validation evidence, not a soak pack. |

## Handoff

Outcome: **BLOCKED** on #860 acceptance, not on the vulture ledger. No
unsupported scanner repair or cosmetic runtime changes were made. Only this
note changes in this round. Existing tests meaningfully exercise the local
middleware, admission probes, process-group sampler and fail-closed evaluator;
they cannot substitute for sustained production execution.

Next prerequisite: an explicitly selected immutable RC image/configuration
and a production-topology runner covering the missing workloads and physical
fencing. Resolve the replica-selection budget mismatch through the canonical
security path, then execute and publish a fresh at-least-four-hour RC soak.
Do not repeat short host preflights as promotion evidence. No integration or
issue closure is authorized by this handoff.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0;
validation command failures 0; next is the blocked production-soak work above.
