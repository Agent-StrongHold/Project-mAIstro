# REPAIR-NOTES — #330 round 3: develop sync conflict resolved and merge validated

Job `e54dbedd875f496f8ccabfe3e4ec6a7f`, branch `auto-330`. Starting state:
the previous worker died mid-merge with `origin/develop` (`f956a814275c`,
2 commits: fastmcp/setuptools/pypdf bumps + its own #2285 concurrency work)
partially merged and ONE unmerged path:
`scripts/check-image-lock-reconciliation.py` — which is why the incoming
pre-validation failed ruff ("Failed to parse ... Expected a statement",
104 errors): the file still contained conflict markers.

## The conflict

Both sides had independently fixed the same #330 containers-gate bug (a
uv.lock forked across `python_full_version` markers exports several
`name==version` pins for one distribution; a name-keyed parse dropped all
but the last and failed a correct py3.13 image):

- this branch (`0ec7d211b`): `parse_expected` keeps every variant per name
  (`variants: dict[str, dict[str, bool]]`), plus a new pure-logic
  `reconcile_variance(required, conditional, actual)` helper that main()
  calls; skew message `a != x or y`.
- `origin/develop` (`f956a814275c`, merge-queue run 40085096483): same fix
  expressed as `by_name: dict[str, set[str]]` plus an `_expected_clause`
  formatter; skew message `a != one of x, y`.

## Resolution (commit 35555d1fd)

Union, not either/or:

- `parse_expected`: develop's simpler `by_name` structure (behaviourally
  identical to the branch's `variants` map — both classify a name with any
  conditional variant as conditional-as-a-whole and keep every pin), with a
  merged docstring.
- `_expected_clause` kept (develop); `reconcile_variance` kept (branch) and
  re-expressed to format skews via `_expected_clause`, so the merged
  mismatch contract is `image_pin (image) != one of locked_a, locked_b`
  (single candidate keeps the historical exact format).
- `main()` calls `reconcile_variance` with both sides' rationale comments.
- Test file had auto-merged to the union of both sides' suites; the only
  edits were the two assertions on THIS branch that pinned the old
  `" or "`-joined skew format — aligned to the merged `one of` contract
  (`tests/test_check_image_lock_reconciliation.py`). No test added or
  removed; `scripts/check-suite-inventory.py` confirms counts unchanged, so
  no new inventory-note delta is required.

A follow-up fix removed a duplicate `reconcile_variance` (the auto-merge had
already carried the branch's copy into the file; `ruff F811` caught the
second copy my first resolution inserted) and ran `ruff format`.

## Local proof (CI's exact commands where defined)

- `uv sync --locked --extra dev` → ok.
- `uv run ruff check .` → All checks passed. `uv run ruff format --check .`
  → 3492 files already formatted.
- `uv run pytest tests/test_check_image_lock_reconciliation.py -q` → 37
  passed (union of both sides' marker-fork/split-resolution suites).
- `tests/test_mutation_*.py` (baseline, critical, diff_scope, packet,
  pr_gate, select_tests) → 113 passed.
- `uv run pytest tests/ -q` → **5843 passed, 139 skipped** — the
  `RuntimeError: Event loop is closed` reds recorded at `7e468400e` do not
  reproduce at the merged head.
- `uv run pytest packages/hive-conductor/backend/tests -q` → 3945 passed,
  25 skipped; merge-touched `test_run_concurrency_limits.py` +
  `test_resource_policy_health.py` → 71 passed, 19 skipped.
- `uv run mypy <all seven src trees>` → no issues in 937 files.
- `scripts/check-suite-inventory.py` → 21 suites match the recorded
  inventory.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact args) → 1302 reviewed identities
  = 1302 findings, unclassified 0, ratchet authorized from base
  `f956a814275c`. **No ledger amendment needed or made.**
- `scripts/check-branch-protection.py` → OK (19 required on develop, 32 on
  main); `check-workflow-inventory.py` → clean (32 workflows);
  `check-image-inventory.py` → OK.
- `scripts/mutation_critical.py --validate` → OK (8 sources, 7 domains);
  cosmic_ray/pytest/pytest_timeout importable.
- **End-to-end containers reconcile (the red under repair):** built the
  engine image from the merged tree
  (`docker build -f Dockerfile -t maistro-engine:pr-330-merged .`) and ran
  security.yml's exact step — `uv export --locked --package maistro-server
  --extra image ...` + `python scripts/check-image-lock-reconciliation.py
  --image maistro-engine:pr-330-merged --expected-file ... --member
  maistro-core==0.9.0 --member maistro-server==0.9.0 --member
  maistro-canvas==0.9.0` → **`OK: maistro-engine:pr-330-merged ships
  exactly the locked set (128 distributions, incl. 3 workspace member(s);
  14 marker-conditional pin(s) evaluated leniently)`, exit 0** — with the
  beartype marker fork still present in the merged lock (both pins in the
  export).
- `npm ci && npm audit --audit-level=high` in both
  `packages/maistro-canvas/frontend` (the ci.yml `test` red) and
  `packages/hive-conductor/frontend` → found 0 vulnerabilities, exit 0.
- Gate explicit-failure contract, live in production code (not just unit
  tests): `mutation_pr_gate.py` with a missing baseline →
  `::error::mutation baseline is unreadable/missing ... refuses to run
  without its trusted base`, exit 1; with an empty targets file →
  `::error::no mutation targets; a run against nothing is not a pass.`,
  exit 1.

The merge's only `uv.lock` delta vs the branch head is uv lockfile-revision
metadata plus macOS-only pyobjc marker rewrites — no Linux image dependency
changed, so the engine-image reconcile proof is not masking drift in the
other three image contracts (round 2 verified all four at `0ec7d211b`; the
reconcile script is the only reconcile-relevant change since, and it is
unit-covered plus now proven end-to-end).

## Not touched

- `quality/vulture-baseline.json` and every other `quality/*.json` ledger.
- No gate weakened; no workflow, ownership or policy file edited.
- No test added or removed (two assertion strings aligned to the merged
  contract); suite inventory unchanged.
