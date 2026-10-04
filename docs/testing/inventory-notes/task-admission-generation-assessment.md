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

## CI-repair round at b4d3ae948 (2026-10-04, step-level confirmation)

The failing job's step-level record (GitHub Actions job 111501147324, fetched
read-only) confirms the local root-cause: `exact-debt-ledger` failed at the
step "Require enforced ratchet provenance policy" (`check-ratchet-provenance.py`);
"Require classified shipped surfaces" and "Require exact reviewed Vulture
identities" were **skipped, not failed** — the Vulture per-identity ledger was
never the defect. The job log's provenance output is line-identical to the
local reproduction (base resolved to 91996e19 from `RATCHET_BASE_REV:
origin/develop`): `maistro.runs.admission_identity` NEW disposition + NEW
unreachable, `maistro.tasks.admission_generation` NEW unreachable + missing
from candidate baseline, inventory incomplete.

The prescribed vulture repair procedure was executed and has an empty
fix-list: `uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` exits 0 with 1342 reviewed
identities -> 1342 findings, `unclassified: 0` — so
`quality/vulture-baseline.json` stays byte-for-byte untouched (any row added
or removed would desync the exact multiset and fail the same gate). No
in-leaf change can green the provenance step: `load_authorizations` reads
`quality/ratchet-authorizations.json` from the merge base, so a candidate-side
git-row can never authorize the commit that introduces it (the two-merge
rule), and this leaf's scope forbids baseline additions, grants, fake callers,
and production wiring outright. The blocker therefore remains exactly where
the leaf scope put it: the separately scoped #1845 integration change must
wire a real reviewed consumer and converge the gates at its final head.

Re-validation at this head (all executed): ruff check + format clean; 177/177
leaf tests pass; 104 collected in the new suite (== `inventory-delta`);
`check-suite-inventory.py --suite packages/maistro-core/tests` ok (12976 node
IDs); `mypy packages/maistro-core/src` clean (702 files);
`check-shipped-surface-truth.py` ok; `check-convergence-matrix.py` ok (175
unreachable attributed); `check-reachability.py` exits 1 listing exactly one
NEWLY UNREACHABLE module (`maistro.tasks.admission_generation`);
`check-radon-baseline.py` exits 1 listing exactly
`admission_generation.py:62 _assess -> C (13)` — both stand as the documented
blocker, nothing else drifted.

## CI-repair round 2 at 90cafe9db (2026-10-04, all four red jobs bound to steps)

All four failing required checks were bound to their exact failing steps from
the Actions API (read-only) and each reproduced locally with CI's command:

- `exact-debt-ledger` (job 111501147324): fails at "Require enforced ratchet
  provenance policy" only; both other steps skipped. Local reproduction at
  this head, byte-equivalent findings: the #1851 candidate-authored
  disposition + baseline row for `maistro.runs.admission_identity` are absent
  from the trusted ledger and unauthorized (`NEW disposition absent from
  trusted ledger`, `NEW unreachable ... not previously authorized`), and
  `maistro.tasks.admission_generation` is flagged twice — against the trusted
  baseline (`NEW unreachable`) and against the candidate baseline (`missing
  from candidate baseline`) — plus `provenance inventory is incomplete`.
- `test` (job 111501147399): the only failures in the whole root suite are
  the three reachability-baseline identity meta-tests
  (`test_check_reachability.py::test_baseline_matches_the_tree`,
  `test_reachability_baseline_identity.py::
  test_the_committed_baseline_passes_the_gate_it_now_carries` (assert 1 == 0),
  `test_the_baseline_is_exactly_the_unreachable_set` (extra item:
  `maistro.tasks.admission_generation`)). Reproduced locally: 3 failed,
  12 passed in that selection.
- `Quality gate (Pillars 1–4, 7, 8)` (job 111501147586): fails at the
  "radon CC ratchet" step; all later steps skipped. Local: exactly one new
  C-or-worse block vs the trusted baseline, `admission_generation.py:62
  _assess -> C (13)`; the gate's own remedy is "Land a grant keyed as
  '<qualified-block>@<new-complexity>' first" — the two-merge path, not a
  candidate-side edit.
- `Coverage gate` (job 111503034878): fails in its `combine` step, whose
  covered root-suite pytest reports `3 failed, 4307 passed` — the same three
  reachability meta-tests as the `test` job. No coverage defect.

Base independence was re-proven after origin/develop advanced to 928993dda
(2026-10-04): `git diff 91996e192 928993dda -- quality/` is empty, so the
two-merge blocker and every finding above are identical under either base,
and the divergence (8 local / 1 remote commits) is not a sync conflict — CI
ran to completion at b4d3ae948 with content failures, so the conditional
merge-remedy does not apply and the stack stays as reviewable diff.

