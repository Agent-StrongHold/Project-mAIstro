# CR-2375 round 2 — develop sync conflict resolution + local gate battery

Branch: `dependabot/docker/templates/autonoetic/python-3.15.0-slim-bookworm`
Round start head: `e8323b52a942` (left mid-merge by the previous round: `git merge 469f361339`
(then-tip of `origin/develop`, carrying #2377 + the M7-A5 fence WIP) had three
unmerged paths). Round end head: `14f2d3c70a44`.

## What was in conflict

Both sides had independently retired the picomatch audit waiver
(GHSA-fc5q-39xc-vjpf, withdrawn upstream 2026-11-18T15:38:56Z) — the branch in
`dbe5499410` (this PR's CI repair), develop in its own commit. Same semantics
(`ALLOWED = {}`, tests inject waivers explicitly), different wording:

- `.github/workflows/ci.yml` — the npm-audit comment block above the gate step.
  Resolution: develop's comment, with the branch's "0 advisories against the
  identical lock, picomatch still pinned at 4.0.7" fact folded in.
- `scripts/npm_audit_gate.py` — the comment above `ALLOWED` and the
  unwaived-advisory fix hint. Resolution: merged comment (withdrawal timestamp
  + identical-lock detail + pointer to the round-9 notes), develop's fix hint
  ("the retired waiver in git history shows the expected shape" — the old
  branch text claimed the comment block above ALLOWED still spelled out the
  bar, which stopped being true the moment the waiver was deleted).
- `tests/test_npm_audit_gate.py` — docstring + three `_run(allowed=...)`
  call sites. Resolution: per-test, forced by shared hunks outside the
  conflict regions:
  - module docstring: merged text (withdrawal date + every test injects its
    allowlist, retirement pins excepted);
  - `test_a_waiver_covers_the_advisory_and_every_package_it_cascades_into`:
    develop's side — the shared body below the hunk references `advisory_id`,
    which only develop's side binds;
  - `test_a_new_advisory_on_the_same_chain_is_not_covered_by_the_waiver`:
    develop's side (consistent wording);
  - `test_a_waiver_whose_advisory_stopped_being_reported_is_stale`: branch's
    side (`GHSA-gone`) — the shared body asserts `"GHSA-gone" in out`, so
    develop's hypothetical-waiver text would have failed it.

## Local gate battery (all green at round end, exact commands in evidence)

- ruff check / ruff format --check (one format drift in the merged comment
  fixed in `14f2d3c70a`)
- `pytest tests/test_npm_audit_gate.py` (15 passed), `pytest tests/` (5929
  passed / 139 skipped), `pytest packages/maistro-core/tests/graph/durable_runs
  packages/maistro-core/tests/runs` (2373 passed) — the suites the merge
  touched
- `check-suite-inventory.py` (21 suites match the recorded inventory — no
  inventory-note delta needed: the resolution selects between sides, it does
  not add tests)
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (1235 reviewed identities = 1235 findings, baseline read
  from merge base 469f361339)
- `check-ratchet-provenance.py` (55 consumers, no candidate-approved expansion)
- `check-radon-baseline.py` (126 = 126), `check-reachability.py` (ok)
- `check-image-pins.py`, `check-image-inventory.py`, `check-build-context.py`,
  `check-workflow-inventory.py`, `check-workflow-write-safety.py`
- live npm audit through the gate: `npm audit OK (0 advisories reported, all
  triaged in ALLOWED)` — the advisory stays withdrawn, so the empty ledger is
  the correct production state
- live pip-audit through the gate (CI's exact invocation): `pip-audit OK (1
  known, all triaged in ALLOWED)` — ecdsa PYSEC-2026-1325
- Docker Hub re-verification of the bump: `docker buildx imagetools inspect
  python:3.15.0-slim-bookworm` resolves to exactly the pinned
  `sha256:0e019bbdfb5d9874cb2389f1c2884b64aa2ac97c99960b5bc521cef978c0617d`,
  and `docker run` of that digest prints `Python 3.15.0`

## Mergeability against the current PR base

`git merge-tree --write-tree origin/develop HEAD` (origin/develop =
8b6e4eca40a1, three commits past the synced 469f361339, none overlapping this
branch's files) exits 0 with zero conflicts: the branch merges cleanly into
the base the merge queue will use.

## Not reproduced locally (hosted-only, inputs unchanged)

Container scan + SBOM + cosign and the full-suite coverage producer. Both were
green at the last merge-queue evaluation of this branch; this round's delta
contains zero `packages/*/src` lines (`git diff 469f361339..HEAD`), and
diff-coverage's MEASURED_ROOTS covers `packages/*/src` only, so the coverage
floor cannot move from this resolution. The container gate consumes
`quality/image-pins.json`, whose autonoetic row this round re-verified live
against Docker Hub instead of by rebuild.
