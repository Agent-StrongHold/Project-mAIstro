# Issue #860 — ac7fa3bf repair checkpoint

## Frozen scope

- Issue #860 only; writer lane `auto-860`.
- Starting HEAD: `d63711ef7a762f0cd85bdd449aa631f23f7bcd71` (matches the exact
  assigned head). Supplied develop base: `a8258ee24dd957d0f0b302db4eee90661fe23439`.
- Worktree was clean at start; no incoming uncommitted work to salvage.
- Prior result artifact (`9fe10987…`, verdict BLOCKED) was read. Its five findings
  were each re-verified against this head instead of being assumed true.
- Job directory contains **no `check-*.log` files**; the driver's deterministic
  checks cannot be claimed, so all checks below were executed fresh.
- Planned edit surface: the EOF-whitespace defect reproduced below and this
  report. No tests added, no ledger, gates, thresholds, runtime or authorization
  changes.

## Reproduction and repair of prior findings

1. **EOF whitespace — reproduced and fixed.** `git diff --check 91996e1…HEAD`
   fails with `docs/testing/soak/issue-860-9fe10987-repair.md:107: new blank
   line at EOF`, introduced by this lane's own previous commit `d63711ef7`
   (the round had verified the three earlier instances fixed, then reintroduced
   the defect class in its report). The trailing blank line was removed this
   round; the three instances named in the prior finding
   (`issue-860-13ec34d7-repair.md`, `issue-860-62822668-repair.md`,
   `m3a-round16-handoff.md`) are confirmed fixed in the tree.
2. **Historical shakedown rejection — confirmed, not editable.** Fresh evaluator
   execution over `evidence/m3a-round6-shakedown.json` returns failed gates
   `['sustain_duration', 'exact_rc_artifact']`; the file records 90.43 observed
   seconds versus the 14,400-second minimum and `hashes.git_head =
   b31c5fdaa63b…`, which is not this lane's head `d63711ef7a76…`. The artifact
   honestly records its own insufficiency; rewriting evidence would be
   fabrication. The missing 4-hour exact-RC soak is the blocker, not the record.
3. **Host-preflight gate — confirmed deliberate.** `scripts/soak/run_soak.py`
   `preflight_artifact_check()` returns `ok: False` ("not the exact production
   Compose image and configuration") with no CLI override by design, and
   `exact_rc_artifact` is in the required gate list. Re-executed this round:
   `ok=False`.
4. **Replica-local rate budget — confirmed as documented implementation.**
   `packages/maistro-server/src/maistro_server/api/rate_limit.py` instantiates
   the process-local `InMemoryRateLimiter` and its docstring states each replica
   enforces independently (effective N-replica budget = N × configured limit).
   The counterexample regression
   `test_replica_selection_has_an_independent_production_allowance`
   (`tests/test_soak_promotion_gates.py`) passes at HEAD, reproducing
   `[200, 200, 429]` independently on two middleware instances for the same
   identity. #860's "cannot be bypassed by replica selection" acceptance is
   therefore demonstrated **not met**. Repairing it requires a coordinated
   store (product change) plus a fresh soak; out of scope for a repair round.
5. **Profile gaps — confirmed.** `m3a-load-profile.md` still lists multi-user/
   Workspace population, Graph/tool/Canvas fan-out, physical Attempt fencing,
   worker counts, pool saturation and application-loop latency as unverified
   blockers ("These are blockers, not acceptance waivers").

## Develop-sync decision

The branch is 215 commits ahead of and 9 behind `origin/develop`
(`a8258ee24…`). `git merge-tree` shows the merge would be textually clean
(0 conflicts), but the prior block was an acceptance blocker, not a develop
sync conflict, so the merge directive does not apply. The 9 develop commits
introduce the new gated `maistro-ext-sdk` package and CI-workflow changes
whose quality/suite baselines belong to the integrating merge, not to this
evidence-lane repair. **Merge skipped with rationale; divergence recorded.**

## Validation executed this round

- `git diff --check 91996e1…HEAD`: **PASS after the whitespace fix** (failed
  before it with exactly one finding, see above).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1,336 findings /
  1,336 reviewed identities, 0 unclassified, 0 never-allowlist. No ledger
  amendment is justified by any scan this round.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS.
- `uv run python scripts/check-suite-inventory.py`: PASS, 15 suites match; no
  test files changed, so no `docs/testing/inventory-notes/` delta is required.
- `uv run pytest tests/test_soak_promotion_gates.py -q`: **52 passed** (the only
  soak suite under `tests/`).
- Fresh evaluator run (above) rejects the round-6 artifact; compose config
  interpolation for `deploy/docker-compose.prod.yml` still fails on required
  `LITELLM_API_KEY` — no RC artifact/configuration is establishable here.

## Final acceptance review

| Issue acceptance | Executed evidence / remaining status |
| --- | --- |
| Representative RC load profile | UNVERIFIED: profile still omits multi-user/Workspace, Graph/tool/Canvas and sustained Goal workloads. |
| ≥ 2 application replicas on the supported topology | UNVERIFIED: compose config cannot interpolate (`LITELLM_API_KEY` missing); no deployed RC replicas exist here. |
| Sustained saturation/reclaim/retry/leak observation | UNVERIFIED: evaluator rejects the 90.43-second historical shakedown; no long production run exists. |
| Exactly-once/fenced physical work + Goal reconciliation | UNVERIFIED: admission probes do not observe physical work; sustained reconciliation absent. |
| Rate limiting not bypassable by replica selection | **Demonstrated not met**: counterexample test passes at HEAD against the production middleware; per-replica budgets are documented behavior. |
| Complete telemetry with explicit thresholds | UNVERIFIED: application-loop latency, worker counts, pool saturation remain absent from any current-RC evidence. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no current-RC restart probe evidence. |
| Long soak of the exact RC artifact/configuration | UNVERIFIED and blocked: no RC artifact selectable; host preflight is non-promotable by design. |
| Findings filed/reclassified to earliest invariant | Local F1–F12 classification exists; current filing status UNVERIFIED. No GitHub mutations performed. |
| Machine+human evidence tied to exact artifact hashes | Historical files exist but none tie to a promotable current RC artifact; UNVERIFIED. |

## Handoff

**BLOCKED**, not merge-ready. The only defect reproducible in this environment
(the reintroduced EOF whitespace) is fixed; every remaining blocker requires a
selected immutable RC artifact with reachable production configuration, real
deployed replicas, and a ≥ 4-hour soak — none of which this environment can
establish. Validation logs: `/tmp/issue-860-ac7fa3bf-*.log`.

Next: designate the RC image/config to promote, provision the gateway
credential, land a coordinated-store rate-limit design (new soak required after
any such change), then execute the sustained multi-replica soak with the
telemetry and fencing probes already instrumented in the driver.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped
0 issues; errors 0 implementation attempts. Environment blocker and acceptance
counterexample are recorded above. Local report commit is the handoff, not
integration approval.
