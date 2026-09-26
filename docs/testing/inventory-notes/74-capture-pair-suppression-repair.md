---
inventory-delta:
  packages/maistro-core/tests: +1
---
# 74 capture-pair suppression repair (post-verify round)

Verify round a32cb60a (NEEDS-REPAIR) found a product-path false negative in
`detector._scan_semantic_windowed`: once any earlier full-conversation phrase
was seen, the windowed carry could never record a later capture→object pair
(the `if not has_full_conversation` guard froze both `has_ordered_capture`
and `has_capture_action`), and the per-window helper compared the capture
verb against the *first* conversation phrase rather than against the
existence of any later pair. Reproduced through `MasterOrchestrator.execute`:
the legacy single-regex rule matched the output, Warden returned clean, and
the canonical work item completed (completed=1, failed=0, status=passed).

## Fix

- `security/warden/semantic.py`: `semantic_tool_poisoning_capture_signals`
  and `semantic_tool_poisoning_capture_ordered` are replaced by
  `semantic_tool_poisoning_capture_positions`, which returns the first
  capture-verb start and the last complete-object start. Ordering is
  `first capture < last conversation` — exactly the legacy
  `(?:capture|export|include).*(?:full|complete|entire)\s+...` verdict, with
  bounded patterns instead of the `.*` hot path.
- `detector._scan_semantic_windowed` aggregates those positions across the
  overlapping windows (offset+start is a true global position because every
  phrase is far shorter than the 2KB overlap), so a pair split across windows
  is flagged and a prepended benign object phrase suppresses nothing, while
  an object that merely precedes the capture verb with no later object stays
  clean.

## Test delta (measured +1 node ID, `scripts/check-suite-inventory.py`)

- `tests/orchestrator/test_output_security_gate.py` (+1):
  `test_real_warden_semantic_capture_pair_after_earlier_object_is_refused`
  reproduces the verifier finding end to end — output whose later
  capture→full-conversation pair follows an earlier benign object mention,
  pinned against the legacy regex (asserted to match) and refused by the real
  `Warden` behind `build_output_security_gate` through
  `MasterOrchestrator.execute` (failed=1, static refusal, blocked outcome
  metadata, canonical work item FAILED).
- `tests/security/test_sentinel_policy.py` (net 0):
  `test_post_call_real_warden_preserves_capture_ordering` rewritten to pin
  both sides of the repaired contract — object-before-verb with no later
  object stays clean (single-window and padded multi-window), and the two
  texts that previously asserted clean (they contain a capture verb followed
  by a later complete object: "…should capture the entire record.") now
  assert refusal, matching the legacy rule the verifier used as reference.
  The fallback-window monkeypatch target moved from
  `semantic_tool_poisoning_capture_signals` to
  `semantic_tool_poisoning_capture_positions` (the helper the product path
  now calls per window).

Develop sync (origin/develop at ca4caec7d) was merged first: the #66
multi-view/context scanning architecture is kept, with the #74 windowed
semantic phase retained on the primary structural view instead of develop's
whole-text `semantic_tool_poisoning_scan` call, and `BaseAgent
._sanitize_tool_result` keeps the develop context kwarg inside the #74
fail-closed ImportError handler.

Known pre-existing failure (not this lane): `tests/security/test_log_redaction
.py::test_install_is_idempotent` fails at pristine origin/develop ca4caec7d
(probe worktree, no local changes), so it is a develop-side test-isolation
defect, not a regression of this repair.

## Focused post-repair validation (5403979a)

The product-path acceptance bundle was rerun at the repaired head:
`test_direct.py`, `test_react.py`, `test_base.py`, `test_output_security_gate.py`,
`test_sentinel_policy.py`, `test_warden_pii_bypass.py`, and
`test_warden_regex_equivalence.py` completed with **196 passed**. This includes
the real `MasterOrchestrator.execute` timeout/window and capture-ordering
regressions, governed-executor PII masking/fail-closed behavior, and the
accelerated-versus-stdlib Warden verdict comparison. `ruff check .`, `ruff
format --check .`, `check-compliance.py`, `check-security-inventory.py`, and
`check-suite-inventory.py --suite packages/maistro-core/tests` all passed.
The required vulture exact-debt command — the exact CI argv
`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (the form wired in
`.github/workflows/vulture-ratchet.yml` and `.github/workflows/quality.yml`) —
passed (exit 0) with 1,412 reviewed identities -> 1,412 findings, zero
unclassified identities, and zero never-allowlisted findings, measured at
`5403979a` and re-measured at this round's develop-sync merge head;
therefore no ledger amendment was needed or made in this CI-repair round.
Reconciliation of the prior verifier's exit-1 report: that run omitted the
`--exclude '*/third_party/*'` flag, scanning vendored upstream benchmark
sources under
`packages/maistro-evolve/src/maistro_evolve/benchmarks/third_party/` and
reporting 60 "new" identities (1472 findings) there. Those trees are
deliberately excluded by CI — `quality.yml` documents them as vendored
upstream source (Google's IFEval verifier, BFCL's AST checker) kept
byte-faithful — so the exclude-less result is out of the gate's scope, is
pre-existing develop-wide debt, and is not a regression of this lane; no
lane-touched `maistro-core` identity changed (1,412 = 1,412 at every
measured head).