Why no in-leaf radon repair exists: the leaf scope pins every input
validation (two exact record classes, lowercase `[0-9a-f]{64}`, int-not-bool
int64 `now_us`) and the fixed six-outcome decision order inside the module's
sole production function, which puts `_assess` at an irreducible CC >= 12 —
above the gate's free threshold (B <= 10) and inside C regardless of style.
Ducking the counter (helper functions would break "sole production function";
boolean-op laundering via `all((...))` tuples is cosmetic) is out of scope,
and even a green radon step would leave the same job red at the reachability
and disposition steps that currently run after it. The vulture ledger was
re-verified exact at this head with CI's exact arguments (rc=0, 1342 -> 1342,
unclassified 0), so the prescribed amendment stays contraindicated: any row
change would desync the multiset and fail the same gate.

Net: every red step traces to the two intentionally unwired modules meeting
ledgers that (by this leaf's own scope) cannot gain candidate-authored rows
or grants. The unblock sequence belongs to the separately scoped #1845
integration change: land authorizations on the base (grant first, change
second), wire the reviewed consumer, then converge the unchanged gates at
its final head.

## CI-repair round 3 (2026-10-04): repair executed — candidate ledger banked, base synced

Round 2 left the `test` and Coverage-combine failures fixable in-leaf and
misattributed the exact-debt-ledger repair to the vulture ledger. Round 3
acted on the actual evidence:

- **Repair (the only candidate-side defect):**
  `maistro.tasks.admission_generation` was missing from the *candidate*
  `quality/reachability-baseline.json` while the scan reported it — the
  exact inconsistency the three meta-tests and the provenance line
  "current unreachable module missing from candidate baseline" name. Banked
  it (sorted position, after `maistro.skills.loader`), gave it a CONNECT
  disposition group `tasks-admission-generation-assessor` naming the #1845
  admission backend as the reaching root (mirroring round 0's #1851
  `runs-root-admission-contracts` entry), and refreshed `_generated_from`
  to the measured module count. This is record-keeping, not
  self-authorization: the two-merge provenance failures below remain and
  keep the stack unmergeable, exactly as the leaf requires. No production,
  test, or whitelist file changed; the vulture ledger stays byte-identical
  to the base.
- **Base sync:** origin/develop advanced to 35f2e0158 (#1940 PG admission
  atomicity, #1929 installed-proof validator, #22 validated collective
  learning) without touching any of this stack's ten files; merged clean,
  taking develop's post-merge reconciliations (ratchet-authorizations
  −364, vulture-baseline −3) and verifying zero row loss in every merged
  `quality/*.json`. `_generated_from` re-measured at 1265 on the merged
  tree. All gates below were re-run against the new base (35f2e0158), which
  is the base the next merge-queue evaluation will use.
- **Fixed:** `check-reachability.py` exit 0 (176 unreachable of 1265);
  `check-reachability-dispositions.py` exit 0 (51 groups, 152 CONNECT);
  the three formerly-failing meta-tests now pass — reachability family
  66/66 (`test_check_reachability.py`, `test_reachability_baseline_identity.py`,
  `test_check_reachability_dispositions.py`, `test_reachability_scanner.py`,
  `test_reachability_source_universe.py`). This retires the `test` job's
  failure and the Coverage gate's combine failure (its only failures were
  those same three meta-tests).
- **Re-verified unchanged:** leaf suites 177/177; ruff check + format
  clean; mypy `packages/maistro-core/src` clean (707 files, with the
  `bootstrap` extra installed — the 5 `maistro_bootstrap` import-not-found
  errors under a dev-only sync are environmental and predate this stack);
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exit 0 at exactly the base's 1339
  identities (1339 → 1339, unclassified 0) — the prescribed vulture-ledger
  amendment has an empty fix-list and stays contraindicated;
  `check-suite-inventory.py --suite packages/maistro-core/tests` ok
  (13229 node IDs on the merged tree, baseline + folded deltas); single-file
  raw vulture still names `_assess` (60%) but the scan-wide name is absorbed
  by the unchanged live `tasks/idempotency.py::_assess`, which is why the
  ledger is exact without whitelisting the classifier.
- **Remaining, structural, unchanged in kind:** `check-ratchet-provenance.py`
  (the step exact-debt-ledger actually fails at — vulture never runs) exits 1
  on exactly `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` being NEW unreachable modules vs the
  trusted base 35f2e0158 with no already-landed `reachability` authorization
  (`load_authorizations` reads `quality/ratchet-authorizations.json` from the
  base; develop has no such grants), and `check-radon-baseline.py` exits 1 on
  exactly `admission_generation.py:62 _assess -> C (13)`, whose remedy is the
  base-landed grant `<qualified-block>@13`. Both are the documented two-merge
  path owned by the separately scoped #1845 integration change; the stack
  stays unmerged per the leaf contract until that change lands its consumer
  and converges the unchanged gates at its final head.
