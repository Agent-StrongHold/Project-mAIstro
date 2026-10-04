# Formal Invariant Inventory — evidence rules (#410)

Every counted invariant in `formal/models/` must be able to fail: it states a
property of the *implementation's* observable behavior that has a realistic
counterexample class, and each one has been demonstrated to fail against a
concrete mutant. Invariants that merely restate a machine's own bookkeeping
(`counter >= 0` on a counter the machine itself increments), assert the empty
statement, or re-evaluate the implementation against itself are **rejected**
from the evidence counts: they add green signal without constraining behavior.

Parent issue: #410 (initiative #452; CI governance owner #160).

## Evidence rules

An invariant is **counted** only if all of these hold:

1. **Independent oracle.** The property is expressed against an independent
   model, a documented contract (docstring / ADR), or a constructive input
   class — never against the same value the implementation just produced.
2. **Counterexample class documented.** The docstring names a realistic
   defect that the property detects.
3. **Demonstrated mutant.** A concrete mutation of the implementation makes
   the invariant's model file fail (`pytest formal/models/<file> -q
   --hypothesis-seed=0`), while the unmutated suite passes 664/664.

## Counted invariants (post-#410)

| # | Model | Invariant / property | Counterexample class | Demonstrated mutant (observed result) |
|---|-------|----------------------|----------------------|----------------------------------------|
| 1 | I1 `test_strike_escalation.py` | `counter_matches_model` (+ per-rule post-conditions on `record_violation`/`remove_strikes`) | Tracker loses a removal clamp, records a violation without counting it, or double-counts — stored counter diverges from the machine's independent model | M1: lockout shifted from strike 2 to strike 3 → **3 failed** |
| 2 | I1 | `escalation_ladder_consistent` | A struck account left at `normal` scrutiny (strikes silently ignored) or a level off the documented ladder | M2: `unlock` resets scrutiny to `normal` → **3 failed** |
| 3 | I1 | `enable` rule post-condition (was empty `pass` invariant `enable_clears_disabled_and_lock`) | `enable()` clears the disable flag but leaves the lock in place | M3: `locked_until = None` removed from `enable` → **3 failed** |
| 4 | I10 `test_gate_processing.py` | `tracker_matches_model` (+ lock short-circuit transitions in both rules) | Gate records a strike on clean input, records two strikes per block, or keeps striking an already-locked account | M4: strike recording moved to every input → **7 failed** |
| 5 | I-design `test_design_registry_state.py` | `registry_matches_transition_model` | Delete removes a protected T0 skill; register overwrites a built-in with a lower trust tier; any lost entry | M5: T0 delete protection removed → **1 failed** |
| 6 | I-design | `list_by_mode_partitions_registry` | `list_by_mode` filter inverted/wrong-mode: per-mode concatenation no longer partitions `list_all()` | M6: filter `==` → `!=` → **1 failed** |
| 7 | I18 `test_flag_response.py` | `built_response_carries_banner` | Flag → silently pass: builder returns content without the security banner or drops layer attribution | M7: `return original_content` (banner dropped) → **6 failed** |
| 8 | I22 `test_warden_detector.py` | `blocked_implies_not_clean` | Reject path fails open: `clean=True, blocked=True` (block metric incremented, verdict clean) | M8: reject return flipped to `clean=True` → **6 failed** |
| 9 | I22 | `not_clean_implies_named_flags` | Dirty verdict with no flags (unattributable block) | covered by M8's flag-tuple return → **caught** |
| 10 | I22 | `clean_implies_no_flags` | Clean verdict carrying flags (flags leak past an early return) | covered by M8 → **caught** |
| 11 | I20 `test_warden_sanitizer.py` | `output_has_no_zero_width_chars` (was empty `pass` invariant) | Zero-width substitution dropped: U+200B–U+200F/U+FEFF smuggle through | M9: zero-width regex disabled → **3 failed** |
| 12 | I20 | `output_is_a_sanitize_fixpoint` | One-pass-only whitespace collapse — re-sanitizing changes the output | M10: `\s+` → `\s\s` (pairs only) → **4 failed** |
| 13 | I12 `test_warden_semantic.py` | `scan_prescriptive_free_text` rule | False positive on descriptive security text: flagging on action+object without the prescriptive requirement | M11: `has_prescriptive and has_actions` → `has_actions` → **1 failed** |
| 14 | I12 | `flagged_implies_nonempty_flags` | `flagged=True` with empty flag list (unauditable verdict) | caught by M11 family |
| 15 | I11 `test_warden_heuristics.py` | `scan_benign_text` rule | Benign, instruction-free text flagged (threshold regression, overzealous vocabulary) | M12: `window` added to instruction tokens → **1 failed** |
| 16 | I11 | `flagged_iff_nonempty_flags` | Boolean and flag list disagree in either direction | caught by M12 family |
| 17 | I13 `test_pii_filter.py` | `last_matches_respect_canonical_bounds` (+ embedded-credential rule: overlap, redaction shred) | Span computed on a derived view (bounds exceed the canonical string the contract indexes); redactor leaves a reconstructable fragment of the secret | M16: match `end` off by one → **1 failed** |
| 18 | I14 `test_auth_provider.py` | `authentication_is_stateless` | Liveness: provider accumulates failure state (lockout after N bad keys) so the configured key stops authenticating; safety: prefix/fuzzy match accepts a wrong key | M15: `key.startswith(candidate_key)` prefix match → **1 failed** |
| 19 | I7 `test_auth_scopes.py` | `scopes_match_documented_expansion` | Wildcard expands to a strict subset of its category; invalid spec leaks a scope | M13a: wildcard drops one scope → **3 failed** |
| 20 | I7 | `has_scope_agrees_with_membership_both_ways` (over the FULL scope universe) | Fail-open `has_scope` (always True) fails on any non-member; fail-closed on any member | M13b: `has_scope` → `return True` → **4 failed** |
| 21 | I17 `test_quota_tracker.py` | `recorded_usage_matches_model` | Accumulator adds output tokens into the input bucket, drops a side of the sum, or miscounts requests — store diverges from the machine's independent accumulators | M14: `input_tokens += output_tokens` → **3 failed** |
| 22 | I5 `test_external_content.py` | `wrapped_output_positions_markers_correctly` (was empty `pass` invariant) | End marker emitted before/instead of the start marker; marker dropped — boundary contract broken | M17: `_START_MARKER`/`_END_MARKER` swapped in the parts list → **2 failed** |
| 23 | I8 `test_secret_equal.py` | `comparison_true_iff_identical` | Prefix of the secret compares True; case-folded match; always-True (auth bypass) or always-False (lockout) comparison | M18: `b.startswith(a) or compare_digest(...)` → **5 failed** |

## Rejected invariants (removed or rewritten; excluded from evidence)

These were the tautologies #410 inventory targets. None survives in the
counted set:

| Model | Old invariant | Why it could never fail |
|-------|---------------|--------------------------|
| I1 | `strike_count_never_negative` (`>= 0`) | `int >= 0` on a value the tracker itself clamps |
| I1 | `remove_strikes` rule `assert rec.strike_count >= 0` | same |
| I1 | `enable_clears_disabled_and_lock` | literally `pass` |
| I1 | `fresh_violation_escalation` | literally `pass` |
| I10 | `tracker_consistency` (`strike_count >= 0`) | `int >= 0` |
| design | `list_all_length_non_negative` (`len(...) >= 0`) | `len() >= 0` always |
| design | `registry_size_never_negative` | `len() >= 0` plus an unreachable `None` element check |
| I18 | `built_count_non_negative` | machine's own increment counter |
| I22 | `counts_consistent` (`clean_count >= 0`, `dirty_count >= 0`) | machine's own counters |
| I20 | `no_zero_width_chars` | literally `pass` |
| I20 | `sanitized_count_non_negative` | machine's own counter |
| I12 | `counts_non_negative` | machine's own counters |
| I13 | `match_count_non_negative` | machine's own accumulator |
| I14 | `failures_dont_exceed_attempts` | implied by the rules' own bookkeeping (each failure also counted an attempt) |
| I7 | `has_scope_consistent` | **self-referential**: iterated the identity's own scopes and asserted `has_scope(s)` — with `has_scope` implemented as `scope in self.scopes`, that is `s in S for s in S` |
| I17 | `total_equals_input_plus_output` | **self-referential**: re-derived `total == input + output` from the store's own entry fields — consistently-wrong recorders stayed green |
| I5 | `wrapped_always_contains_markers` | literally `pass` |
| I11 | `counts_consistent` (`flagged_count <= scanned_count`) | implied by the rules' own bookkeeping |
| I8 | `results_are_bool` | non-string results were already asserted `is False` by the rule before being stored |

## Informational invariants (kept as-is; explicitly excluded from evidence counts)

Trivially implied but retained as documentation of constructor wiring; they
are not counted as formal evidence:

- `test_auth_client.py`: `base_headers_contain_key/name/scopes` (values the
  machine itself passed to the constructor), `identity_property` (reference
  identity the machine itself assigned).
- `test_auth_scopes.py`: `identity_scopes_are_frozen` (type contract on the
  expansion output; kept because a mutant returning a mutable set fails it,
  but it constrains no behavioral property and is not counted).

## Reviewed and classified falsifiable (not changed by #410)

All remaining `@invariant()`/stateful properties were reviewed for this issue
and already satisfy the evidence rules (independent model or documented
contract): I2 `test_rate_limiter.py`, I3 `test_trust_boundary.py`,
I6 `test_sentinel_policy.py`, I9 `test_task_policy.py`, I15
`test_auth_registry.py`, I16 `test_session_store.py`, I19
`test_secure_random.py`, I21 `test_billing_cycle.py`, I23–I28 auth
provider/registry/client/cookie/composite/static-key models, I29
`test_sentinel_validator.py`, I30 `test_memory_scopes.py`,
`test_pipeline_integration.py`, `test_rsi_audit_trail_conformance.py`,
`test_rsi_rollback_conformance.py`, `test_run_lease_fence.py`.

## Method notes

- The mutant battery runs against a PYTHONPATH-shadowed copy of
  `packages/maistro-core/src` (plus `maistro-design` where noted), precedence
  verified via `module.__file__`; the worktree is not modified. Exceptions:
  M5/M6 mutate `maistro_design` in-tree under the documented
  backup → `cp` restore pattern (the design model bootstraps
  `packages/maistro-design/src` to `sys.path[0]`, which outranks PYTHONPATH);
  both restores were verified with `git diff --quiet`.
- Suite inventory: collection is unchanged by this issue (664 nodes before
  and after) — invariant bodies are not collected nodes.
