# cr-2371 — grant-only PR verification (#1629 debt authorization)

No test inventory change (no tests added, removed, or modified), so this note
carries no `inventory-delta` front matter — per `docs/testing/inventory-notes/README.md`,
a note without the block records no delta, which is the normal case for a
change that moved no count. (An earlier draft of this note wrote a
nested `added/removed/modified` block instead; `check-suite-inventory.py`
read those keys as suite names and failed the CI `test` job with
"recorded suites with no collection recipe: added, modified, removed" — the
block is therefore removed rather than re-indented.)

This PR began as a two-merge ratchet grant: one entry `@tool/plan_delivery`
under `reachability` in `quality/ratchet-authorizations.json` (+5 lines vs
merge-base), so #1640 could bank the matching baseline/disposition row from
a base that already carries the grant. Round 5 below **withdrew that grant
as moot** — no reachable tree can ever produce the `@tool/plan_delivery`
identity, and no ledger row for it exists anywhere — so the current diff is
the `mutation.yml` gates-ran trigger repair (round 4) plus this note, with
`quality/` byte-identical to the merge base.

## Round 2 evidence (local, CI-exact arguments, head after develop sync)

This round (1) synced `origin/develop` (`fdf545a6175`) into the branch and
(2) fixed the note front matter described above. The sync picks up the
already-landed prune of the superseded `ac-state` grant
`design_coverage@39.641` (removed on develop by #2361/#2363), which is what
makes `Quality / Acceptance state` pass here: `check_ac_state_impl.py`
computes `superseded_by_present` from the candidate tree's own grant file, so
the only run that passes is the one that no longer carries the row.

- Branch diff vs merge-base `origin/develop` (`fdf545a6175`) touches exactly
  two files: `quality/ratchet-authorizations.json` +5 (the one grant, with
  owner/issue/reason) and this note. No product code, no baseline or
  disposition edits.
- Post-merge row audit of `quality/ratchet-authorizations.json`: all 13
  develop `reachability` rows retained + this branch's `@tool/plan_delivery`
  (14 total); `ac-state` is `{}` (develop's prune, not re-added); every other
  section count matches `origin/develop` exactly; `quality/vulture-baseline.json`,
  `quality/reachability-baseline.json`, `quality/reachability-dispositions.json`
  and `docs/testing/inventory/baseline.json` are byte-identical to develop.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
  (the exact-debt-ledger job's invocation, vulture-ratchet.yml) → exit 0;
  resolves base `ba7d378ef7d3` → candidate `21986b8b92e8` pre-sync and
  "no candidate-approved expansion", "55 quality JSON consumer(s) have
  explicit provenance".
- `uv run python scripts/check-reachability.py` (quality.yml Quality /
  Reachability) → exit 0; 88 unreachable of 1492 modules, unchanged from
  develop.
- `uv run python scripts/check-reachability-dispositions.py` (quality.yml
  Quality / Reachability dispositions) → exit 0; 30 groups cover all 88
  unreachable modules (67 CONNECT, 20 LIBRARY, 1 RETIRE).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact CI args) → exit 0;
  1235 reviewed identities, 1235 findings, unclassified 0.
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0.
- `uv run python scripts/check-compliance.py` → exit 0.
- `uv run pytest tests/test_ratchet_provenance.py
  tests/test_check_ratchet_provenance.py tests/test_reachability_baseline_identity.py
  tests/test_check_reachability.py tests/test_check_reachability_dispositions.py`
  → 133 passed.
- Driver battery at the pre-sync head: `uv sync --locked --extra dev` ok,
  `ruff check .` all passed, `ruff format --check .` all formatted.

## Why the earlier RED CI picture is not a content failure of the grant

On head `272fd3aade` (and its develop-merge `21986b8b92e8`) every check run
was mass-cancelled twice (2026-10-26T11:07:32–39Z and ~11:17–11:18Z); the
`failure` conclusions were aggregate/waiter jobs reporting cancelled
dependencies ("dependency did not succeed", "docker-build … concluded
cancelled"), not scanner findings. On the re-run at `21986b8b92e8` (2026-11-18),
two real content failures appeared — both repaired by this round:

- `test` job → `scripts/check-suite-inventory.py` exit 2: this note's
  malformed `inventory-delta` block (see above). Repaired here; reproduced
  locally with `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-suite-inventory.py` → exit 2 before the fix.
- `Quality / Acceptance state` → `scripts/check-ac-state.py` FAIL
  "authorized floor(s) independent landings have superseded":
  `design_coverage@39.641` was already pruned on develop
  (`ac4a7667ba`, `fdf545a617`), but this branch's develop merge predated the
  prune. Resolved by syncing `origin/develop` (`fdf545a6175`); the candidate
  file no longer carries the superseded row, which is the run the gate
  accepts ("by_present is correctly empty, because there is nothing left in
  the file to report on").
- `Quality gate (Pillars 1–4, 7, 8)` was a waiter on the above
  ("quality-acceptance: dependency did not succeed"), not an independent
  finding.

## Round 3 evidence (independent verification at head `b279fd8d8f`, base `8b6e4eca40a1`)

Re-run of every content-relevant gate on the post-sync head, in a
`uv sync --locked --all-extras` environment (the exact-debt-ledger job's
recipe). This corrects two prose-only counts above that had been measured in
the smaller `--extra dev` venv: the reachability scan reports **1492**
production modules (not 1489) and the vulture scan **1235** reviewed
identities (not 1236); both ratchet invariants are unchanged (88 → 88
unreachable, no candidate-approved expansion).

- `origin/develop` resolves to `8b6e4eca40a1`; `git diff --numstat
  origin/develop -- quality/` shows exactly `quality/ratchet-authorizations.json`
  +5/−0, and `quality/vulture-baseline.json`,
  `quality/reachability-baseline.json`, `quality/reachability-dispositions.json`,
  `docs/testing/inventory/baseline.json` are byte-identical to `origin/develop`.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
  → exit 0; base `8b6e4eca40a1` → candidate `b279fd8d8fdf`, "OK: 88 unreachable
  module(s), no candidate-approved expansion", "OK: 55 quality JSON consumer(s)
  have explicit provenance". The grant is inert on its own branch by
  construction (`ratchet_provenance.load_authorizations` reads grants from the
  base revision), so this PR cannot bank the debt it authorizes.
- `check-reachability.py` exit 0 (1492 modules, 88 unreachable);
  `check-reachability-dispositions.py` exit 0 (30 groups: 67 CONNECT, 20
  LIBRARY, 1 RETIRE); `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exit 0 (1235 identities);
  `check-shipped-surface-truth.py` exit 0; `check-compliance.py` exit 0;
  `uv run python scripts/check-suite-inventory.py` exit 0 ("ok: 21 suite(s)
  match the recorded inventory"). Note the last one must run under `uv run
  python` locally: a bare system `python3` without the workspace deps
  reports 102 collection errors, which is an environment artifact, not a
  tree defect (CI installs the deps before the same command).
- `Quality / Acceptance state` reproduced **with CI's service stack**:
  `pgvector/pgvector:pg18` on :5432 (maistro/maistro/maistro_test),
  `uv run alembic upgrade head`, `uv pip install -e packages/maistro-evolve`,
  `age-keygen` on PATH, `DATABASE_URL`/`MAISTRO_TEST_PG_DSN` set,
  `RATCHET_BASE_REV=origin/develop`, then
  `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
  8b6e4eca40a1…` → **exit 0**; `design coverage: 44.4608%` sits exactly on the
  floor folded from the 50 base notes ("1 progress counter sits exactly on its
  floor"), mandate and chain mandate both OK. Without those services the same
  command measured `design coverage: 39.8641` and failed the floor —
  `--run-tests` drops criteria that cannot execute locally out of the
  `reachable` rung, so a service-less local run under-measures and is not
  evidence about this branch (whose diff touches no spec, ADR, test or
  baseline).
- `uv run pytest tests/test_ratchet_provenance.py
  tests/test_check_ratchet_provenance.py tests/test_reachability_baseline_identity.py
  tests/test_check_reachability.py tests/test_check_reachability_dispositions.py`
  → 133 passed; `uv run ruff check .` → all checks passed.
- Branch commit messages scanned for GitHub closure keywords
  (`fixes/closes/resolves #N`): none.

## Residuals (recorded, not repaired here)

- #1640's current head places the planner at `tools/plan_delivery.py`, while
  `scripts/check-reachability.py` collects tooling from `TOOLING_DIR = "scripts"`
  only — so `@tool/plan_delivery` may never enter the baseline and the grant
  may go unexercised. Unused authorizations are harmless (the provenance gate
  passes with this grant present and unused). The grant reason's reference to
  the LIBRARY disposition describes the state #1640 is expected to bank, not a
  row that exists today.
- "CI green on the new tip" cannot be proven from this lane (push prohibited);
  the content-relevant gates are re-run locally with CI's exact arguments and
  recorded above. At capture, 61 of the head's 64 check runs were still
  `in_progress`/`queued` with 3 completed successes, so hosted CI remains the
  separate acceptance gate.

## Round 4 evidence — root cause of the stuck merge-queue gate + repair (head after develop sync `d521240c6b`)

The lane block was "commit status not successful". Root-caused from the
dispatch-captured GitHub evidence at `ca2feefd1d9b` and reproduced locally
with CI's own evaluator — **the only non-successful signal on that head is
the required `gates-ran` commit status, permanently PENDING**:

- Hosted check runs at `ca2feefd` (captured 07:41Z): **79 runs, 73 success /
  6 skipped (classifier-scoped)/ 0 failures / 0 in-progress**. Every
  previously-RED gate (Analyze x3, Compliance registry, Container scan,
  Coverage gate, DevSkim, Gate C, Quality / Acceptance state, Quality/*)
  is `success`. The earlier "RED gates" list predates this head.
- The 9 `gates-ran` commit statuses are all `pending` ("Required execution
  evidence is still arriving", last 06:19:59Z — *after* the last producer
  finished). PR #2371 is `mergeable: true, mergeable_state: unstable` purely
  on that status.
- **CI-exact reproduction** (`python3 scripts/check-gates-ran.py
  --check-runs <captured> --require-complete --base-branch develop
  --event-name pull_request --changed-files <PR files>`): `EXIT 2 — PENDING,
  not present yet (1): Mutation gate (changed critical lines)`.
- Why permanent: `mutation.yml`'s `pull_request` paths filter does not match
  this PR (grant JSON + inventory note only), so the workflow never triggers
  and the check can never appear; `check-gates-ran.py` includes every
  every-PR row from the generated table in the evidence set and only excuses
  the `PATH_SCOPED_CHECKS` classifier legs. This is precisely the failure
  mode and remedy documented in the same file for `quality/image-pins.json`
  (#2120): list the governance surface in the trigger so the gate reports
  real zero-overlap evidence instead of permanent absence.

Repair (this round, commit `1ea63a73e7`): added
`quality/ratchet-authorizations.json` and `docs/testing/inventory-notes/**`
to `mutation.yml`'s PR trigger. Grant content untouched (`git diff --numstat
origin/develop HEAD -- quality/` = exactly +5 on
`ratchet-authorizations.json`; every other ledger byte-identical). Also
merged `origin/develop` (`d521240c6b`, one commit, no conflicts) — the
branch was out-of-date; merge head `a854dfb694`.

Local proof at `a854dfb694`:

- Post-fix evaluator run (captured 79 runs + the zero-overlap success run the
  fixed trigger now produces): `ok: all 73 required check(s) ran on this
  head`, **exit 0** → the publisher flips `gates-ran` to success on the next
  hosted evaluation of this PR.
- The zero-overlap job path itself: `uv run python scripts/mutation_critical.py
  --changed-from <empty and non-Python sets>` → `no mutation-critical files
  in the changed set`, exit 0 twice.
- `python3 scripts/check-required-checks.py` (workflow-lint, CI-exact) → ok,
  78 PR checks match the contract table.
- Exact-debt companions, CI arguments: `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → 1235 =
  1235 identities, exit 0; `check-reachability.py` → 1492 modules / 88
  unreachable, exit 0; `check-reachability-dispositions.py` → 30 groups OK;
  `RATCHET_BASE_REV=origin/develop check-ratchet-provenance.py` → base
  `d521240c6b2d` → candidate `a854dfb69491`, "no candidate-approved
  expansion", 55 consumers, exit 0; `check-suite-inventory.py` → 21/21.
- Tests: gates/required-checks/mutation-targets set → **197 passed**;
  ratchet/reachability set (12 files) → **299 passed** (same as round 3).
- `uv run ruff check .` / `ruff format --check .` → clean.

No test inventory change (no tests added, removed, or modified).

## Residuals (recorded, not repaired here)

- The `gates-ran` fix takes hosted effect only once this branch's
  `mutation.yml` change is the PR definition GitHub evaluates (pull_request
  workflows run the candidate's definition), i.e. on the next CI run of this
  PR after push. Push is prohibited from this lane, so hosted green remains
  the separate acceptance gate; the evaluator proof above is CI-exact.
- A deeper evaluator-side design option (treat generated `paths`-scoped rows
  like `PATH_SCOPED_CHECKS`, excusing absence on a measured changed-file
  envelope) would fix the class without widening triggers, but cannot make
  *this* PR green (the publisher evaluates with default-branch code) and is
  a contract change beyond this grant lane.
- #1640's head `4fb4a2be` carries its own red `test` check run (2026-11-18)
  and its own `gates-ran` eventually went success there; that is #1640's
  lane, not this PR's head.

## Round 5 evidence — grant withdrawn as moot (repair at this head)

The independent verify round at `cb17b1b4f0` returned NEEDS-REPAIR: the
grant this PR was opened to authorize is void on every reachable tree. Facts
re-derived locally at the repair head (not trusted from the dispatch):

- `git cat-file -e origin/develop:scripts/plan_delivery.py` and the same
  for `HEAD` both fail — the file exists on **no** reachable tree. It was
  born inside PR #1640 and relocated there to `tools/plan_delivery.py`
  (#1640 commit `5ba1b82b85`, "relocate delivery planner to tools/ so the
  reachability floor-raise it cannot self-authorize is no longer required").
  `check-reachability.py` cannot see `tools/` either: it collects tooling
  from `TOOLING_DIR = "scripts"` only (`scripts/check-reachability.py:29`).
- `grep -c plan_delivery` over `quality/reachability-baseline.json`,
  `quality/reachability-dispositions.json` and develop's
  `ratchet-authorizations.json` → 0 rows everywhere; only this branch's own
  grant ever mentioned the identity, so the grant reason's claim to authorize
  "its matching disposition" described a row that does not exist.
- `uv run python scripts/check-reachability.py` at the repair head → exit 0,
  88 unreachable of 1492 modules, **none named plan_delivery**.

Why removal rather than leaving the grant inert: round 3's residual ("unused
authorizations are harmless") is **superseded**. Develop itself prunes
superseded grants (the `design_coverage@39.641` ac-state prune of
#2361/#2363, recorded in round 2 above), so merging a dangling grant
recreates the anti-pattern develop just cleaned up — and it would pre-waive
the two-merge review for any future `scripts/plan_delivery.py`. The grant
hunk is therefore removed; `git diff origin/develop -- quality/` is empty
(byte-identical ledger) at the repair head.

Kept, with justification reworded to stay truthful:

- The `mutation.yml` trigger additions (round 4) **stand**:
  `docs/testing/inventory-notes/**` is exercised by this PR's own remaining
  diff, and `quality/ratchet-authorizations.json` stays for the class it
  fixes — recurring grant-only PRs of the two-merge protocol, measured
  PENDING-forever at `ca2feefd1d9b`. The in-file comment no longer claims
  this PR ships the plan_delivery grant.
- This note stands as the PR's evidence record.

Repair-head local battery (CI-exact arguments) — results recorded in the
round-5 battery note that follows this section:

- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` (vulture-ratchet.yml invocation) —
  the grant's removal cannot expand the candidate; expected 88 → 88, no
  candidate-approved expansion.
- `uv run python scripts/check-reachability.py`; `uv run python
  scripts/check-reachability-dispositions.py`; `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`; `uv run python
  scripts/check-suite-inventory.py` — all expected exit 0 (ledger is
  byte-identical to develop, so every scanner result must equal develop's).
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- Merge-order residual for the operator: #1640's head carries a commit that
  removes `mutation.yml`'s `paths` filter entirely, which overlaps this
  branch's trigger additions — whichever lands second must resolve the
  conflict in favor of a filter that still lists the governance surfaces
  (or accept the other PR's design), so this PR and #1640 need merge-order
  coordination.
- Hosted CI green on the repair tip remains UNVERIFIED from this lane (push
  prohibited), as in every prior round.
