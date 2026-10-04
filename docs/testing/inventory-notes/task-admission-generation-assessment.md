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

## CI-repair round at 927a3adf8 (2026-10-04)

The merge-queue run at this head failed four jobs. Root-caused locally with
each job's own invocations:

- `exact-debt-ledger` (vulture-ratchet.yml): the named vulture repair
  procedure has an empty fix-list — `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exits 0 with 1342
  reviewed identities -> 1342 findings, so `quality/vulture-baseline.json` is
  exact and untouched. The job actually fails earlier, in
  `check-ratchet-provenance.py`: its `reachability` and
  `reachability-dispositions` sub-gates compare the candidate ledgers against
  the trusted base, and `maistro.runs.admission_identity` (baselined and
  dispositioned by the #1851 sibling commit 9a15e6830) plus
  `maistro.tasks.admission_generation` are NEW unreachable/dispositioned
  identities the base never authorized. That is the two-merge rule doing its
  job (a candidate ledger row cannot approve itself); it stands as the
  documented blocker above.
- `Quality gate (Pillars 1–4, 7, 8)`: `check-reachability.py` and
  `check-radon-baseline.py` fail as documented above. `check-convergence-matrix.py`
  additionally failed because the #1851 sibling's baseline row moved
  `maistro.runs.admission_identity` into the Run / NodeRun / Attempt
  lifecycle row while the matrix still said `none`. Repaired here the way
  the gate itself prescribes — the row now says `few` and names the
  baselined-unreachable contract leaf — a planning-surface doc update, not a
  waiver; the gate still recomputes shares from the live import graph and
  `tests/test_check_convergence_matrix.py` passes (60/60).
- `test` (ci.yml root suite): 4 failures, all one root cause — the new
  module is not in the reachability baseline
  (`test_check_reachability.py::test_baseline_matches_the_tree`, both
  `test_reachability_baseline_identity.py` gate-identity tests) plus the
  convergence-matrix drift test fixed above. The three baseline-identity
  failures stand as the documented blocker; they disappear only when the
  #1845 integration consumer wires the module (or a base-landed
  authorization lands first).
- `Coverage gate`: replicated CI's per-file diff-coverage locally
  (`coverage run --branch --source=packages/maistro-core/src/maistro -m
  pytest packages/maistro-core/tests`, then `check-diff-coverage.py
  coverage.xml --base 91996e19`): both new modules are at or above 90% lines
  / 80% branch arcs, exit 0. The CI job failed in its root-suite coverage
  producer, which runs the same `tests/` suite as the `test` job — same
  reachability root cause, no coverage defect.

One local-only red herring:
`packages/maistro-core/tests/test_container_postgres.py::
test_an_unreachable_server_is_an_error_not_a_fallback` needs a reachable
Docker daemon (passes with `DOCKER_HOST` set; green in CI, which has one).
