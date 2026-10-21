# Issue 848: exact-debt-ledger reachability repair (no test-count change)

This round added no tests, so it records no `inventory-delta:` block at all
(the key is present only when a change moves a collected node-ID count; this
one moves none). It records why the branch touches
packages/maistro-core/src/maistro/runs/__init__.py -- a production-file edit
a reviewer sees in a proof PR and should be able to check rather than trust
its commit message.

## Background: the inherited develop-side reachability hole

maistro.runs.admission_identity -- the inactive contract leaf #1851 shipped --
was unreachable from any entry point and never banked by the develop tip this
branch is cut from:

```console
$ git show e20e9f52e:quality/reachability-baseline.json | grep -c admission_identity
0
$ python scripts/check-reachability.py
1 module(s) are NEWLY UNREACHABLE: maistro.runs.admission_identity
```

So the develop tip this branch is cut from already fails the exact-debt-ledger
gate (scripts/check-ratchet-provenance.py), and every develop-based candidate
inherits that red.

## Why banking the row is structurally closed here

Two candidate-side remedies exist and one is structurally closed:

- **Bank the row** (one quality/reachability-baseline.json row + one CONNECT
  disposition). A first attempt on this lane did exactly that; it turns
  check-reachability.py and the root-suite self-checks green but cannot
  authorize itself: exact-debt-ledger runs scripts/check-ratchet-provenance.py,
  whose load_authorizations reads quality/ratchet-authorizations.json from the
  merge base -- the two-merge rule scripts/ratchet_provenance.py documents.
  With no reachability grant for the module at base e20e9f52e, the banked row
  fails provenance (NEW unreachable module absent from trusted base and not
  previously authorized), and the grant-first merge cannot be landed from this
  lane. So the ledger edit was reverted; quality/ is byte-identical to the
  base again.

- **Reconnect the module to the package's public surface** -- the repair this
  branch carries. maistro/runs/__init__.py re-exports five identity names
  (AdmissionBinding, AdmissionRecordV2, CanonicalJsonObject,
  LegacyAdmissionRecord, RootAdmissionEnvelope, with __all__ entries),
  mirroring the parallel #886 and #948 CI-repairs (2d662ed43, 8b5a2e838) for
  the identical inherited red. The module's own disposition text calls it a
  published library surface; maistro/runs/__init__.py is how this package
  publishes (it already re-exports concurrency, eval, execution, lifecycle,
  model, service, store names), and the contract's consumer evidence is its own
  test suite (packages/maistro-core/tests/runs/test_root_admission_identity.py).
  No behavior, authority path, or ledger row changes.

## Gate evidence (CI-exact invocations, RATCHET_BASE_REV=origin/develop)

```console
$ uv run python scripts/check-reachability.py
1418 production modules, 168 unreachable from any entry point   # was 169
$ uv run python scripts/check-reachability-dispositions.py
OK: 48 groups give all 168 unreachable modules a disposition (146 CONNECT, 20 LIBRARY, 2 RETIRE)
$ uv run python scripts/check-ratchet-provenance.py
OK: 53 quality JSON consumer(s) have explicit provenance (inventory + delegated gates)
$ uv run python scripts/check-shipped-surface-truth.py
Shipped-surface truth matrix is complete.
$ uv run python scripts/check-vulture-baseline.py packages/*/src \
    --min-confidence 60 --exclude '*/third_party/*'
1326 reviewed identities = 1326 findings, exit 0
$ uv run ruff check packages/maistro-core/src/maistro/runs/__init__.py
All checks passed!
$ uv run ruff format --check packages/maistro-core/src/maistro/runs/__init__.py
1 file already formatted
$ uv run pytest tests/test_check_reachability.py tests/test_reachability_baseline_identity.py \
    tests/test_check_reachability_dispositions.py tests/test_check_ratchet_provenance.py \
    tests/test_ratchet_provenance_repository.py -x -q
67 passed
$ uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
79 passed
$ uv run pytest packages/maistro-core/tests/runs/ -x -q
1399 passed, 338 skipped
```

The re-export adds no vulture identities (__all__ re-exports are uses, not
findings) and moves no other ratchet.

## Diff coverage of this branch's changed files

