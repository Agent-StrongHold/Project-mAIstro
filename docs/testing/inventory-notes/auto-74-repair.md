---
inventory-delta:
  packages/maistro-core/tests: +6
---
# Issue #74 repair evidence

## Repair: unreachable whole-text semantic composition removed (post-merge)

Merging develop surfaced one new exact-debt item:
`security/warden/semantic.py: semantic_tool_poisoning_scan` (vulture
`core-public-api-surface`, reproduced against trusted base `ba2f1f07`). The
function was a whole-text composition of the Layer 2.5 signals that the product
path no longer uses: `Warden.scan` aggregates the same bounded signals across
overlapping scan windows in `detector._scan_semantic_windowed`, which is
strictly more sensitive (cross-window signal carry) and carries the corrected
capture-ordering semantics. No ledger grant was sought; the dead composition was
removed and its callers were retargeted onto the real product path:

- `formal/models/test_warden_semantic.py` now exercises
  `Warden._scan_semantic_windowed` — the evaluator `Warden.scan` runs per
  window. Equivalent for these inputs (all ≤500 chars, one window) and identical
  in flag/verdict shape, so every Hypothesis property keeps its strength under
  the CI seed (`pytest formal/models/ --hypothesis-seed=0`: 411 passed).
- `test_warden_pii_bypass.py::TestWardenCodeSyntaxDoesNotBypass` now goes
  through the `Warden.scan` product boundary and asserts the Layer 2.5 flag
  strings, so a semantic-layer wiring defect cannot hide behind a direct call
  to a pure helper (the exact blind spot that class docstring described).
  The benign-code no-false-positive property targets the Layer 2.5 evaluator
  itself, since the full boundary additionally applies the heuristic density
  layer, which is not what that property is about.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exits 0 (1413 reviewed identities → 1413
  findings, no deltas).

## Prior repair evidence (windows/timeouts, equivalence, PIIMatch)

Four product-path security regressions extend the initial #74 evidence:

- Sentinel's real Warden scans a pathological reject pattern across overlapping
  windows, records a fail-closed timeout, and never hands a search more than the
  configured window; the fallback semantic phase gets the same product-path
  window bound and preserves a padded capture/full-conversation signal across
  windows without an unbounded regex.
- The complete Warden verdict is compared on the accelerated and stdlib fallback
  regex engines, rather than comparing only individual pattern APIs.
- Sentinel output redaction is paired with a `PIIMatch` masking assertion so the
  raw credential is absent from both the product result and match metadata.
- The prior semantic false positive is reproduced through `Sentinel.post_call`: a
  complete-object phrase before `capture` remains clean, while the ordered
  capture/full-conversation form remains blocked.

## Post-merge re-validation at head `8c7424edfc43`

Re-verified against the merged head (develop `8bb344e32` merged into the lane);
no test counts changed, so the deltas above stand:

