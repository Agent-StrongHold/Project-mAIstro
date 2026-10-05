---
inventory-delta:
  tests/: +46
---
# 951-extension-sdk-boundary

The extension SDK boundary lands (#951, epic M9-A #938) with its own gate
suites in the root `tests/` tree, all against fabricated trees in tmp
directories plus two tests over the real one.

## What moved

`tests/test_check_extension_imports.py` (+30) covers
`scripts/check-extension-imports.py`:

- the acceptance criterion the issue names, tested against the real reference
  extension: a pristine copy of `extensions/reference-greeter` passes the
  scan, and the same copy with one injected
  `from maistro.security.warden import _regex` fails with the offending
  module named;
- each violation class on fabricated extensions: product-private roots,
  repo-relative roots, `sys.path` repair, undeclared third-party imports
  (and the same import passing once declared), dynamic-import literals,
  underscore-private members under the public SDK root (both the
  `import root._mod` and the `from root import _helper` spellings);
- imports nested in functions and `TYPE_CHECKING` blocks still caught;
  relative imports and the standard library still allowed;
- the policy document itself: a namespace on both lists, no public roots, no
  extension trees, an unclassifiable first-party root, and an extension
  directory without a `pyproject.toml` are all loud configuration errors;
- the gate run as CI runs it (subprocess, exit 0), and `main()`'s fail and
  pass paths over a fabricated root (the real tree is never mutated),
  including unreadable/invalid policy files and build-output directories
  (`__pycache__`, `dist`) that must be ignored rather than scanned.

A test also pins a gate refinement the tests forced: a call such as
`dynamic_import_module("x")` is a helper with an unfortunate name, not a
dynamic import — the gate matches `import_module`/`__import__` precisely
(attribute or bare name), so plausible non-imports pass.

`tests/test_check_reference_extension.py` (+16) covers
`scripts/check-reference-extension.py`:

- the plan shape: build → fresh venv → install (wheel + pytest) → one
  negative control per product-private root plus the `packages`/`extensions`
  sentinels (each *expected to fail*) → the extension's tests with
  `--confcutdir` pinned at the extension root so the repository's conftest
  cannot participate;
- the documentation contract: `docs/extensions/authoring-guide.md` and
  `extensions/reference-greeter/README.md` must contain the exact command
  sequence the fixture executes *and* the wheel filename the extension's
  current name/version produces — a doc that drifts from the fixture fails
  here rather than misleading an author;
- the execution paths with subprocesses mocked (offline): `isolate()` runs
  build → venv → install (with the built wheel's real path substituted for
  the plan's glob) → one negative control per product-private root plus the
  `packages`/`extensions` sentinels → the test run, with the build in the
  extension directory and everything else in the sandbox; an ambiguous
  two-wheel `dist` is refused; `main()` reports per-extension and returns 1
  with `FAIL:` on stderr when an extension fails;
- negative-control semantics (a step expected to fail fails the fixture when
  it succeeds), `_run`'s stdout/failure reporting, clean-environment env
  stripping, discovery, configuration errors, and the one-policy-file
  invariant shared with the import gate.

One test is skipped by default (`test_full_isolation_run_end_to_end`): it
executes the whole physical run (uv build, a fresh venv, a wheel install) and
is run unconditionally by its dedicated CI step
(`scripts/check-reference-extension.py` in the `lint-and-type-check` job);
setting `MAISTRO_TEST_EXTENSION_ISOLATION=1` runs it locally. The skip is the
only reason the delta is 46 rather than 45 collected-and-passing.

## What did not move

No package suite changed: the gate and the fixture are root-tree tooling, the
reference extension's own tests live under `extensions/` (deliberately
outside `testpaths` — they are run by the isolation fixture in a venv that
holds no part of this repository, which is the property being proven), and
`packages/` is untouched.
