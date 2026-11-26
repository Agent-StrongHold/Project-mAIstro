# Handoff — issue #415 (M6 milestone exit-criteria validation), lane L415, job 22de740f2af84dd0a977153b2051d256

## Scope of this round

Issue #415 is a milestone tracker: its acceptance criteria are the M6 exit
criteria (governance + repo-surface truth), evaluated at head
`086ad770863bdc1e237a4c9bec03bf9ff076beb9` (= declared develop base, worktree
clean). The job manifest declared verifier `checks: []` and no `check-*.log`
files existed, so every check below was executed fresh by this round. No
tree-side repair was warranted: all repo-side gates and the tests shipped with
the merged M6 cohort pass at this head. The residual failures are GitHub-side
bookkeeping, which this lane is prohibited from mutating.

## Executed validation (all at this head)

Repo gates (CI-exact invocations, all RC 0):

- `python3 scripts/check-deployment-claims.py` — OK (ci.yml:159)
- `python3 scripts/check-retired-guidance.py` — ok, 454 governed files (ci.yml:180)
- `python3 scripts/check-compose-secrets.py` — ok, 8 compose files (ci.yml:190)
- `uv run python scripts/check-release-consistency.py` — ok (quality.yml:766)
- `uv run python scripts/check-workflow-inventory.py` — clean, 22 workflows (quality.yml:1090)
- `uv run python scripts/check-backlog-consistency.py` — OK, 167 items (quality.yml:1097)
- `uv run python scripts/check-shipped-surface-truth.py` — complete (vulture-ratchet.yml:79)
- `uv run ruff check .` — passed; `uv run ruff format --check .` — 2855 files clean

Targeted tests (criterion 3: M6 removals did not weaken safety):

- `uv run pytest tests/test_install_compose_floor.py tests/test_check_workflow_inventory.py -q` — 71 passed
- `uv run pytest packages/hive-conductor/backend/tests/test_fresh_install_security_truthfulness.py -q` — 9 passed

GitHub state (read-only `gh api`, no mutations):

- #452 open, lists 19 direct deferred children; every child's body carries
  exactly one `Parent initiative: #452` line (verified per-issue).
- #412 has no milestone and names `Parent program: #453` with an explicit
  not-a-hierarchy-authority clause — consistent with #415's ownership rule.
- #408 and #441 are closed `completed`. #1195 (parent #55, label `milestone:M1`)
  has a canonical parent but sits in the M6 GitHub milestone — placement drift.

## Exit-criteria assessment

1. Every direct child of #452 implemented / closed with rationale / promoted —
   **in substance partially met; GitHub state lags the tree.** Implemented
   in-tree but still OPEN: #399 (95553db80, +9 truthfulness tests), #400
   (cfb6c3b64, workflow inventory gate), #401 (5d962bdab, placeholder gone),
   #407 (9522eb57d, Compose v2 floor + 71-test coverage); likewise #1116
   (086ad7708) and #1117 (014245aa5), parented to #452 but unlisted in its
   child checklist. Remaining children (#402–#406, #409–#411, #863, #1191,
   #1205–#1207) are open and unimplemented — the expected live state of an
   open milestone.
2. Deferred configuration/UI surfaces do not misrepresent capabilities —
   **met**: all seven surface/deployment/consistency gates RC 0 at this head.
3. Closing an item does not weaken an earlier milestone's safety or release
   contract — **met**: each merged M6 removal shipped its own regression tests
   (re-executed above) plus inventory notes; release-consistency and
   shipped-surface-truth gates clean.
4. No `milestone:M6` issue lacks one unambiguous canonical parent —
   **violated**: #1331, #1349, #1350, #1351 are open, labeled `milestone:M6`
   and in the M6 GitHub milestone, and carry **no** `Parent` line of any form
   (verified by full-body scan). All other M6-population issues resolve to
   exactly one distinct parent (#452, or #55/#453/#415 as applicable).

## Required repairs (GitHub-side; needs a mutation-capable driver)

1. Triage #1331/#1349/#1350/#1351 and add one `Parent initiative: #452` line
   each (or reparent out of M6 if their risk has changed), satisfying #452's
   intake rule.
2. Close #399/#400/#401/#407 (and #1116/#1117) as completed with the merge
   commits above as rationale, and tick their boxes in #452's checklist.
3. Add #1115/#1116/#1117/#1333 (and #133, #1191-family already listed) to
   #452's "Direct deferred children" checklist so its list matches the live
   `milestone:M6` population, and correct #1195's GitHub milestone field
   (label says M1) or its label, whichever the M1 owner confirms.

## Residual risks

- #1195 is a P0 M1 issue physically parked in the M6 milestone: until its
  milestone field is corrected, milestone-scoped queries over M6 will surface
  an issue whose canonical owner is M1.
- The four parentless issues were deferred from review threads; without a
  parent line they are invisible to #452's intake/exit bookkeeping and can be
  silently lost — the exact failure mode M6 exists to prevent.
