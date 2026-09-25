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

## Fourth pass at head `0d6e45f9f` (driver log absent — battery re-run; salvaged hot-path repair)

The assigned driver again produced no `check-*.log` files, so the battery was
re-executed at head `0d6e45f9f` (develop `60862b6c5` merged). One new
salvaged repair from the previous worker session is included (no new test
nodes; `test_react.py` assertions strengthened in place):

- **PIIMatch/security-review hot-path finding — security block misrecorded as
  success.** `ReactStrategy._reason` returned
  `[BLOCKED: output sanitization unavailable]` when the PII filter import
  fails, but `BaseAgent`'s `tool_had_failures` predicate
  (`agents/base.py`, `startswith("Error")` or `"error" in result[:50].lower()`)
  matches neither branch on that string, so a fail-closed security block was
  persisted as a successful tool Outcome (skipping RCA and poisoning
  success-count traces). Fix prefixes `Error: `; the updated
  `test_reason_pii_filter_import_error_blocks_unredacted_result` asserts both
  the exact string and the predicate shape. Evidence that the old string
  failed the predicate: it contains no `Error` prefix and no `error` in the
  first 50 chars, so both disjuncts are false.
- COMPLIANCE.md AT-01 row now also cites the decay/promoter-gate test paths;
  both exist and pass (`tests/memory/episodic/test_decay.py` +
  `tests/memory/learnings/test_promoter_gate.py` → 24 passed).
- Battery at this head: `ruff check .` + `ruff format --check .` clean;
  full AGENTS.md mypy command → 713 source files, no issues;
  `pytest tests/security` → 1269 passed / 19 skipped / 1 failed (only the
  documented pre-existing `test_install_is_idempotent` pytest-9 red);
  `test_warden_regex_equivalence.py -rs` → 7 passed, none skipped (`import
  re2` verified under `uv run`); window/timeout + PII-bypass product-path
  nodes → 18 passed; strategies → 66 passed;
  `formal/models/test_warden_semantic.py --hypothesis-seed=0` → 12 passed.
- Gates: `check-security-inventory.py` exit 0 (65 paths, 23 rows);
  `check-vulture-baseline.py` (CI args) exit 0, 1415/1415, candidate head
  `0d6e45f9ff30` vs base `60862b6c5eb1`; `check-doc-links.py` exit 0;
  `check-suite-inventory.py` 13/13.
- Alembic re-checked: `alembic heads` → single head
  `036_audit_log_org_scope`, `alembic branches` → empty, exactly one file each
  for 033/034 — the prior duplicate-revision conformance failure stays
  resolved.

## Fifth validation pass (435c24cca + format repair, driver checks absent)

The 435c24cca job manifest listed `checks: []` and shipped no `check-*.log`
files, so every acceptance check below was re-executed locally.

- **Finding (fixed here):** `ruff format --check .` failed at 435c24cca —
  `test_sentinel_policy.py` (introduced by that commit) had two overlong lines
  in `test_post_call_real_warden_windows_semantic_fallback_input`. This was the
  only file in the tree flagged. Repair is `ruff format` on that file only
  (pure whitespace/line-splitting, 7+/2−); no assertion changed.
- Product-path window/timeout nodes:
  `test_sentinel_policy.py` → **44 passed** at the repaired head, including
  `test_post_call_real_warden_times_out_pathological_regex`,
  `::test_post_call_real_warden_windows_pathological_reject_input`,
  `::test_post_call_real_warden_windows_large_fallback_input`,
  `::test_post_call_real_warden_windows_semantic_fallback_input`,
  `::test_post_call_real_warden_windows_large_fallback_semantic_input`,
  `::test_post_call_real_warden_preserves_padded_semantic_signal`,
  `::test_post_call_real_warden_preserves_capture_ordering`, and
  `::test_post_call_pii_match_value_is_masked_on_product_path`.
