# Issue #89 — bounded implementation validation (71864dc4)

## Frozen scope

- One item: issue #89, branch `auto-89`, starting HEAD
  `0950278bfe5eef942a897018b7d8dfa67f81c31b`, base
  `7926d9ab4dda6a699a80536c6d03a59eab205725`.
- Existing implementation under review: `.github/workflows/release.yml`,
  `scripts/promote_release.py`, `scripts/release_guard.py`, their adjacent
  `tests/test_promote_release.py` and `tests/test_release_guard.py`, and the
  existing issue-89 inventory/verification notes. Relevant release ADRs and
  consistency gates are context, not new implementation assignments.
- Evidence: supplied job `dispatch-context.json` only. Do not re-fetch issues
  or inspect/modify sibling worktrees. Initial git log/diff/status show prior
  implementation commits and no uncommitted work; nothing needs salvage.
- Job directory has no `check-*.log` files. Validation must be executed here.

## Prior-attempt diagnosis and assumption

The prior result explicitly left every operational release acceptance criterion
unverified: no designated RC or actual release workflow run, no completed exact-RC
soak, and no final promotion. Repeating static checks cannot turn that absence
into acceptance. Preserve the implemented reuse path and test it against the
production workflow; repair only a reproduced defect. Do not invent RC evidence,
lower soak thresholds, run a competing scheduler, or publish artifacts.

This is the writer lane (assignment says implement), so focused implementation
and a local commit are permitted. Actual tag pushes, registry publishing and
release-environment approval remain prohibited. The prior attention request is
not a develop sync conflict: starting HEAD already contains the assigned base.

## Results

Reproduced production-graph defect: `pypi.needs` is `[guard, wheels,
m1-closeout]`, while `adopt-digests` (the only soak gate) runs in `images`,
which has the same needs. Thus PyPI can irreversibly publish the final even
when `images` fails for missing/failed soak evidence or unrouted findings.
Repair: require successful `images` before `pypi`, preserving the single
`release.yml` publisher and existing approval environment. Added dependency
regression test first: targeted pytest failed with `assert 'images' in
['guard', 'wheels', 'm1-closeout']` at `tests/test_promote_release.py:826`.
After the needs repair, `uv run pytest tests/test_promote_release.py
tests/test_release_guard.py -x -q` passed **84 tests** (1.09 s).
`uv run ruff check .` and `uv run ruff format --check .` both passed (3678
files formatted). Inventory delta: `tests/: +1`. Existing pytest plugin
warnings (unset async fixture loop scope and AnyIO CallSpec2 deprecation)
are unrelated to this workflow repair.

First independently solvable repair committed as `684e9fa5ea`.

Second reachable workflow defect in the same frozen file: `github-release`
unconditionally downloads `soak-evidence`, even for RC runs, although its
producer in `images` runs only for finals and the workflow explicitly says the
candidate has no soak evidence yet. An absent artifact is not optional for
`download-artifact`; `if-no-files-found` is an upload-artifact input, not a
skip-missing download input. The RC run cannot finish successfully to become
eligible for `select_rc_run`. Repair only this branch mismatch: download the
soak evidence on finals, fail closed if absent there, skip on RCs. Add a
workflow regression test before editing the branch condition. It failed at
`tests/test_promote_release.py:852` with `None` rather than the finals-only
condition. After repair, `uv run pytest tests/test_promote_release.py
tests/test_release_guard.py -x -q` passed **85 tests** (1.03 s).

Fresh gate results (all exit 0):
- `uv run python scripts/check-image-inventory.py`: 10 Dockerfiles inventoried.
- `uv run python scripts/check-workflow-inventory.py`: 33 workflows dispositioned.
- `uv run python scripts/check-release-consistency.py`: released none, shipping
  0.9.0, working toward 1.0.0.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: 6501 unique
  test identities match baseline plus deltas; new inventory delta is now +2.

Operational acceptance remains UNVERIFIED unless actual immutable RC/soak/final
evidence is supplied. Local tests are machinery evidence only.
