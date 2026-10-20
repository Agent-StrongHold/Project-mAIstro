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
findings) and moves no other ratchet. What remains red in CI is inherited
develop-side debt with owning lanes -- pip-audit advisories (aiohttp, ecdsa)
and the coverage-gate combine -- reproduced against pristine e20e9f52e and
out of scope for this lane.
