---
inventory-delta:
  packages/maistro-core/tests: +26
---
# auto-950 — M9-A2 canonical extension context and lifecycle (#950)

Adds the `packages/maistro-core/tests/extensions/` suite pinning the new
public extension contract (`maistro.extensions`, ADR-104, issue #950). The
26 tests split across two files by what they pin:

- `test_extension_contract_conformance.py` (21) — the interface contracts
  themselves, independent of any one extension implementation: the closed
  public context surface (no store/container/db handles, `__slots__`-pinned),
  declared-only configuration access, service grants requiring declaration
  AND host grant, effect dispatch requiring declaration AND route plus a
  cancellation pre-check, the cancellation view's read-only semantics over
  the canonical task fence (including never swallowing `CancelledError`),
  progress-hook validation, structural lifecycle protocol conformance, and
  extension-attributed lifecycle error wrapping.

- `test_extension_reference_execution.py` (5) — a reference extension
  executing through the canonical `Graph → Run → NodeRun → Attempt` path
  (`AttemptExecutionService` over `PythonExecutionRuntime`): its governed
  effect produces a real canonical `Invocation` row with full correlation,
  provenance and progress land on the canonical event stream with the
  extension identity in the envelope `provenance` field, undeclared effects
  and activation-scope dispatch are refused, and `service.cancel(attempt_id)`
  reaches the extension's cancellation view while the Attempt settles
  CANCELLED with NodeRun/Run terminal.

No existing tests were removed or renamed; the delta is purely additive.

## Validation battery (executed at head `f348fa3e0bfb…`, branch `auto-950`)

Re-executed after the CI-repair round on top of `869f936f525e` — the repair
(`CORE_PUBLIC_SURFACE` enumeration, ADR-104 `related` reclassification,
`EventStoreProgressSink` M1 projection marker) changed no test, so the counts
below are unchanged; the newly executed provenance gates are appended.

- `uv run ruff check .` → All checks passed (exit 0); `ruff format --check .`
  → 2926 files already formatted.
- `uv run mypy --strict packages/maistro-core/src/maistro/extensions
  packages/maistro-core/src/maistro/runtime/__init__.py` → Success, no issues.
- `uv run pytest packages/maistro-core/tests -q` (minus `tests/integration`,
  the known services-down set) → **12422 passed, 888 skipped, 1 xfailed**.
- `uv run pytest packages/maistro-server/tests packages/maistro-design/tests
  packages/maistro-registry/tests -q` → **1039 passed, 9 skipped** (the root
  package's import graph changed in this lane, so sibling importers were run).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0; 1338 reviewed
  identities → 1338 findings; `unclassified: 0`. The SDK's external-only
  methods are referenced in `packages/maistro-core/src/_vulture_whitelist.py`
  (public-surface mechanism; no `quality/*.json` rows added).
- `uv run python scripts/check-reachability.py` → exit 0; the six new modules
  are wired through the documented `maistro.runtime` anchor.
- `uv run python scripts/check-promotion-surface.py` → exit 0 (an earlier
  draft anchored the SDK in the package root, which dragged the
  capabilities/events/policy/credentials subgraph onto the promotion path;
  that anchoring was replaced — see ADR-104 §7).
- `scripts/check-radon-baseline.py` (143=143), `check-suite-inventory.py`
  (14 suites ok), `check-contract-markers.py` (ADR-104 evidenced by the
  `contract: behavioral` markers on both new test files), `check-adr-index.py`,
  `check-ac-state.py`, `check-doc-links.py` → all exit 0.
- A ledger `--update` run against `quality/contract-markers-baseline.json`
  was reverted unused; the ADR-104 claim is evidenced by markers instead.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` (the `exact-debt-ledger` portfolio,
  CI's exact step) → exit 0 after the repair: citation-status 0 exceptions,
  enumerations 1 tolerated gap, adr-status-language / promotion-surface /
  reachability / reachability-dispositions / shell-execution /
  contract-markers / lifecycle all flat vs the trusted base.
- `uv run python scripts/check_enumerations.py` → exit 0, no new gaps
  (`maistro.extensions` is enumerated in `CORE_PUBLIC_SURFACE`,
  `scripts/verify-wheel-imports.py`).
- `uv run python scripts/check-citation-status.py` → exit 0 (SPEC-177 cited
  as `related`, not governing `substrate`, in ADR-104).
- `python scripts/check-m1-convergence-freeze.py --base 94781cf6` → exit 0
  (`EventStoreProgressSink` docstring carries the policy's own
  `M1 product-local projection: Event` classification).
- `tests/test_check_citation_status.py` root self-checks (the ones CI's
  `test` job and the coverage combine step run) → pass; plus
  `tests/test_verify_wheel_imports.py`, `tests/test_check_enumerations.py`,
  `packages/maistro-core/tests/extensions`, `packages/maistro-registry/tests`
  → 313 passed total across the repair battery.
- `scripts/check-diff-coverage.py` (branch coverage over the changed
  measured files) → ok at 90% lines / 80% branch floors.
- `scripts/check-adr-index.py`, `maistro_registry.cli lint . --strict`,
  `scripts/check-doc-links.py`, `scripts/check-ac-state.py`,
  `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (1338=1338, `unclassified: 0`) → all exit 0;
  `quality/` is byte-identical to the base (no ledger rows added).
