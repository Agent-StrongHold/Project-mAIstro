---
inventory-delta:
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