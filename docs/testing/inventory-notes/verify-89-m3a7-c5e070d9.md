---
inventory-delta:
  tests/: +1
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# verify-89-m3a7 — RC soak and byte-equivalent final promotion (#89)

Verification record for issue #89 (M3-A7, parent epic #19) at head
`c5e070d97d07800464972ee2c026a4d525ffbb21` (branch `auto-89`, tree clean, zero
lane commits, base identical). The job manifest carried `checks: []` — no
driver-executed check logs existed — so every check below was run by the
verifier at the exact head. Child soak lane `auto-860` (#860) was inspected
read-only at its tip `b26a6cd95e464dcb2c3092fa720c31127da82850`; none of that
work is merged into this head.

## Verifier-executed checks (all at c5e070d97)

- `uv run pytest tests/test_release_guard.py -q` — **23 passed** (162.20s):
  the static tag/version/ancestry guard machinery works in-tree.
- `uv run python scripts/check-release-consistency.py` — **exit 0**
  ("ok: released none, shipping 0.9.0, working toward 1.0.0").
- `git tag -l 'v*'` — **zero tags** repo-wide (no rcN, no final).
- `ls scripts/soak docs/testing/soak` — **both absent** at this head; the
  soak harness and evidence exist only on unmerged `auto-860`.
- `git rev-list --count origin/develop..auto-84|auto-86|auto-87|auto-88` —
  **0, 0, 0, 0**: all four dependency lanes of #89 are cut at the develop
  head with no implementation commits.

## Acceptance sweep (issue #89 snapshot → evidence at this head)

| # | Criterion | Disposition | Evidence |
|---|-----------|-------------|----------|
| 1 | RC artifacts built only from the candidate commit | UNVERIFIED | no RC tag exists (`git tag -l 'v*'` empty); `.github/workflows/release.yml:23-27` self-declares "NOT YET EXERCISED … this workflow has never run" |
| 2 | Soak includes clean install, real-model execution, security hot path, backup/restore | UNVERIFIED | no soak evidence at this head; even the `auto-860` profile excludes it by design — `docs/testing/soak/m3a-load-profile.md:67` "task execution fails fast against the absent [provider]", `:146` "Model/provider latency is not part of the profile (no LiteLLM in the soak)", `:152` no Graph fan-out / successful model calls; no clean-install or backup/restore phase exists in the profile |
| 3 | #860 exercises the exact RC under representative sustained multi-replica workload (crash/restart, admission/fencing, pool pressure, duplicate work) | **BLOCKED** (child lane's own gate) | `auto-860` tip checkpoint `b26a6cd95` "docs(soak): record 860 CI validation and unresolved RC blockers": fresh run failures are exactly `sustain_duration` (observed 90.43s vs `--sustain-seconds 14400` minimum, `m3a-load-profile.md:126-127`) and `exact_rc_artifact` (`scripts/soak/run_soak.py:1409` — no designated immutable RC image/config exists); cluster-wide rate-limit non-bypass NOT MET (production `RateLimitMiddleware` builds per-instance `InMemoryRateLimiter`); F7 concurrent-boot `CREATE INDEX` race (pg18) must be fixed before the promotion soak |
| 4 | Load/concurrency findings invalidating earlier invariants filed/reclassified before promotion | PARTIAL | F1-F10 classification + handoff retained on `auto-860` (`docs/testing/soak/m3a-ci-repair-handoff.md`), but external filing is outside lane authority and promotion has not occurred |
| 5 | Any code/runtime-config change forces a new RC + new soak evidence | UNVERIFIED | no RC exists to version; no enforcement surface for this rule at this head beyond the static guard (`scripts/release_guard.py:162`) |
| 6 | Final tag/tree byte-equivalent to the soaked RC tree | **FAIL** | zero tags repo-wide; the rc→final promotion path has never been executed (the L7 sweep note recording the same disposition, `verify-m3-afb075be.md`, exists only on sibling lane branch `auto-7` at `df227b0f2`, not merged into this head) |
| 7 | External package/image/signature/install verification succeeds | **FAIL** | `release.yml` never ran; ADR-073126-c4e1 "Implementation status": PyPI trusted publisher not registered, `release` environment not configured |
| 8 | Machine-readable soak evidence tied to the exact promoted artifact/configuration | **FAIL** | evidence exists only on unmerged `auto-860` and its own `exact_rc_artifact` gate is false (`run_soak.py:1409`); no evidence file at this head |

Tally: 0 PASS, 1 PARTIAL, 3 UNVERIFIED, 3 FAIL, 1 BLOCKED.

## Verdict rationale (BLOCKED)

Issue #89 is the promotion milestone: it can only be satisfied after its child
#860 executes a ≥4-hour soak of a *designated immutable RC* and after the
release workflow is actually exercised (tag cut, workflow run, environment
approval, final tag). None of those prerequisites exist:

1. The soak lane itself terminated BLOCKED with explicit cross-lane
   prerequisites (RC image/config designation; cluster rate-limit semantics
   with the deployment/security lane; F7 production fix) and the recorded
   conclusion that "another emulator shakedown cannot unblock acceptance".
2. All four dependency lanes (#84, #86, #87, #88) contain zero commits.
3. The promotion actions (tag push, merge to `main`, `release` environment
   approval) are GitHub mutations that lanes are prohibited from performing,
   and the promotion gate itself requires the workflow's first-ever real run.

No repair inside this lane can close program-scale absence; the gap requires
program-level RC designation and cross-lane sequencing before any promotion
soak can start. Static in-tree release machinery (release_guard, release
consistency) is healthy and is not the blocker.

Progress: `{checked: 8, done: 0, skipped: 0, errors: 0, next: program-level RC designation → #860 exact-RC 4h soak → exercised release pipeline}`.

## Re-verification addendum — 2026-10-18 round 2 (job `36d3131d`)

Prior block (gh API rate-limit during preflight) resolved read-only: all child/
sibling evidence below came from the frozen `dispatch-context.json` (captured
17:38:10Z, `complete_for_scope: true`) and local git, zero live API calls. Job
directory again carries no `check-*.log` files (`manifest.json` `checks: []`).

Fresh checks executed at `fc8f78278` (identical tree to `c5e070d97` plus this
note; earlier claims re-proven, not assumed):

- `uv run pytest tests/test_release_guard.py -q` → **23 passed** (0.84s).
- `uv run python scripts/check-release-consistency.py` → **exit 0**
  ("ok: released none, shipping 0.9.0, working toward 1.0.0").
- `git tag -l 'v*'` → **0 tags**; `scripts/soak` and `docs/testing/soak` →
  **still absent** at this head; `.github/workflows/release.yml:23-24` → still
  self-declares "NOT YET EXERCISED … this workflow has never run".
- Citation repair: criterion 6 previously cited `verify-m3-afb075be.md` as if
  in-tree; that note exists only on `auto-7` (`df227b0f2`). Citation fixed above;
  the primary evidence (zero tags) was always local and unchanged.

Movement since round 1 (vs `origin/develop` `f72d4fc92`, 391 commits past base):
auto-86 now **+1** (`63fcc1fc2`), auto-87 **+6** (`0daad820d`), auto-84 and
auto-88 **still 0** — none merged to develop, so #84/#88 prerequisites remain
unproven and #86/#87 work is not in any shipping tree.

Child lane `auto-860` moved to tip **`9a243fc61`** (2026-10-18). Its own fresh
acceptance matrix (`docs/testing/soak/issue-860-8d50e6eb-repair.md`, committed
12:28:55 -0500) records **BLOCKED, not merge-ready**: evaluated round-30 soak
**420.08s vs 14400s minimum**, `exact_rc_artifact` **NOT MET** (round-30 hash ≠
assigned HEAD; `scripts/soak/run_soak.py:744-755` deliberately cannot certify
Compose artifact identity; no immutable RC/config manifest supplied),
replica-selection rate-limit bypass **NOT PROVEN** (`rate_limit.py:32-37`
documents N-times aggregate allowance), and all other criteria UNVERIFIED for
the current RC. The #860 issue timeline shows three further repair attempts
today each stopping at a blocker (16:45Z, 17:09Z, 17:33Z) and explicitly rules
out another CI-only repair as a path to acceptance.

**Verdict unchanged: BLOCKED.** No criterion moved from FAIL/BLOCKED to PASS;
the promotion-scale gaps (no designated RC, no ≥4h exact-RC soak, no exercised
release pipeline, zero tags) are program-level and outside this lane's
authority. Round-2 tally: 0 PASS, 1 PARTIAL, 3 UNVERIFIED, 3 FAIL, 1 BLOCKED
(same as round 1).

Progress: `{checked: 8, done: 0, skipped: 0, errors: 0, next: program-level RC
designation and cross-lane sequencing; then #860 exact-RC ≥4h soak; then first
release-workflow run → rc→final promotion}`.

## Re-verification addendum — 2026-10-20 round 3 (job fe235b29548c)

Independent re-check at HEAD `877cf6b4c37132de3052c63a5c365196c2784e8b`
(branch `auto-89`, tree clean). No prior claim trusted — every check below was
re-executed in this worktree. No GitHub mutations performed (dispatch-context
consumed from the frozen snapshot at
`/home/dev/maistro/jobs/fe235b29548c49909a12c9079a92e2b2/dispatch-context.json`;
the prior `gh` preflight block was a rate-limit 403, not a code finding).

### Fresh deterministic checks (all re-run in this worktree)

| Check | Command | Result |
|---|---|---|
| Release consistency | `uv run python scripts/check-release-consistency.py` | exit 0 — "ok: released none, shipping 0.9.0, working toward 1.0.0" |
| Release guard | `uv run pytest tests/test_release_guard.py -q` | **23 passed** (0.91s) |
| Tags | `git tag -l 'v*'` | **0 tags** repo-wide (no rcN, no final) |
| Soak dirs | `ls scripts/soak docs/testing/soak` | **both absent** at this head |
| Promotion surface | `uv run python scripts/check-promotion-surface.py` | exit 0 — "promotion surface: ok" |
| Lint | `uv run ruff check .` | exit 0 — "All checks passed!" |

### Release workflow (read-only at this head)

`.github/workflows/release.yml` still self-declares at lines 23-24:
"NOT YET EXERCISED … this workflow has never run." The `guard → wheels →
pypi` / `images → github-release` job graph (ADR-073126-c4e1 §3-4) requires a
`v*` tag push and `release` environment approval — both are GitHub mutations
that this lane is hard-prohibited from performing. No candidate commit or RC
artifact manifest has been designated by the program.

### Dependency lanes (re-counted from origin/develop fad17a8)

| Lane | Tip now | vs develop now | vs round-2 note | Merged? |
|---|---|---|---|---|
| auto-84 | `c5e070d97` | 0 | 0 | n/a |
| auto-86 | `63fcc1fc2` | 1 | 1 | n/a |
| auto-87 | `0daad820d` | 6 | 6 | n/a |
| auto-88 | `e074a6212` | **11** | **0** | n/a |
| auto-860 (child soak) | `aa26df847` | 791 | 9a243fc61 | BLOCKED |

`auto-88` gained WIP + develop-merge commits since round 2 (WIP M2/M3/M5/M8
commits, none merged to `origin/develop`) but remains an unmerged WIP branch;
it does not satisfy #88's prerequisite for the #89 promotion pipeline.

`auto-860` (child #860) advanced from `9a243fc61` to `aa26df847` (2026-10-19
22:12). Its latest blocker docs —
`docs/testing/issue-860-8d2d6f26-validation.md` and
`docs/testing/issue-860-e5003c9da2b340609d82f635f50e929b-repair.md` — still
record **BLOCKED, not merge-ready**:

- `sustain_duration`: 420.08 s observed on the round-30 historical pack vs the
  14400 s floor (`m3a-load-profile.md:67` / `run_soak.py:1601-1602`); the floor
  exceeds the lane timeout (5400 s) with background execution prohibited —
  "no in-lane path" to the 4-hour sustained soak.
- `exact_rc_artifact`: **NOT MET** — `run_soak.py:744-755` cannot certify the
  Compose image/config identity; no immutable RC/config manifest supplied; RC
  regex sweep of #860/#89/#1672/#86 finds only prose criterion text.
- Rate-limit non-bypass: **NOT PROVEN** — component tests reproduce per-process
  `InMemoryRateLimiter` allowances (independent `[200,200,429]` per instance at
  `test_soak_promotion_gates.py:483-526`), not a deployed cluster-wide contract
  (`rate_limit.py:32-37` documents N-times aggregate allowance).
- All remaining criteria UNVERIFIED (no production deployment or soak).

Linked PR #1672 (head `148d5de8c390`, 2026-10-18 06:08) remains **DRAFT, open,
unmerged**. Parent issue #89 remains open, 0 comments updated.

### Acceptance sweep update (re-checked, not assumed)

No criterion moved from FAIL/BLOCKED to PASS since round 2. Round-3 tally:
0 PASS, 1 PARTIAL, 3 UNVERIFIED, 3 FAIL, 1 BLOCKED (identical to round 2).

The promotion-scale gaps are program-level and outside this lane's authority:
(1) no designated RC artifact/config, (2) no ≥4 h exact-RC soak (blocked on
sustain floor > lane timeout), (3) no first run of `release.yml` (requires tag
push + environment approval = GitHub mutations, prohibited), (4) external
provider keys / rate-limit ownership decisions out of lane scope. These are
not repairable by code or documentation within this worktree.

**Verdict unchanged: BLOCKED.**

Progress: `{checked: 8, done: 0, skipped: 0, errors: 0, next: program-level RC
designation and cross-lane sequencing; then #860 exact-RC ≥4h soak; then first
release-workflow run → rc→final promotion}`.

## Re-verification addendum — 2026-10-20 round 4 (job a3aefc85d1b54a55)

This is a clean retry of round 3 (job `fe235b29548c`): round-3's verification
was committed at `494c8929c` but that job failed to submit its
`MAISTRO_RESULT`, so this round re-runs the battery from scratch rather than
trusting round-3's claims. No prior commit trusted — every check below was
re-executed in this worktree at the identical code tree `c5e070d97` (round-3's
`494c8929c` adds only documentation to that tree). Working tree clean
(0 dirty files).

### Fresh deterministic checks (re-run in this worktree)

| Check | Command | Result |
|---|---|---|
| Release consistency | `uv run python scripts/check-release-consistency.py` | exit 0 — "ok: released none, shipping 0.9.0, working toward 1.0.0" |
| Release guard | `uv run pytest tests/test_release_guard.py -q` | **23 passed** (0.85s) |
| Tags | `git tag -l 'v*'` | **0 tags** repo-wide (no rcN, no final) |
| Soak dirs | `ls scripts/soak docs/testing/soak` | **both absent** at this head |
| Promotion surface | `uv run python scripts/check-promotion-surface.py` | exit 0 — "promotion surface: ok" |
| Lint | `uv run ruff check .` | exit 0 — "All checks passed!" |

All six reproduce round-3's results exactly at `494c8929c`. No claim is
assumed; each was re-executed here.

### Only deltas since round 3 (none change the verdict)

- `origin/develop` advanced `fad17a8 → e20e9f52e`; the in-lane
  dependency-count deltas among auto-84/86/87/88 are re-measured but none are
  merged into develop (auto-88 gained WIP M2/M3/M5/M8 commits, still an unmerged
  WIP branch; auto-86/auto-87 remain non-ancestors of develop). #89's
  prerequisites therefore remain unproven.
- Child soak lane `auto-860` advanced `aa26df847 → 37767efa3` (develop merge
  commit). Its own latest validation doc
  (`docs/testing/issue-860-8d2d6f26-validation.md`, and the 3b703b8ea
  "record issue 860 soak validation blocker" follow-up on its tip) still
  records **BLOCKED, not merge-ready**: `sustain_duration` 420.08 s vs 14400 s
  floor (floor > lane timeout, no in-lane path to ≥4 h), `exact_rc_artifact`
  NOT MET (`run_soak.py` host-process runner cannot certify Compose image/config
  identity; no immutable RC/config manifest supplied), rate-limit bypass NOT
  PROVEN (component tests show per-instance `[200,200,429]` allowances, not a
  cluster-wide contract).
- `release.yml` lines 23-24 still self-declare "NOT YET EXERCISED … never run",
  and ADR-073126-c4e1 "Implementation status" still shows PyPI trusted
  publisher **not registered** and `release` environment **not configured**.
- `git tag -l 'v*'` still 0; no RC artifact, no final tag.

### Verdict (re-affirmed)

No criterion moved from FAIL/BLOCKED to PASS since round 3. The promotion-scale
gaps — (1) no designated RC artifact/config, (2) no ≥4 h exact-RC soak (blocked
on the `sustain_duration` floor exceeding the lane timeout and on
`exact_rc_artifact` not being met), (3) no first run of `release.yml` (requires
a `v*` tag push + `release` environment approval, both GitHub mutations this lane
is prohibited from performing), (4) no machine-readable soak evidence tied to
an exact promoted artifact at this head — are program-level and outside this
lane's authority. They are not repairable by code or documentation within this
worktree. The static in-tree release machinery (release guard, release
consistency, promotion surface, ruff) is healthy and is not the blocker.

Tally: 0 PASS, 1 PARTIAL, 3 UNVERIFIED, 3 FAIL, 1 BLOCKED (unchanged since
round 1).

**Verdict: BLOCKED.** Prior round-3 non-submission was a result-emission
omission, not a code/evidence change; this round re-ran the full battery and
re-emits the same diagnosis.

## Re-verification addendum — 2026-10-23 round 5 (job `43373cf79`) + lane-rebuild repair

Round 5 started from rebuilt head `0408ea3c6` ("rebuild L89: re-apply orphaned
lane history onto develop (was `a30416f695`, root `b1c9eafb94`)"), whose
immediately preceding attempt (`3352f43c`) died on a provider 404 before doing
any work. Job `manifest.json` again carried `checks: []` — no driver-executed
check logs existed — so every check below was run in this worktree. All GitHub
evidence came from the frozen `dispatch-context.json` (captured
2026-10-23T23:19:10Z, `complete_for_scope: true`); zero live API calls and zero
GitHub mutations.

### Lane-rebuild integrity finding and in-place repair

The rebuild commit was not a faithful re-application. Forensics (all from
local git, tree clean at start):

- The orphaned lane chain (`fc8f78278` → `a30416f695`, four commits) touched
  exactly one file: this verify note (`git diff c5e070d97 a30416f695
  --name-status`). Its root `b1c9eafb94` dates to 2026-09-30 and shares **no
  merge base** with current develop — genuinely orphaned history.
- Canonical develop (`4de7e906d`, tip 2026-10-23) is **203 commits ahead** of
  that September-30 line (`git rev-list --count a30416f695..4de7e906d`).
- Yet `git diff --no-renames --name-status 4de7e906d 0408ea3c6` showed **441
  files** (436 M + 5 A, −26 164 lines) reverted toward the stale tree:
  `quality/ratchet-authorizations.json` halved 1774 → 879 lines,
  `tests/test_check_gates_ran.py` gutted (−272), CI workflows
  (`quality.yml` −442, `ci.yml` −126), `uv.lock`, migrations, and 5
  stale-tree files develop no longer has
  (`.github/workflows/stream1-diagnostic.yml`, `tests/api/test_health.py`,
  alembic `041_canonical_run_effect_claim` / `043_capability_invocation_effect_index` /
  `045_capability_invocation_logical_effect` — all present in the old lane
  tree, all absent from develop).

Repair (this round): each of the 441 paths was restored to its `4de7e906d`
state (5 stale additions removed); nothing else changed, and the note file was
kept byte-identical to `a30416f695` (verified: `git diff a30416f695 HEAD --
<note>` empty before edits). Post-repair parity check:
`git diff --cached --name-only 4de7e906d` == this note, nothing else. No
history rewritten, no refs deleted; the pre-repair tree remains reachable at
`0408ea3c6`.

### Fresh deterministic checks (repaired tree = develop + this note)

`uv sync --locked --extra dev` re-run against develop's lockfile first.

| Check | Command | Result |
|---|---|---|
| Release guard | `uv run pytest tests/test_release_guard.py -q` | **24 passed** (develop grew the suite 23 → 24) |
| Release consistency | `uv run python scripts/check-release-consistency.py` | exit 0 — "ok: released none, shipping 0.9.0, working toward 1.0.0" |
| Tags | `git tag -l 'v*'` | **0 tags** repo-wide (no rcN, no final) |
| Soak dirs | `ls scripts/soak docs/testing/soak` | **both absent** at develop |
| Promotion surface | `uv run python scripts/check-promotion-surface.py` | exit 0 — "promotion surface: ok" (74 tolerated modules) |
| Lint | `uv run ruff check .` | exit 0 — "All checks passed!" |

### Movement since round 4 (none favorable)

- `release.yml:23-24` still self-declares "NOT YET EXERCISED … this workflow
  has never run"; `ADR-073126-c4e1` §Implementation status (lines 146-166)
  still records PyPI trusted publisher **not registered**, `release`
  environment **not configured**, **no tags at all**.
- Child soak lane #860: last three progress markers (2026-10-23 08:04-08:28Z)
  are started → started → **blocked** (repair attempt `db2517ec` at head
  `78534b6e`). Its PR #1672 remains **open, DRAFT, unmerged** (base
  `develop`), and the frozen check-runs on that head include **failure**
  conclusions (Coverage gate, devskim).
- Dependency lanes vs develop `4de7e906d`: auto-86 **+1**, auto-88 **+297**
  (unmerged WIP); `origin/auto-84` / `origin/auto-87` have no local remote
  refs in this worktree (last measured 0 in rounds 3-4) — recorded as not
  locally resolvable, and in no case merged into develop.
- #89's own comment timeline (12 comments) contains only bot progress
  markers; latest state "failed" for the provider-404 attempt.

### Verdict (re-affirmed, round 5)

No criterion moved from FAIL/BLOCKED to PASS. Round-5 tally: 0 PASS,
1 PARTIAL, 3 UNVERIFIED, 3 FAIL, 1 BLOCKED — unchanged since round 1. The
promotion-scale gaps remain program-level and outside this lane's authority:
(1) no designated RC artifact/configuration, (2) no ≥4 h exact-RC soak (child
lane #860 last recorded BLOCKED on 2026-10-23 with `sustain_duration` floor
exceeding its lane timeout and `exact_rc_artifact` NOT MET), (3) no first run
of `release.yml` (requires a `v*` tag push + `release` environment approval —
GitHub mutations this lane is prohibited from performing), (4) no
machine-readable soak evidence tied to any promoted artifact at this head.
The static in-tree release machinery (release guard 24/24, release
consistency, promotion surface, ruff) is healthy on the repaired tree and is
not the blocker.

**Verdict: BLOCKED.**

Progress: `{checked: 8, done: 0, skipped: 0, errors: 0, next: program-level RC
designation and cross-lane sequencing; then #860 exact-RC ≥4h soak; then first
release-workflow run → rc→final promotion}`.

## Re-verification addendum — 2026-11-26 round 6 (job `e50016d67efb`) — in-lane RC-tree guard landed and validated

Round 6 started from head `6ff2cd32a8df9f33a2b02821825e1e7e0d5c906f` (branch
`auto-89`, tree clean), i.e. round 5's repaired tree plus one in-lane commit:
`fix(release): reject final source drift from latest RC (#89)`. The intervening
attempt (`8f98fc5ca`) produced exactly that commit before dying on a provider
usage-limit error, and this job's `manifest.json` again carried `checks: []` —
**no `check-*.log` files exist in the job directory** — so every check below
was re-executed in this worktree. All GitHub evidence came from the frozen
`dispatch-context.json` (captured 2026-11-26T15:19Z, `complete_for_scope:
true`); zero live API calls, zero GitHub mutations.

### The in-lane repair (commit `6ff2cd32a8`, now at lane head)

Acceptance criterion 6 ("final tag/tree is byte-equivalent to the soaked RC
tree") previously had **no enforcement surface**: nothing compared a final tag
to the RC that was soaked. The commit adds exactly that surface without
claiming it proves more than it does:

- `scripts/release_guard.py` gains `--verify-rc-tree`: for a final `vX.Y.Z`
  tag it selects the numerically **latest** `vX.Y.Z-rcN` (highest N, never an
  older candidate whose tree happens to match), requires the candidate to be
  an annotated tag, requires the checkout to equal the final tag's tree, and
  compares git **trees** (contents, paths, modes, submodule IDs) so a
  promotion merge may change the commit ID but not the soaked source. Fails
  closed on missing candidates, lightweight candidates, missing refs, and git
  errors; no metadata exception.
- `.github/workflows/release.yml` guard step now always passes
  `--verify-rc-tree` (full `fetch-depth: 0` checkout, no `continue-on-error`),
  so no final build/publish can skip it.
- `tests/test_release_guard.py` adds 11 cases on real temporary git repos
  (35 total in the file).
- `docs/testing/inventory-notes/issue-89-rc-tree-guard.md` records the delta
  (`tests/: +11`) and an honest criterion-by-criterion handoff.

### Fresh deterministic checks (all re-run at `6ff2cd32a8`)

| Check | Command | Result |
|---|---|---|
| Release guard suite | `uv run pytest tests/test_release_guard.py -q` | **35 passed** (0.95s) — 24 pre-existing + 11 new |
| Negative control (new tests bind to the fix) | new test file copied onto base `e0b427fefa` in a disposable scratch checkout at `/tmp/wt-neg89` | **11 failed, 24 passed** — every new test fails against the pre-fix tree (argparse rejects `--verify-rc-tree`; workflow lacks the flag); scratch removed after measurement |
| Lint | `uv run ruff check .` | exit 0 — "All checks passed!" |
| Format | `uv run ruff format --check .` | exit 0 — "3484 files already formatted" |
| Release consistency | `uv run python scripts/check-release-consistency.py` | exit 0 — "ok: released none, shipping 0.9.0, working toward 1.0.0" |
| Promotion surface | `uv run python scripts/check-promotion-surface.py` | exit 0 — "promotion surface: ok" |
| Suite inventory | `uv run python scripts/check-suite-inventory.py --suite tests/` | exit 0 — "ok: 1 suite(s) match the recorded inventory" |
| Tags | `git tag -l 'v*'` | **0 tags** repo-wide (no rcN, no final) |
| Soak dirs | `ls scripts/soak docs/testing/soak` | **both absent** at this head |

### Dependency/program movement since round 5 (mixed, none unblocking)

- **#88 closed** (2026-10-25): backup/restore acceptance is the first
  dependency of #89 to reach satisfied.
- **#84's verification exercise merged into develop** (`14cf1c935e`, PR
  #2514 — get.sh checksum verification, publish-metadata tests, verification
  doc) although the #84 issue itself remains open; it did **not** touch
  `release.yml`, `release_guard.py`, or `test_release_guard.py`.
- `origin/develop` advanced **189 commits** past the lane base `4de7e906d9`
  (now `7ba29c1cd`, this job's declared base). Of the files this lane's fix
  touches, only `release.yml` also changed on develop (DevSkim suppressions
  and action version pins in different hunks) — no content conflict on the
  guard surface, but the lane branch is not yet based on the current develop
  head and will need a sync before integration. The round's prior block was a
  provider error, not a sync conflict, so no merge was performed this round.
- **Child soak lane #860 / PR #1672**: still open and unmerged (head
  `edbc2f4e43f3`, no longer draft, `mergeable: true`). Last lane activity
  2026-11-17 ended **blocked**; frozen check-runs on that head: 44 success,
  1 **failure** (Quality / Documentation links), 31 pending, 3 skipped;
  `gates-ran` status pending. The exact-RC ≥4 h soak has still never run.
- #86 (clean-machine install) and #87 (real-model execution) remain open.

### Verdict (round 6)

The source-integrity criterion now has a tested, mandatory, production-wired
enforcement surface, and every gate passes at the lane head. But that surface
is **necessary, not sufficient**: as `issue-89-rc-tree-guard.md` itself
records, equal git trees do not prove artifact byte identity across rebuilds,
do not constitute soak evidence, and the promotion actions (RC tag cut,
`release.yml` first run, `release` environment approval, final tag) remain
GitHub mutations this lane is prohibited from performing. No RC exists; the
≥4 h exact-RC soak is still blocked in the child lane; soak directories remain
absent from every shipping tree. Round-6 tally vs the issue's eight criteria:
1 PARTIAL (upgraded from UNVERIFIED — RC-tree guard), 1 PARTIAL (new-RC-on-change
enforcement), 6 UNVERIFIED/FAIL/BLOCKED. **Verdict: BLOCKED**, unchanged in
kind since round 1, with one criterion materially hardened in-lane.

Progress: `{checked: 8, done: 1 (RC-tree drift guard), skipped: 0, errors: 0,
next: develop sync for lane branch → operator-designated immutable RC →
#860 exact-RC ≥4 h soak → first release-workflow run → external verification}`.

## Re-verification addendum — 2026-11-26 round 7 (job `fa9871ce55e4`) — battery re-proven, blockers unchanged

The immediately preceding attempt (job `43b97501ac53`) never started: the
provider rejected the configured model ("No API key found for moonshotai",
`agent_exit: 1`, `worker_error`), so it produced **zero** work — tree clean at
`3c4e0b4f9f`, nothing to salvage. This job's `manifest.json` again carries
`checks: []` and **no `check-*.log` files exist in the job directory**, so the
full battery was re-executed here at head `3c4e0b4f9f` (branch `auto-89`, tree
clean before this note). GitHub evidence is from the frozen
`dispatch-context.json` (captured 2026-11-26T16:08:16Z, `complete_for_scope:
true`, 35 sources); zero live API calls, zero GitHub mutations.

### Fresh deterministic checks (all re-run at `3c4e0b4f9f`)

| Check | Command | Result |
|---|---|---|
| Release guard suite | `uv run pytest tests/test_release_guard.py -q` | **35 passed** (1.01s) — includes the 11 RC-tree promotion cases and the workflow-wiring test asserting `--verify-rc-tree`, `fetch-depth: 0`, no `continue-on-error`, and `guard` in `wheels`/`images` needs |
| Suite inventory | `uv run python scripts/check-suite-inventory.py` (**CI's exact invocation**, `.github/workflows/ci.yml:719`, no args) | exit 0 — "ok: 21 suite(s) match the recorded inventory"; 34,136 collected node IDs, 0 duplicate identities, 0 byte-identical files |
| Release consistency | `uv run python scripts/check-release-consistency.py` | exit 0 — "ok: released none, shipping 0.9.0, working toward 1.0.0" |
| Lint | `uv run ruff check .` | exit 0 — "All checks passed!" |
| Format | `uv run ruff format --check .` | exit 0 — "3484 files already formatted" |
| Tags | `git tag -l 'v*'` | **0 tags** repo-wide (no rcN candidate, no final) |
| Tree | `git status --short` | clean (only this note added this round) |

### Program movement since round 6 (none unblocking)

- Child soak lane **#860 still open**; PR **#1672 open and unmerged** at
  `edbc2f4e43f3` (`mergeable_state: "blocked"`). Frozen check-runs on that
  head regressed/stalled vs round 6: now **75 success / 3 failure** ("Quality
  gate (Pillars 1–4, 7, 8)", "test failure", "Quality / Documentation links")
  / 3 skipped, and the `gates-ran` commit status is **pending** on all 4
  contexts. The exact-RC ≥4 h soak has still never run.
- Issue #89 carries no tracked sub-issues (`sub_issues: []`); #860 is linked
  only in the body, so its completion is not mechanically gated on the issue.
- Dependencies per round-6 record: #88 closed; #84/#86/#87 open.

### Verdict (round 7)

No in-lane engineering gap was found: the RC-tree promotion guard and its
tests pass every gate at the lane head, and nothing in this round's evidence
warrants a repair to committed code. All remaining acceptance criteria still
require release **operations** this lane is prohibited from performing: RC tag
designation, the #860 exact-RC sustained soak (its own PR is failing CI and
unmerged), the first real `release.yml` run with `release` environment
approval, and external package/image/signature/install verification. Tally
vs the issue's eight criteria is unchanged from round 6: 2 PARTIAL
(RC-tree guard; new-RC-on-change enforcement), 6 UNVERIFIED/FAIL/BLOCKED.
**Verdict: BLOCKED**, unchanged in kind since round 1.

Progress: `{checked: 8, done: 0 (no new repairable gap), skipped: 0, errors:
0, next: #860 CI repair + merge → operator-designated immutable RC/config →
exact-RC ≥4 h soak → exercised release pipeline → external verification}`.
## Re-verification + repair addendum — 2026-11-26 round 8 (job `da9e1dd77e0f4`)

Round 8 inherited two inputs: the implement round's promotion machinery at
`fc86f63873` (job `ea5c1ec3`, verdict MERGE-READY as a writer handoff) and a
**preserved develop-sync merge conflict** in `.github/workflows/release.yml`
(the previous round's block). This job's `manifest.json` again carries
`checks: []` — no `check-*.log` files exist — so every check below was
executed in this worktree. GitHub evidence is from the frozen
`dispatch-context.json` (captured 2026-11-26T17:59Z, `complete_for_scope:
true`, 35 sources); zero live API calls, zero GitHub mutations.

### Previous block resolved: develop sync (commits `2e66978455`, `b1b00ed2b6`)

The worktree arrived mid-merge (MERGE_HEAD `b6879c417f` = the develop tip the
merge was started from) with exactly one conflicted file, two identical-shaped
hunks: develop bumped `docker/build-push-action` `v7` → `v7.4.0` in the two
image-build steps; auto-89 had gated those same steps to candidates with
`if: needs.guard.outputs.prerelease == 'true'`. Resolution keeps both (gate +
pinned version). `origin/develop` advanced one commit past MERGE_HEAD during
the round (to `7926d9ab`, this lane's declared base: react-dom e2e bump), and
was merged cleanly on top. After both merges `git merge-base --is-ancestor
origin/develop HEAD` holds: the branch now contains the develop base. The
resolved `release.yml` parses as YAML, carries zero conflict markers, and the
promotion wiring test (`test_shipping_workflow_promotes_rc_artifacts_on_finals`)
passes unchanged — it asserts both build steps keep the candidate-only gate.

### Fresh deterministic checks (all at `b1b00ed2b6` + this round's repair)

Environment: `uv sync --locked --extra dev` re-run against the merged
lockfile before trusting any exit code (develop changed `uv.lock`).

| Check | Command | Result |
|---|---|---|
| Promotion + guard suites | `uv run pytest tests/test_promote_release.py tests/test_release_guard.py -q` | **83 passed** (82 prior + 1 new pin) |
| Lint | `uv run ruff check .` | exit 0 — "All checks passed!" |
| Format | `uv run ruff format --check .` | exit 0 — "3678 files already formatted" |
| Suite inventory | `uv run python scripts/check-suite-inventory.py` (**CI's exact invocation**) | exit 0 — "ok: 21 suite(s) match the recorded inventory" |
| Release consistency | `uv run python scripts/check-release-consistency.py` | exit 0 — "ok: released none, shipping 0.9.0, working toward 1.0.0" |
| Promotion surface | `uv run python scripts/check-promotion-surface.py` | exit 0 — "promotion surface: ok" |
| Image pins | `uv run python scripts/check-image-pins.py` | exit 0 — "11 pinned base/tool image(s) … all registered" |
| Image inventory | `uv run python scripts/check-image-inventory.py` | exit 0 — "every shipped image names live jobs" |
| Required checks | `uv run python scripts/check-required-checks.py` | exit 0 — "79 PR checks match docs/ci/REQUIRED-CHECKS.md" |
| Workflow lint | actionlint 1.7.7 + shellcheck 0.10.0, CI's exact invocation (`ci.yml:1717-1726`), binaries installed to /tmp the same way CI installs them | exit 0 over the whole workflows tree, incl. the conflict resolution |

### New finding + in-round repair: the soak-gate check set was adaptive, not pinned

Mutation experiment (disposable scratch checkout at the merged head, removed
afterwards): dropping `"multi_replica_soak"` from `REQUIRED_SOAK_CHECKS`
(`promote_release.py:139-145`) left **all 44 promotion tests passing** — both
`test_valid_evidence_passes`' helper and
`test_every_required_soak_check_gates_promotion` iterate the tuple
dynamically (`tests/test_promote_release.py:104,238`), so removing a required
check weakens the final-promotion gate invisibly. That is precisely the
regression issue #89's criteria 2-3 forbid (soak must include clean install,
real model, security hot path, backup/restore, and the #860 multi-replica
soak).

Repair (this round, `tests/test_promote_release.py`):
`test_required_soak_checks_are_pinned_not_adaptive` asserts the exact
five-element set with a diff in the failure message. Binding proven in the
mutated scratch: **1 failed, 44 passed** — the new test fails against
exactly the drift it names, everything else stays green.

### Acceptance status (unchanged in kind)

The in-lane engineering surface for byte-equivalent promotion is complete,
tested, and gate-clean, and the lane branch is now synced onto the declared
develop base. The issue's promotion-scale criteria remain outside lane
authority, unchanged since rounds 1-7: `git tag -l 'v*'` → **0 tags** (no RC
exists); `scripts/soak` / `docs/testing/soak` → **absent from this tree**;
`release.yml:23-27` still self-declares the workflow has never run; child
soak lane #860 / PR #1672 is open, unmerged, and per the frozen snapshot
carries failing check-runs on `edbc2f4e43f3`; the first real `release.yml`
run, the ≥4 h exact-RC soak, and external package/image/signature/install
verification are release operations lanes are prohibited from performing.

**Verdict: BLOCKED for issue acceptance** (program-level operations pending);
the lane's own deliverable — sync resolved, promotion machinery validated,
gate-pin repair landed — is handed off for integration review.

Progress: `{checked: 8, done: 2 (develop-sync resolution; soak-gate check-set
pin), skipped: 0, errors: 0, next: #860 CI repair + merge → operator-designated
immutable RC/config → exact-RC ≥4 h soak → first release-workflow run →
external verification}`.