The per-file diff gate (90% lines / 80% branch arcs) was reproduced locally
against the develop base e20e9f52e by running the two producers that measure
the changed trees under ``coverage run --branch``:

```console
$ uv run coverage run --branch --source=packages/maistro-core/src/maistro \
    -m pytest packages/maistro-core/tests --timeout=30 -q
15664 passed, 1131 skipped, 7 xfailed
$ uv run coverage run --append --branch --source=packages/hive-conductor/backend \
    -m pytest packages/hive-conductor/backend/tests --timeout=30 -q
3780 passed, 24 skipped
$ uv run coverage xml -o /tmp/coverage.xml
$ uv run python scripts/check-diff-coverage.py /tmp/coverage.xml --base e20e9f52e
ok: every measured file this change touches is at or above 90% lines / 80% branch arcs
```

The aggregate publish-set floor and the pip-audit advisories (aiohttp, ecdsa)
remain inherited develop-side debt with owning lanes, reproduced against
pristine e20e9f52e and out of scope for this lane.

## CI-repair round at b4eaab95b4a7 (develop sync resolution)

The merge-queue failure was an exact-debt-ledger stale-ledger failure, not a
new production identity. The branch had been cut at `c2d7209f1dbc`, and
`origin/develop` advanced to `780f1d340de8` with `ac1e2f955` (personas durable
store, #2158). That commit removed two reviewed `personas/store.py::
get_for_workspace` rows from `quality/vulture-baseline.json` after wiring the
method into the durable store, while this branch still carried the pre-removal
ledger. Against the old merge base the candidate and base both counted 1326
identities, so the failure only appeared once CI evaluated the synthetic merge
with the current develop tip.

Repair: merged `origin/develop` into `auto-848` at `b4eaab95b4a7`, resolving
the sole conflict in `packages/maistro-canvas/pyproject.toml` by keeping the
branch's `pillow>=13.0.0,<14` security-floor comment on develop's identical
constraint. The merge takes develop's source wiring and its two-row ledger
removal together; no ledger row was hand-edited and no test count changed in
this repair round (so this note still carries no `inventory-delta:` block).

CI-exact gate evidence against the actual develop base (`RATCHET_BASE_REV=origin/develop`,
which resolves to `780f1d340de8`):

```console
$ uv sync --locked --extra dev
$ RATCHET_BASE_REV=origin/develop uv run python scripts/check-vulture-baseline.py \
    packages/*/src --min-confidence 60 --exclude '*/third_party/*'
ratchet: vulture [vulture (tool version: 2.16), metric v1]
  baseline: base 780f1d340de8
  candidate: b4eaab95b4a7
  1324 reviewed identities  ->  1324 findings          # exit 0
$ RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py
OK: 53 quality JSON consumer(s) have explicit provenance (inventory + delegated gates)
$ RATCHET_BASE_REV=origin/develop uv run python scripts/check-shipped-surface-truth.py
Shipped-surface truth matrix is complete.
```

Focused behavioral re-validation after the merge:

```console
$ uv run ruff check .                                  # All checks passed!
$ uv run ruff format --check .                         # 3389 files already formatted
$ uv run pytest packages/maistro-core/tests/harness/test_importers.py \
    packages/maistro-core/tests/security/test_trust_monotonic.py -q -x
44 passed
$ uv run pytest packages/maistro-core/tests/security \
    packages/maistro-core/tests/capabilities \
    packages/maistro-core/tests/skills packages/maistro-core/tests/agents -q
3300 passed, 29 skipped
$ uv run pytest packages/hive-conductor/backend/tests/test_mcp_defaults_and_manifest.py \
    packages/hive-conductor/backend/tests/test_mcp_trust_boundary.py -q
33 passed
$ uv run python scripts/check-suite-inventory.py \
    --suite packages/maistro-core/tests --suite packages/hive-conductor/backend/tests
ok     packages/maistro-core/tests: 16952
ok     packages/hive-conductor/backend/tests: 3883
```

That covers the merge-relevant acceptance boundary: rediscovery idempotence,
governed replacement, fail-closed unknown/blank provider tiers, traversal and
symlink-safe skill mutation/catalog reload, imported Pi trust clamping and
instruction scanning, and Binding-scoped MCP tool authorization (arbitrary
tool names, missing/malformed allowlists, wrong server, non-Atlassian or
plaintext endpoints).