- Engine equivalence: `uv run python -c "import re2"` OK and
  `_regex.re2_available() is True` under `uv run`, so
  `test_warden_regex_equivalence.py -rs` → **7 passed, 0 skipped**
  (accelerated corpus is live, not vacuous).
- `test_warden_pii_bypass.py` → 9 passed; strategies (`test_react.py` +
  `test_direct.py`) → 28 passed; `formal/models/test_warden_semantic.py
  --hypothesis-seed=0` → 12 passed.
- Full `pytest packages/maistro-core/tests/security` → 1270 passed / 19
  skipped / 1 failed. The single red is the documented pre-existing
  `test_install_is_idempotent` pytest-9 red: re-verified out of scope at this
  head — `test_log_redaction.py`, its `captured` fixture, `log_redaction.py`,
  `uv.lock`, and both `pyproject.toml`s are byte-identical between develop base
  `03c8ba83a`, merge base `60862b6c5`, and HEAD, so the failure exists
  identically at base (pytest 9.1.1 in both trees).
- Battery: `ruff check .` clean; `ruff format --check .` → 2533 files clean
  (after the repair above); `check-security-inventory.py` exit 0 (65 paths,
  23 rows); `check-vulture-baseline.py` exit 0 (the removed
  `semantic_tool_poisoning_scan` stays pruned from both ledgers);
  `check-doc-links.py` exit 0 (1161 files, 0 broken); `check-suite-inventory.py`
  exit 0; `alembic heads` → single head `036_audit_log_org_scope`.

## Sixth validation pass at head `8a7323aa` (driver checks absent — battery re-run after the develop merge)

The assigned driver again produced no `check-*.log` files (manifest
`checks: []`), so the battery was re-executed at head `8a7323aa` (develop tip
`03c8ba83a` merged; local history also strictly contains `origin/auto-74`
`c11969b54`, so the earlier push non-fast-forward block is resolved in-tree —
the next driver push fast-forwards). Trusting no prior claim:

- Product-path window/timeout nodes (`test_sentinel_policy.py -k
  "post_call_real_warden or pii_match"`) → **8 passed**; the targeted file set
  (`test_sentinel_policy.py` + `test_warden_pii_bypass.py` +
  `test_warden_regex_equivalence.py` +
  `sentinel/test_pii_evasion_normalization.py`) → **70 passed**.
- Engine equivalence: `import re2` OK and `_regex.re2_available()` True under
  `uv run`; `test_warden_regex_equivalence.py -rs` → **7 passed, 0 skipped**;
  `test_warden_product_path_matches_with_fallback_engine` compares full
  `(clean, blocked, flags)` tuples over >10k-probe corpus + a 7k-token padded
  cross-window payload on both engines.
- Strategies (`test_direct.py` + `test_react.py`, incl. the
  `test_reason_pii_filter_import_error_blocks_unredacted_result` security-block-
  as-failure pin) → **28 passed**; `formal/models/test_warden_semantic.py
  --hypothesis-seed=0` → **12 passed**.
- Full `pytest packages/maistro-core/tests/security` → **1270 passed / 19
  skipped / 1 failed**; the single red is the documented pre-existing
  `test_install_is_idempotent` pytest-9 interaction: re-confirmed at this head
  by empty base↔head diffs (`git diff 03c8ba83a..HEAD` and
  `git diff 84402748f..HEAD`) on `test_log_redaction.py`, `log_redaction.py`,
  `redact.py` — the failure reproduces identically and is out of #74 scope.
