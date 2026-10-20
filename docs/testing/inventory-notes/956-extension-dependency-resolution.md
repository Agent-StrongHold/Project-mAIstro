---
inventory-delta:
  packages/maistro-core/tests: +100
---

# #956 (M9-C2) — deterministic extension dependency resolution and lock state

Implements the M9-C2 resolution layer over the M9-B1 install records:
strict semantic-version ranges (`maistro/extensions/semver.py`), a
deterministic resolver producing a reproducible `LockState`
(`maistro/extensions/resolution.py`), lock-driven reinstall through the real
install store (`materialize_lock`), lock diffing for updates, and the
`maistro extensions lock|explain` operator commands.

**+100 `packages/maistro-core/tests/extensions/`** (collect-only verified on
this head):

- `test_semver.py` (26) — strict `MAJOR.MINOR.PATCH` grammar (leading zeros,
  pre-release, `v` prefix, partial forms all rejected); numeric-not-
  lexicographic ordering (`1.2.3 < 1.10.0 < 2.0.0`); every comparator plus
  comma-AND ranges (`>=1.0.0,<2.0.0`); the contract-pin truth table; stable
  first-failure reporting in declaration order; loud failures for malformed
  ranges.
- `test_resolution.py` (37) — each test names its acceptance criterion:
  identical catalogs produce byte-identical locks (and are invariant to
  catalog input order); repeated resolution is deterministic; the lock
  carries no wall-clock fields; highest-satisfying-version policy with
  digest tie-break recorded as "lost tie-break", not "incompatible";
  conflicting constraints fail naming both origins, all versions, and each
  rejection reason; a constraint arriving after selection conflicts loudly
  (no backtracking); required cycles fail naming the path; optional
  dependencies are pinned when resolvable and *recorded as skipped with a
  reason* on every failure mode (absent, unsatisfiable, cyclic, range
  violation, tie conflict) — never escalated into required authority;
  optional association on an already-required entry keeps kind and identity;
  lock JSON round-trips equal with equal digest; `from_json` fails closed on
  7 corruption shapes; `explain()` answers presence, constraints, rejections,
  and skips from the lock alone; `diff_locks` reports added/removed/changed
  identities for updates.
- `test_lock_reinstall.py` (8) — end-to-end against the real SQLite store
  with real Ed25519 signatures: materializing a lock recreates exactly the
  locked identity set with verified trust evidence; reinstall is idempotent;
  two of three artifacts missing → `MissingLockArtifacts` naming both, with
  an empty store and zero activations; two fresh hosts from one lock JSON
  rebuild identical sets (restart criterion); tampered bytes fail
  `PackageDigestMismatch` before any record or activation; unregistered
  publisher fails closed; an update lock materialized over the old store
  keeps both lib-b identities in append-only history (install/update
  integration via `diff_locks`).
- `test_cli_lock.py` (7) — `maistro extensions lock` renders one row per
  pinned version plus the lock digest; `explain` answers why the extension
  and its version are present (reason, constraints, policy, skipped
  optionals); unlocked extension, missing file, and invalid lock all exit
  non-zero.

Fail-before evidence (mutations applied to `resolution.py`, then reverted;
`git diff` verified clean after each):

- `max(candidates, …)` → `min(...)`: 3 tests fail (version policy, tie-break
  determinism, explain rejections).
- cycle raise muted (`if False and cycle is not None`): 4 tests fail (both
  cycle tests and the downstream optional-cycle behavior).
- optional-branch `except ResolutionError` re-raised instead of skipping:
  5 tests fail — every "optional never silently becomes required authority"
  test.
- policy max → input-order `candidates[0]`: 3 tests fail, including the
  forward/backward catalog-order determinism pair.

Validation on this head: `pytest packages/maistro-core/tests/extensions` 144
passed (44 pre-existing + 100 new); mypy --strict (six package srcs, 807
files) clean; `ruff check` / `ruff format --check` clean on the full tree;
`check-reachability.py` exit 0 (no new unreachable entries — the resolver is
wired through `maistro.cli`); the vulture per-identity gate stays at 1338
reviewed identities ↔ 1338 findings with CI arguments (the two typer-
dispatched commands and the restart-equality seam are referenced in
`_vulture_whitelist.py` with the #953-consumer rationale, the same
contract-ships-first posture as the #952 store seams).