- Vulture gate (CI args, `packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) exits 0 at the merged head: 1415 reviewed identities →
  1415 findings, `unclassified: 0`, `never_allowlist: 0` (the two extra
  identities over the 1413 recorded pre-merge come from develop, all classified).
- Alembic chain (prior formal-conformance failure `KeyError: '033'`):
  `alembic heads` → single head `036_audit_log_org_scope`, `alembic branches`
  → empty, revisions 033/034 unique
  (`033_project_membership_unique_per_principal`, `034_hitl_deadline_index`),
  chain linear 032→…→036_audit_log_org_scope; `pytest tests/migrations` 17
  passed. The KeyError was a revision-map construction failure, which these
  map-level checks rule out without a database.
- Battery at the merged head: `ruff check .` and `ruff format --check .` clean;
  mypy 712 source files clean; `pytest packages/maistro-core/tests/security`
  1263 passed / 19 skipped / 1 failed; `pytest formal/models/
  test_warden_semantic.py --hypothesis-seed=0` 12 passed; strategies +
  `test_warden_pii_bypass.py` 75 passed; `test_warden_regex_equivalence.py` 7
  passed unskipped (google-re2 installed).
- Known red, out of #74 scope, root-caused not fixed here:
  `test_log_redaction.py::test_install_is_idempotent`. pytest 9.1.1 (CI pins
  `pytest >=9.0.3,<10`) `catching_logs.__enter__` now attaches a
  `LogCaptureHandler` to every *non-propagating* logger, so during the call
  phase the fixture logger `maistro.test.redaction` gains two capture handlers
  with `ColoredLevelFormatter`; the second `install_log_redaction` call then
  correctly wraps those two and returns 2. The product is idempotent: an
  out-of-pytest repro returns 1 then 0, and the same test fails on the
  canonical clone and at the develop base (files byte-identical between base
  and head — the lane never touched them). Repair belongs to a log-redaction
  or test-infra lane.

## Independent re-validation at head `cad92981e` (second repair pass)

Re-executed the full battery from scratch, trusting no prior claims; head
`cad92981e` differs from `8c7424edfc43` only by this note file:

- `pytest packages/maistro-core/tests/security` → 1263 passed / 19 skipped /
  1 failed (only the documented `test_install_is_idempotent` red);
  `test_sentinel_policy.py` 43 passed; `test_warden_regex_equivalence.py` 7
  passed **unskipped** (`import re2` verified — the accelerated/fallback
  comparison really ran); warden/ + `test_pii_evasion_normalization.py` 70
  passed; strategies + `test_warden_pii_bypass.py` 37 passed;
  `formal/models/test_warden_semantic.py --hypothesis-seed=0` 12 passed.
- Gates: vulture (CI args) exit 0, 1415/1415, unclassified 0;
  `check-security-inventory.py` exit 0 (65 paths, 23 rows, 2 counted claims);
  `check-doc-links.py` exit 0; `check-suite-inventory.py` 13/13 suites;
  `ruff check .` + `ruff format --check .` clean; mypy 712 files clean.
- Alembic: `alembic history` constructs the full linear map
  034→035→035_thumb→036_cursors→…→040→036_audit_log_org_scope (single head,
  `alembic branches` empty, 033/034 unique) — exit 0; `pytest tests/migrations`
  17 passed.
- The `test_install_is_idempotent` mechanism was re-reproduced independently:
  fixture-phase install over 1 real handler returns 1, a second install with no
  new handlers returns 0 (product idempotent), and attaching two
  pytest-9-style capture handlers (plain formatters) before the second install
  makes it return 2 — exactly the documented pytest-interaction root cause.
  `test_log_redaction.py`, `log_redaction.py`, `redact.py`, `uv.lock` and
  `pyproject.toml` are all byte-identical develop-base↔head, so the red is
  provably pre-existing.

## Third re-validation at head `f153133ac` (driver log absent — full battery re-run)

The assigned driver produced no `check-*.log` files (manifest `checks: []`), so
the battery was re-executed from scratch at head `f153133ac` (develop
`750edd84d` merged onto the second-pass head), trusting no prior claim:

- `ruff check .` and `ruff format --check .` clean; the full AGENTS.md mypy
  command (all six package `src` trees) clean — 712 source files.
- Exact-debt-ledger CI steps re-run locally: `check-ratchet-provenance.py` OK,
  `check-shipped-surface-truth.py` OK, `check-vulture-baseline.py` (CI args)
  exit 0 — 1415 reviewed identities → 1415 findings, `never_allowlist: 0`,
  confirming the removed `semantic_tool_poisoning_scan` stays removed at this
  head.
- `check-security-inventory.py` exit 0 (65 cited paths resolve, 23 inventory
  rows match the code), so SECURITY.md's resource-limit rows and the
  product-path-evidence sections still point at real tests/constants.
- `pytest packages/maistro-core/tests/security/test_sentinel_policy.py
  tests/security/test_warden_pii_bypass.py
  tests/security/test_warden_regex_equivalence.py
  tests/security/sentinel/test_pii_evasion_normalization.py` → 69 passed;
  `test_warden_regex_equivalence.py -v -rs` → 7 passed, none skipped
  (google-re2 installed), including the whole-verdict product-path engine
  comparison; the seven `test_post_call_real_warden_*` and
  `test_post_call_pii_match_value_is_masked_on_product_path` nodes pass by
  name.
- `pytest packages/maistro-core/tests/security` → 1263 passed / 19 skipped /
  1 failed; the failure is `test_log_redaction.py::test_install_is_idempotent`,
  re-confirmed pre-existing: the same test fails on the clean canonical clone
  (separate checkout, `57ddca502`), and base↔head diff on
  `test_log_redaction.py`/`log_redaction.py`/`redact.py`/`pyproject.toml` is
  empty (the only delta is `uv.lock` gaining a hive-conductor `cryptography`
  dep from the develop merge — unrelated to pytest).
- `pytest packages/maistro-core/tests/agents/strategies/test_direct.py
  test_react.py` → 28 passed; `pytest formal/models/test_warden_semantic.py
  --hypothesis-seed=0` → 12 passed.
- Alembic (prior PR #1463 conformance failure): `alembic heads` → single head
  `036_audit_log_org_scope`, `alembic branches` → empty, `alembic history`
  constructs the 43-revision linear map without `KeyError: '033'`, and exactly
  one file exists each for `033_project_membership_unique_per_principal` and
  `034_hitl_deadline_index`; `pytest tests/migrations` → 17 passed / 79
  skipped (DB-gated).
- Product-path reachability re-checked in source: `container.py` wires the
  container Warden into `Sentinel`, and `orchestrator/output_security.py`
  defaults the output gate to the real `Warden()` — the tested path is the one
  production runs. `pii_filter.py` `scan_for_pii` and `redact` both operate on
  the same `normalize_for_scan` view, matching the offset-consistency
  regression tests.