- CI-repair step run exactly as briefed: `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0,
  1415 reviewed identities → 1415 findings, `unclassified: 0`,
  `never_allowlist: 0` (candidate `8a7323aa` vs base `03c8ba83a`) — the prior
  `semantic.py:136 semantic_tool_poisoning_scan` exact-debt finding stays
  resolved (function removed; composition lives in the product path
  `detector._scan_semantic_windowed`, exercised by the tests above). No ledger
  amendment was needed: nothing new is unbanked and nothing had to be granted.
- Prior PR #1463 alembic finding stays resolved: `alembic heads` → single head
  `036_audit_log_org_scope`, `alembic branches` → empty, exactly one file each
  for 033/034; `pytest tests/migrations` → 17 passed / 79 skipped.
- Gates at this head: `ruff check .` clean; `ruff format --check .` → 2542
  files clean; `check-security-inventory.py` exit 0 (65 cited paths resolve,
  23 inventory rows match); `check-doc-links.py` exit 0;
  `check-suite-inventory.py` exit 0; full AGENTS.md mypy command → **713
  source files, no issues**. SECURITY.md (`:123-129`) and COMPLIANCE.md
  (`:38`, `:55-58`) cite the product-path test nodes, not constants alone.

No code changes were needed in this round: every prior #74 finding is already
fixed at this head and the full battery is green apart from the documented,
provably pre-existing pytest-9 log-redaction red. This pass adds evidence
only.

## Pass 7: develop-sync conflict resolution + full battery re-run (head 88f6fa900)

Previous block resolved: the worktree carried an in-progress
`git merge origin/develop` (MERGE_HEAD `84402748f`) with one conflict in
`COMPLIANCE.md`. develop (#1464) had replaced the document with the
evidence-first registry format (`quality/compliance-registry.json` +
`scripts/check-compliance.py`), while auto-74 had rewritten the old mapping
table with product-path citations. Resolution (merge commit `88f6fa900`):

- develop's registry-backed format wins (its checker rejects the old table);
- the #74 "Product-path evidence for security claims" section is re-added
  outside the registry markers, citing the executed Sentinel/Warden nodes;
- the machine-checked registry rows for OWASP-AT-01/OWASP-AT-02 now cite the
  product-path tests (`test_sentinel_policy.py`,
  `test_warden_regex_equivalence.py`) in `test_refs`, with claim text synced
  byte-exactly between registry and document.

Evidence at this head:

- `scripts/check-compliance.py` → exit 0 ("compliance registry and
  COMPLIANCE.md are valid"); `tests/test_check_compliance.py` → **97 passed**.
- Acceptance nodes: `test_sentinel_policy.py -k "post_call_real_warden or
  pii_match"` → **8 passed** (timeout + window + padded-semantic + capture
  ordering + PIIMatch masking on the product path);
  `test_warden_regex_equivalence.py -rs` → **7 passed / 0 skipped** with
  `re2_available() == True` (accelerated vs fallback equivalence exercised,
  not skipped); `test_react.py::test_reason_pii_filter_import_error_blocks_-
  unredacted_result` + `test_warden_pii_bypass.py` → **10 passed**.
- `pytest packages/maistro-core/tests/security` → 1270 passed / 19 skipped /
  1 failed; the single red remains the documented pre-existing
  `test_log_redaction.py:82` pytest-9 interaction (file unchanged since the
  initial release; `git diff 29b43bac3..88f6fa900` on it is empty).
- develop-touched surfaces from the merge: persistence + learnings → **599
  passed / 169 skipped**; hive HITL/dag tests → **46 passed**;
  strategies + `formal/models/test_warden_semantic.py` +
  `formal/models/test_sentinel_policy.py` → **92 passed**.
- Gates: `ruff check .` clean; `ruff format --check .` → 2550 files clean;
  `check-security-inventory.py` exit 0 (65 paths / 23 rows);
  `check-doc-links.py` exit 0; `check-suite-inventory.py` exit 0;
  `check-ratchet-provenance.py` exit 0 (all 10 ratchets, candidate
  `88f6fa900` — includes the new compliance-registry consumer);
  full AGENTS.md mypy command → **715 source files, no issues**.
- CI-repair step re-run exactly as briefed: `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0,
  **1414 reviewed identities → 1414 findings, unclassified 0,
  never_allowlist 0** (candidate `88f6fa900` vs base `84402748f`). No ledger
  amendment needed: nothing unbanked, nothing dead found.
