---
inventory-delta:
  tests/: +57
---
# 951-extension-sdk-boundary

The extension SDK boundary lands (#951, epic M9-A #938) with its own gate
suites in the root `tests/` tree, all against fabricated trees in tmp
directories plus two tests over the real one.

## What moved

`tests/test_check_extension_imports.py` (+41) covers
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
(attribute or bare name), so plausible non-imports pass. The violation-class
matrix includes the third private spelling (`from root._internal import
thing`), where the underscore hides in the `from` path rather than in the
alias.

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
only reason the delta is 57 rather than 56 collected-and-passing.

## The review-repair round (second)

The independent review of the first cut left findings; the repair adds the
eleven node IDs this note's delta now carries, all in
`tests/test_check_extension_imports.py`:

- the manifest `entrypoint.module` is held to the same boundary as imports
  (`manifest_entrypoint_violations`): a host imports it as extension code, so
  a manifest could otherwise reach `maistro.security.warden` or a
  repo-relative root without a single import statement for the scan to see.
  Covered both ways on fabricated trees — one test for the passing shape
  (own namespace, no underscore segments) and a parametrized matrix for the
  failing ones (product-private, repo-relative, another public SDK root,
  any other foreign root), plus a private entrypoint under the extension's
  own namespace and an unreadable manifest failing loudly — and once against
  the real reference extension, whose entrypoint must name its own packaged
  namespace;
- the private-member scan learned the `from` path spelling: `from
  maistro_ext_sdk._internal import thing` is now named, joining the two
  spellings the first cut already caught.

The fixture suite's count is unchanged (+16): its repair changed assertions
on existing tests, not their number — the plan now verifies the installed
distribution carries the policy's required artifacts (`extension.json`) via
`importlib.metadata`, and executes a staged copy of the extension's tests
from the sandbox instead of the checkout's `tests/` directory, so a suite
cannot read a resource the wheel does not ship. The wheel carries the
manifest via `force-include`; the extension's root-environment suite reads
the installed distribution first and falls back to the extension root's copy
only under the editable install, where no wheel exists to read — in the
isolation sandbox the fallback file does not exist, so the fixture still
fails a wheel that drops the manifest.

## What did not move

No package suite changed: the gate and the fixture are root-tree tooling, and
`packages/` is untouched.

## The extension suite's own row (repair round)

The first cut left `extensions/reference-greeter/tests` out of the inventory
entirely, on the reading that a suite run only inside the isolation fixture is
not part of the root environment's surface. That reading failed the first
independent validation: `uv run pytest
extensions/reference-greeter/tests/test_reference_greeter.py` — the command
any author, verifier, or driver runs for a file that exists in the tree —
collects the module in the root dev environment, where `reference_greeter` was
not installed, and died with `ModuleNotFoundError` before an assertion could
run; and `check-suite-inventory.py --suite extensions/reference-greeter/tests`
had no collection recipe to name. A suite that only the fixture can execute is
invisible to both.

The repair keeps the division of labor and closes the gap:

- The reference extension joins the uv workspace
  (`members = ["packages/*", "extensions/reference-greeter"]`) and the root
  `dev` extra installs it editable. `uv run pytest extensions/...` now runs
  the five self-contract tests in the root env — the same assertions the
  fixture runs in the clean venv.
- The boundary is untouched. Membership is build wiring: the extension still
  declares zero dependencies, still imports nothing first-party (its own test
  asserts it), the static gate still fails any product-private or
  repo-relative import, and the isolation fixture still proves the wheel
  builds and tests in a venv that holds none of this repository — the
  clean-environment acceptance criterion is the fixture's, not the root
  install's.
- The suite is registered: a `RECIPES` entry (plain collection — the editable
  install makes `reference_greeter` importable with no PYTHONPATH repair), a
  `SUITE-INVENTORY.md` row, and its baseline count (5). No delta line is
  recorded for it: a baseline entry is how a newly registered suite enters
  the ledger, and an outstanding delta on top would double-count it (the
  gate would then expect 10 where the suite collects 5). A future change
  that breaks the extension suite's collection is inventory drift, loud like
  any other.
