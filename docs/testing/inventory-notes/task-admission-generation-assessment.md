---
inventory-delta:
  packages/maistro-core/tests: +104
---
# #1852 admission-generation classifier evidence

Adds the inactive pure classifier
`packages/maistro-core/src/maistro/tasks/admission_generation.py` (sole
production function `_assess`) and its contract suite
`packages/maistro-core/tests/tasks/test_admission_generation_assessment.py`.
No production module imports the new module in this leaf, `maistro.tasks.__init__`
is unchanged, and no other test file moved, so no other suite count changes.

The suite pins the #1852 decision order with fixed instants only (no sleeps,
no free-running clocks, no database): every matrix row at its exact boundary
and ±1 µs — inclusive expiry (`REPLACE_EXPIRED` at `expires_at_us == now_us`,
one µs earlier still classifying inside the window), fingerprint mismatch ahead
of binding/legacy/lease inside the window, binding winning over lease status
and the unread `acknowledged_at_us`, v2 unbound lease boundaries
(`PENDING` at lease −1 µs, `TAKEOVER` at lease and lease +1 µs), unbound legacy
rows never takeover-eligible (`LEGACY_UNRESOLVED`, including an
out-of-window lease), and input validation (`ValueError` for non-record
shapes including the live flow's `AdmissionRecord`, non-`[0-9a-f]{64}`
fingerprints, bool/float/out-of-range `now_us`; signed-int64 boundaries
accepted). Purity is asserted structurally: `time.time`/`monotonic`/
`perf_counter`/`sleep` are replaced with raising stand-ins around the call
(restored inside the test body, before pytest's own teardown timing), caplog
stays empty, and records compare equal to pristine copies afterwards.

The unchanged live four-variant loop in `maistro.tasks.idempotency` is called,
not edited: `_AssessmentKind` still has exactly its four values, live `_assess`
and `_takeover_guard_holds` still answer the live contract on mirrored rows
(expired matching key → `"takeover"`, expired mismatch → `"takeover"`), while
the new classifier distinguishes `REPLACE_EXPIRED` on the same stories —
proof the separate module path activated no new variants in the live loop.

## Explicit merge blocker (documented, not repaired here)

This leaf is not independently mergeable, by design. The new module is
newly unreachable from any process entry point, so the unchanged gates fail
at this head in exactly the way the leaf scope predicts; no baseline addition,
disposition, or grant was added for it (none is permitted for this leaf), and
no `IdempotencyKeyMismatch`/HTTP mapping was touched. Gates run with CI's
invocations (`uv sync --locked --all-extras` first, as `quality.yml` does):

- `check-reachability.py` exits 1 listing exactly one new unreachable module,
  `maistro.tasks.admission_generation` (176 live vs 175 baselined);
  `tests/test_check_reachability.py::test_baseline_matches_the_tree` fails for
  the same single-module delta and nothing else.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exits 0: 1342 reviewed identities -> 1342 findings, no
  new identity (the name-based scanner sees `_assess` used by the live flow's
  identically named function).
- `check-radon-baseline.py` exits 1 with exactly one new identity,
  `admission_generation.py:62 _assess -> C (13)` — unauthorizable in-leaf
  (a grant cannot approve the change that introduces it), so it is left
  standing for the integrating change.

A later, separately scoped #1845 integration change must land the real
reviewed runtime consumer and pass the unchanged full quality gates at its
exact final head, including these tests and this note (banking the radon
identity via its own pre-landed grant, and pruning the reachability entry the
moment the consumer wires the module).
