---
inventory-delta:
  packages/maistro-core/tests: +132
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

The unchanged live claim loop in `maistro.tasks.idempotency` is called,
not edited: live `_assess` and `_takeover_guard_holds` still answer the
live contract on mirrored rows (expired matching key → `"takeover"`,
expired mismatch → `"takeover"`), while the new classifier distinguishes
`REPLACE_EXPIRED` on the same stories — proof the separate module path
activated no new variants in the live loop. Since round 20 the mirrored
rows are built in the merged M1-B1 record shape (`df00785bb`: required
`claim_token`/`completed_at_us`, `admitted` ⇔ stamp ≠ 0) and pin the
merged loop's five-variant answer set (including `"ambiguous"`) — the
leaf still added none of them.

## Explicit merge blocker (documented, not repaired here)

This leaf is not independently mergeable, by design. The new module is
newly unreachable from any process entry point, so the unchanged gates fail
at this head in exactly the way the leaf scope predicts; no baseline addition,
disposition, or grant was added for it (none is permitted for this leaf), and
no `IdempotencyKeyMismatch`/HTTP mapping was touched. Gates run with CI's
invocations (`uv sync --locked --all-extras` first, as `quality.yml` does):

- `check-reachability.py` exits 1 listing the two leaf modules as NEWLY
  UNREACHABLE — `maistro.runs.admission_identity` (#1851 sibling) and
  `maistro.tasks.admission_generation` (this leaf); both
  `tests/test_check_reachability.py::test_baseline_matches_the_tree` and the
  two `tests/test_reachability_baseline_identity.py` gate-identity tests fail
  for that same two-module delta and nothing else (re-derived at round 13;
  earlier sections quote one module because the #1851 sibling had not landed
  yet when they were written).
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

(Round 6 supersedes the radon sentence above: the radon identity no longer
exists — `_assess` is rank B — and the grant path it described was never
sufficient anyway, because the Quality gate's xenon step carries a separate
module-rank failure no JSON grant can retire. See the round-6 section.)

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

## CI-repair round 4 (2026-10-05): missing required import-spy test added;
## full re-validation at aac9a08bc (base 31d891a5 merged)

Round 3 left one issue-scope gap: the required named test
`test_existing_live_claim_flow_does_not_import_v2_classifier` was covered
only behaviorally (live four-variant answers unchanged), not by the import
spy / dependency inspection the issue prescribes. Round 4 adds exactly that
to `test_admission_generation_assessment.py` (no production file touched): a
fresh-interpreter probe imports `maistro.tasks.idempotency` and
`maistro.tasks.queue` and asserts `"maistro.tasks.admission_generation" not
in sys.modules` (the test process has already imported the classifier, so
only a subprocess observes the live modules' own transitive imports), plus
an in-process check that neither live module's namespace binds the
classifier. Suite count 104 -> 105 (front-matter delta +105);
`check-suite-inventory.py --suite packages/maistro-core/tests` ok at 13442
collected node IDs.

Re-validation executed at this head, all green:

- `uv run pytest packages/maistro-core/tests/tasks/\
 test_admission_generation_assessment.py -q`: 105 passed.
- `uv run pytest packages/maistro-core/tests/runs/\
 test_root_admission_identity.py packages/maistro-core/tests/tasks/\
 test_idempotency.py -q`: 112 passed.
- ruff check + `ruff format --check` on both leaf files: clean; `mypy
  packages/maistro-core/src/maistro/tasks/admission_generation.py`:
  no issues.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`: exit 0, 1338 reviewed identities -> 1338 findings,
  `unclassified: 0` — the prescribed vulture-ledger amendment still has an
  empty fix-list at this head (base 31d891a5); any row change would desync
  the exact multiset and fail the same gate, so
  `quality/vulture-baseline.json` stays byte-identical to the base.
- `check-shipped-surface-truth.py` ok; `check-reachability.py` exit 0 (174
  unreachable of 1266); `check-reachability-dispositions.py` ok (51 groups,
  150 CONNECT); `check-promotion-surface.py` ok.

Mutation proof re-run at this head (each mutation applied to the restored
source copy, focused suite executed, file restored byte-identical — md5
verified): swap TAKEOVER/REPLACE_EXPIRED -> 39 failed; lease before binding
-> 12 failed; legacy pending treated as v2 (LEGACY_UNRESOLVED branch
deleted) -> 7 failed; mismatch moved before expiry without an expiry
exception -> 17 failed. Unmutated suite: 105 passed.

Structural failures re-bound to steps at this head (unchanged in kind,
still the documented blocker): `check-ratchet-provenance.py` exits 1 —
`check-reachability-provenance.py`: `maistro.runs.admission_identity` and
`maistro.tasks.admission_generation` are NEW unreachable modules vs trusted
base 31d891a5 and `load_authorizations('reachability', base=31d891a5)`
returns no grant (develop carries none), so the candidate-ledger rows banked
in rounds 1/3 cannot authorize themselves (the two-merge rule);
`check-reachability-dispositions-provenance.py` fails for the same
candidate-authored disposition rows. `check-radon-baseline.py` exits 1 on
exactly `admission_generation.py:62 _assess -> C (13)` vs 143 reviewed
C-or-worse blocks — its remedy is the base-landed grant
`<qualified-block>@13`, not a candidate-side edit. No in-leaf repair exists
for either (grants read from the base; wiring/fake callers/baseline
additions are forbidden by this leaf's scope); both remain owned by the
separately scoped #1845 integration change, and the stack stays unmerged
per the leaf contract until that change lands the reviewed consumer and
converges the unchanged gates at its final head.

## CI-repair round 5 (2026-10-05): Task-queue matrix row repaired; all four
## 0c5ff2c899ad CI failures re-bound to steps with job logs

The merge-queue run at 0c5ff2c899ad failed four jobs; each was re-bound to
its exact failing step from the Actions job logs (read-only), and one
genuine candidate-side defect was found and repaired:

- **Repair (the only candidate-side defect this round):** `test` (job
  111586617369) failed on exactly one test —
  `tests/test_check_convergence_matrix.py::
  test_the_shipped_matrix_matches_the_shipped_code`, output
  "Task queue and runner: Unreachable says `none`, code says `few` (1 of 16
  modules, 6.2%)". Round 1 fixed the *Run lifecycle* row drift caused by
  `maistro.runs.admission_identity` but missed the second drifted row:
  `maistro.tasks.admission_generation` makes the *Task queue and runner*
  subsystem 1/16 unreachable while its `matrix:disposition` row still said
  `none`. Reproduced locally byte-identical (`check-convergence-matrix.py`
  exit 1, same sentence; `--census` shows `Task queue and runner 1 / 16
  6.2% few`). Repaired the way the gate itself prescribes — the row now
  says `few` and names the baselined-unreachable contract leaf, mirroring
  round 1's Run-row wording; a planning-surface doc update, not a waiver.
  After the fix the gate exits 0 and its full meta-test family passes
  (60/60).
- **Coverage gate** (job 111588631369): failed in its root-suite producer
  leg (`coverage run --source=scripts -m pytest tests/`) on that same
  single convergence-matrix test ("1 failed, 4417 passed") — same root
  cause, no coverage defect. Retired by the same one-line repair. The
  per-file diff-coverage leg was additionally re-proven locally with CI's
  invocation against the current base 8a4bc239f (`check-diff-coverage.py
  coverage.xml --base 8a4bc239`): exit 0, both production files at/above
  90% lines / 80% branches, test files exempt by declaration,
  `_vulture_whitelist.py` outside every producer's measured tree.
- **exact-debt-ledger** (job 111586617406): fails at "Require enforced
  ratchet provenance policy" (`check-ratchet-provenance.py`); reproduced
  locally line-identical at this head vs trusted base 31d891a5 — NEW
  disposition + NEW unreachable for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation`, no already-landed grant
  (`load_authorizations` reads the base; develop carries none). The two
  candidate-side ledger rows banked in rounds 1/3 correctly cannot
  authorize themselves. The vulture step never runs (skipped after
  provenance fails); it is exact anyway: `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exits 0,
  1338 -> 1338, unclassified 0, `quality/vulture-baseline.json`
  byte-identical to the base. Structural two-merge blocker, unchanged.
- **Quality gate** (job 111586617744): fails at the "radon CC ratchet"
  step; reproduced locally — exactly one new C-or-worse block vs the
  trusted baseline, `admission_generation.py:62 _assess -> C (13)`, remedy
  "Land a grant keyed as '<qualified-block>@<new-complexity>' first". The
  leaf scope pins the validations and decision order inside the sole
  production function, so CC >= 12 is irreducible without ducking the
  counter (out of scope, round-2 analysis unchanged). Structural two-merge
  blocker, unchanged.

Full re-validation at this head after the repair (all executed): leaf
suites 105/105 + 112/112; ruff check + `ruff format --check` clean; mypy
on the classifier clean; `check-suite-inventory.py --suite
packages/maistro-core/tests` ok (13442 node IDs); `check-reachability.py`
exit 0 (174 of 1266); `check-reachability-dispositions.py` exit 0 (51
groups, 150 CONNECT); `check-promotion-surface.py` ok;
`check-shipped-surface-truth.py` ok; convergence gate ok (52 subsystems,
174 unreachable attributed); matrix/reachability meta-tests 60+345+53
passed. Mutation teeth re-proven on the restored source (md5-verified
byte-identical restores): TAKEOVER/REPLACE_EXPIRED swap -> 39 failed;
LEGACY_UNRESOLVED branch deleted -> 7 failed; lease-before-binding -> 12
failed; unmutated -> 105 passed.

Naming note against the issue's prospective-test list: the required matrix
and edge coverage is delivered by the suite's parametrized tests (every
matrix row at boundary and ±1 µs), not by the issue's provisional names —
only `test_existing_live_claim_flow_does_not_import_v2_classifier` (the
one round 4 flagged) carries its exact prescribed name. Coverage, not
spelling, is the acceptance substance; this note records the mapping
explicitly.

Net: after this round's one-line matrix repair, every remaining red step
at any plausible head traces only to the two-merge provenance/radon
blockers owned by the separately scoped #1845 integration change.

## CI-repair round 6 (2026-10-05): radon AND xenon retired in-leaf by the
## decision-table refactor; develop base synced to 534d475e

Trigger: the merge-queue evaluation at 9d45343f failed exactly two jobs —
`exact-debt-ledger` (again at `check-ratchet-provenance.py`) and the Quality
gate (again at the radon CC ratchet step). Re-bound from the Actions API
(read-only, jobs 111608902075 / 111608902442): in both jobs the vulture step
never ran (skipped behind the failing provenance / radon steps), and the
prescribed vulture-ledger amendment still has an empty fix-list (executed at
this head: rc=0, 1338 -> 1338, unclassified 0), so
`quality/vulture-baseline.json` stays byte-identical to the base.

New evidence that reopens the radon question:

- Xenon was never reached by the Quality job at any prior head (radon fails
  first). Executed at this head with CI's exact xenon invocation, the
  classifier module carried a MODULE-rank C (its only block is `_assess`)
  while `XENON_MODULE_LEDGER` in `quality.yml` is empty — so even the
  previously assumed remedy, a base-landed radon grant `_assess@13`, would
  have left the job red at xenon, and banking that row means editing the
  workflow YAML, not a JSON ledger. The grant path was therefore never
  sufficient; refactoring is the only in-leaf convergence path.
- The round-2 "irreducible CC >= 12" claim holds for the plain if-chain (five
  decision branches = five points; boolean-operator laundering via
  `all((...))` remains out of scope). But the issue's fixed decision order is
  equally expressible as data: an ordered first-match predicate table — one
  `(predicate, verdict)` row per decision-order bullet, predicates deferred
  as zero-argument callables — costs `for` + `if` = 2 points where five `if`s
  cost 5, with exact short-circuit semantics preserved (the v2-only lease
  comparison is never evaluated for a legacy row because the row above it
  matches first and returns) and the module's sole production function kept.
  `_assess` lands at exactly B (10).

Repair: the decision chain of `_assess` restructured into that ordered
predicate table; validations, envelope extraction, API, docstrings, and every
return value behaviorally identical.

Re-validation at 9c07d5665 (merge of origin/develop 534d475e + the refactor),
all executed with CI's exact invocations:

- Focused: `test_admission_generation_assessment.py` 105 passed;
  `test_root_admission_identity.py` + `test_idempotency.py` 112 passed;
  driver selection (identity + assessment) 178 passed.
- Mutation teeth on a restored source copy (md5 96b9e665 verified identical
  before/after): bidirectional TAKEOVER/REPLACE_EXPIRED swap -> 39 failed;
  lease before binding -> 12 failed; LEGACY_UNRESOLVED row deleted (legacy
  pending treated as v2) -> 7 failed; mismatch before expiry without an
  expiry exception -> 17 failed; unmutated 105 passed. Same counts as
  round 5.
- Quality family: `check-radon-baseline.py` exit 0 (143 -> 143, no
  new/regressed/improved/stale); xenon 143 blocks (<= 145), 0 module-rank,
  0 average — `admission_generation.py` left the C population entirely;
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exit 0 at 1338 -> 1338, unclassified 0;
  `check-reachability.py` exit 0 (174 of 1267);
  `check-reachability-dispositions.py` exit 0 (51 groups, 150 CONNECT);
  `check-promotion-surface.py`, `check-shipped-surface-truth.py`,
  `check-convergence-matrix.py` (52 subsystems, 174 attributed), doc-links,
  enumerations, workspace-retirement, route-permissions,
  principal-identity, frontend-typed-client, backlog-consistency,
  bump-version --check, release-consistency: all exit 0; interrogate 56.9%
  (>= 46 floor); `mypy --strict` clean on the classifier (the 5
  dev-only-sync `maistro_bootstrap` import-not-found errors are
  environmental and predate this stack); ruff check + format clean.
- Meta-tests: reachability/dispositions/convergence families 111 passed;
  `check-suite-inventory.py --suite packages/maistro-core/tests` ok (suite
  count unchanged at 105 — this round touched production code only).
- Base sync: origin/develop advanced five commits past the last evaluation
  base (faf93b2f -> 534d475e: research docs, hive-conductor chat_runs
  admission backpressure, speculative-call bench) without touching any
  `quality/*.json` row, any maistro-core tasks/runs module, or any gate
  script; merged clean (9c07d5665) and `git diff --numstat origin/develop
  HEAD -- quality/` confirms only this stack's own rows (+3/-1
  reachability-baseline, +20 dispositions). All gates above re-run against
  the new trusted base 534d475e.

Still red, structurally, and now exactly one defect family:
`check-ratchet-provenance.py` exits 1 on exactly the two documented
findings — `maistro.runs.admission_identity` and
`maistro.tasks.admission_generation` are NEW unreachable/dispositioned
modules vs the trusted base (now 534d475e) with no already-landed
reachability authorization (`load_authorizations` reads the base; develop
carries none), so the candidate rows banked in rounds 1/3 cannot authorize
themselves. With radon and xenon now green, `exact-debt-ledger`'s sole
remaining defect is that provenance step, and the Quality gate has no known
red step left at this head. The unblock sequence is unchanged since round 1
and belongs to the separately scoped #1845 integration change: land the
reachability authorizations on the base (grant first, change second), wire
the reviewed consumer, then converge the unchanged gates at its final head.

## CI-repair round 7 (2026-10-05): exact-debt-ledger re-bound at 014371c2e;
## vulture fix-list proven empty again; grant precedent identified in the
## base's own ratchet-authorizations.json

Trigger: the merge-queue evaluation at 014371c2 failed `exact-debt-ledger`
(actions run 37267687375, job 111627847522) and the lane brief again
prescribed the vulture-ledger amendment. Re-proven at this head, executed
not assumed:

- The vulture step is not the defect and never ran in CI (it is step 3 of
  the job, behind the failing step 1). Executed here with CI's exact
  invocation `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: **exit 0**, 1338 reviewed identities ->
  1338 findings, unclassified 0, never_allowlist 0, and
  `quality/vulture-baseline.json` remains byte-identical to origin/develop
  (`git diff origin/develop HEAD -- quality/vulture-baseline.json` is
  empty). The prescribed amendment has an empty fix-list; the ledger stays
  untouched for the seventh consecutive round.
- The actual failing step is step 1 of the job,
  `scripts/check-ratchet-provenance.py`. Full inventory executed at this
  head: 9 sub-ratchets, 7 OK (adr-status-language, citation-status,
  promotion-surface, shell-execution, contract-markers, enumerations,
  lifecycle), exactly 2 FAIL — `reachability` ("NEW unreachable module
  absent from trusted base and not previously authorized" for both
  admission modules) and `reachability-dispositions` ("NEW disposition
  absent from trusted ledger and not covered by an already-landed
  reachability authorization" for the same two) — then the aggregate
  "FAIL: ratchet provenance inventory is incomplete" naming only those
  two sub-gates.
- Everything else that can be green at an unwired leaf head is green at
  014371c2e: focused suites 178 passed (identity 73 + assessment 105);
  full `check-suite-inventory.py` ok (14 suites, 26138 identities, zero
  duplicate evidence); `check-shipped-surface-truth.py` and
  `check-promotion-surface.py` exit 0; mypy clean on both new modules;
  ruff check + format clean (driver checks 0-4 all rc=0).

New structural evidence, read from the trusted base itself:
`quality/ratchet-authorizations.json` at 534d475e carries a `reachability`
section whose every existing entry is this exact debt shape — deliberately
unwired library/contract modules granted first, then banked with their
disposition in the follow-up change: the #61 events quartet
(`maistro.events.convergence/pg_envelope/publisher/wiring`), the #458
interop pair (`maistro.interop`, `maistro.interop.contract`),
`@flat/hive-conductor/services.entra_entitlements` (#492),
`maistro.security.strike_recovery` (#1172), the #1154 graph pair
(`maistro.graph.executor`, `maistro.graph.run`), and `_vulture_whitelist`
(#1142, whose grant text limits itself to "exactly that one
newly-discovered, pre-existing file"). Each entry carries `owner`,
`issue`, and `reason`. That is the concrete JSON shape the #1845
integration change must land on the base for
`maistro.runs.admission_identity` and `maistro.tasks.admission_generation`
— one grant per module, referencing this leaf's banked rows and their
CONNECT dispositions — before its own wiring change converges the gates
at its final head.

The deadlock, stated in gate terms so no future round re-litigates it:
`check-reachability.py` fails while a currently-unreachable module is
missing from the candidate baseline (round 3 hit this: the red test /
Coverage-combine jobs), while `check-reachability-provenance.py` fails
when the same rows are banked without a base-landed grant (rounds 1/3
hit this: the red exact-debt-ledger job). `load_authorizations` reads
only the merge base, so no commit on this branch can satisfy both while
the modules stay unwired — which is the issue's own staging constraint
("A candidate baseline update cannot grant itself permission"; wiring is
the #1845 integration's scope, and
`test_existing_live_claim_flow_does_not_import_v2_classifier` pins the
not-wired boundary). The failure is therefore the designed, documented
merge blocker, not a leaf defect.

Round-7 housekeeping: the previous lane job (de8682026) ended
`state: failed` on a driver-side provider timeout ("llama-cpp-gemma/
gemma4-26b-a4b-mtp: Request timed out") after all five repo checks
returned rc=0 — a dispatch-infrastructure failure, not a tree defect;
no tree change answers it. This round edits this note only.
`quality/vulture-baseline.json`, both reachability ledgers, all source
and test files stay byte-identical to round 6's validated state.

## CI-repair round 8 (2026-10-05): exact-debt-ledger reproduced at 52a321e926ce;
## vulture prescription executed with an empty fix-list; two-merge rule read in
## the gate's own source

Trigger: the previous lane job (1bdc9ac4) again died on the driver-side
provider timeout ("llama-cpp-gemma/gemma4-26b-a4b-mtp: Request timed out")
after all five repo checks returned rc=0 — dispatch-infrastructure failure,
not a tree defect; no tree change answers it. This round re-proved the
CI failure and the prescribed repair at the new head 52a321e926ce (merge
base with origin/develop still 94781cf6b708, the same trusted base CI's
`RATCHET_BASE_REV=origin/develop` resolves to), executed here, not assumed:

- Step-for-step reproduction of the exact-debt-ledger job
  (.github/workflows/vulture-ratchet.yml): step 1
  `check-ratchet-provenance.py` fails with exactly two of its nine
  sub-ratchets — `reachability` and `reachability-dispositions`, each naming
  only `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` as NEW vs the trusted base "absent
  ... and not previously authorized"; step 2
  `check-shipped-surface-truth.py` exits 0; step 3
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exits 0 at 1338 reviewed identities ->
  1338 findings, unclassified 0, never_allowlist 0. The lane brief's
  prescription ("amend quality/vulture-baseline.json") therefore has an
  empty fix-list for the eighth consecutive round:
  `git diff origin/develop HEAD -- quality/vulture-baseline.json` is empty
  and the ledger is left untouched. Nothing is genuinely dead to retire:
  the two new modules bank zero vulture findings.
- The failure layer is provenance only, re-run directly at this head:
  `check-reachability.py` rc=0 (174/1267 unreachable, rows banked in the
  candidate baseline), `check-reachability-dispositions.py` rc=0 (51
  groups cover all 174), `check-promotion-surface.py` rc=0.
  `check-ratchet-provenance.py` then fails the aggregate inventory on
  exactly those two sub-gates.
- The two-merge consequence is now cited from the gate's own source, not
  only from repo docs: `scripts/ratchet_provenance.py:478-498`
  (`load_authorizations`) reads the authorizations file **from the base
  revision** and states that "a new grant does not take effect in the
  change that introduces it ... Authorizing a floor-raise is now two
  merges". A reachability grant committed on this branch cannot authorize
  this branch's own banked rows, and this leaf's scope forbids grants
  anyway; landing `reachability` grants for the two admission modules on
  the base remains the #1845 integration change's first merge.
- Acceptance re-execution at 52a321e926ce: focused classifier suite 105
  passed; `test_root_admission_identity.py` + unchanged
  `test_idempotency.py` 112 passed; ruff check/format clean on both new
  files; mypy clean on the new module; full `check-suite-inventory.py` ok
  (14 suites, 26143 identities — +5 vs round 7 from merged develop commit
  94781cf6b, whose inventory the merge already banked).
- Mutation proof re-executed at this head (each mutation applied to a
  backup-restored copy of the module, suite re-run, file restored
  byte-identical — `git diff --stat` empty afterwards): swap
  TAKEOVER/REPLACE_EXPIRED in the expiry row -> 36 failed; swap the same
  pair in the lease row -> 4 failed; move the lease row above binding ->
  12 failed; delete the LEGACY_UNRESOLVED row (legacy treated as v2) ->
  7 failed; move MISMATCH before expiry -> 17 failed. All four issue-named
  mutations make focused tests fail; the in-order table in
  `admission_generation.py` is the only thing keeping them green.
- #1841 boundary revalidated at this head:
  `runs/store_boundary.py:56` still exposes
  `require_admitted_actor(str | None) -> str` (last touched by #1841's own
  053f93969b4d), and scoped reads still take optional-`str` semantics via
  `principal_id` keyword arguments (`runs/scoped_reads.py:52,55`); C1's
  compatibility assumptions hold unchanged.

No source, test, or ledger file changed in this round: this commit edits
this note only. The unblock sequence is unchanged and belongs to the
separately scoped #1845 integration change: land the reachability
authorizations on the base (grant first, change second), wire the reviewed
consumer, then converge the unchanged gates at its final head.

## CI-repair round 9 (2026-10-05): exact-debt-ledger reproduced at 4efbb5ce0fc7
## across the moved merge base; develop tip still carries no grants after the
## #1944 sibling leaf; synthetic-merge cleanliness proven by merge-tree

Trigger: the merge-queue evaluation at 4efbb5ce0fc7 failed `exact-debt-ledger`
(actions run 37286530916, job 111686641054) and the lane brief again
prescribed the vulture-ledger amendment. Everything re-executed at this head,
not assumed; new facts beyond round 8 are marked:

- Step-for-step reproduction of the exact-debt-ledger job with CI's exact
  arguments and `RATCHET_BASE_REV=origin/develop`: step 1
  `check-ratchet-provenance.py` exits 1 on exactly the same two of its nine
  sub-ratchets — `reachability` ("NEW unreachable module absent from trusted
  base and not previously authorized") and `reachability-dispositions`
  ("NEW disposition absent from trusted ledger and not covered by an
  already-landed reachability authorization"), each naming only
  `maistro.runs.admission_identity` and `maistro.tasks.admission_generation`;
  step 2 `check-shipped-surface-truth.py` exits 0; step 3
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exits 0 at 1338 reviewed identities ->
  1338 findings, unclassified 0, never_allowlist 0. The prescribed
  amendment has an empty fix-list for the ninth consecutive round:
  `git diff origin/develop HEAD -- quality/vulture-baseline.json` is empty
  (and so is the diff for `quality/ratchet-authorizations.json`); nothing
  is genuinely dead to retire. Both ledgers stay untouched.
- NEW: the trusted base moved and the failure survived it. This head merged
  develop's b3662bb3719a (PR #1968 research commit), so the merge base with
  origin/develop advanced from 94781cf6b708 (round 8) to b3662bb3719a; the
  provenance output now reads "baseline: base b3662bb3719a" and fails on
  the identical two identities. The defect is therefore independent of
  where the base sits — it is the two-merge rule itself
  (`scripts/ratchet_provenance.py:478-498`, `load_authorizations` reads the
  base revision; the in-repo rule "a grant never authorizes the change that
  introduces it").
- NEW: develop tip (30677b185) landed a sibling #1845 leaf — aee4e0845,
  PR #1944, the `054_task_admission_generations` migration from #1892 — and
  even after that merge `git ls-tree origin/develop` still contains neither
  `maistro/runs/admission_identity.py` nor
  `maistro/tasks/admission_generation.py`, and develop's
  `quality/ratchet-authorizations.json` still has no `reachability` entry
  mentioning either module (`grep -c admission` on both ledgers at
  origin/develop: 0). The unblock action therefore remains pending upstream
  and unchanged in kind by develop's advance.
- NEW: `git merge-tree --write-tree HEAD origin/develop` exits 0 — the
  branch synthesizes cleanly with develop tip 30677b185, so the merge-queue
  candidate builds and the red job is purely the provenance rule; there is
  no develop-sync conflict component to repair. A branch-side merge of
  origin/develop was considered and skipped as non-remedial: it cannot add
  the missing base-landed grants, so the gate outcome is identical.
- Mutation teeth re-proven at this head in a throwaway
  `git worktree` clone (assigned tree untouched, clone restored
  byte-identical afterwards): MISMATCH moved before the expiry row -> 17
  focused failures; the lease row moved above the binding row -> 10
  failures; the LEGACY_UNRESOLVED row deleted (legacy treated as v2) ->
  7 failures. (Fourth issue-named mutation — TAKEOVER/REPLACE_EXPIRED swap
  — was executed at this exact content in round 8's step list: 36/4
  failures by row.)
- Acceptance battery re-executed at 4efbb5ce0fc7: the three focused files
  (`test_admission_generation_assessment.py` + `test_root_admission_identity.py`
  + unchanged `test_idempotency.py`) 217 passed; import-spy test passes
  (`-k import_spy` 1 passed); mypy clean on both new modules; driver checks
  0-4 all rc=0 (ruff check, ruff format --check 2923 files, focused pytest
  178, suite inventory `--suite packages/maistro-core/tests` ok at 13468);
  full `check-suite-inventory.py` ok (14 suites, 26171 identities, zero
  duplicate evidence); `check-convergence-matrix.py` ok (52 subsystems
  classify all 1268 production modules, 174 attributed); no production
  module imports either new module (grep over `packages/*/src` excluding
  the two modules and the whitelist: no matches), and `tasks/__init__.py`,
  `runs/__init__.py`, `tasks/idempotency.py` have a zero-line diff vs the
  merge base.

No source, test, or ledger file changed in this round: this commit edits
this note only. The unblock sequence is unchanged and now proven stable
across a base move and a sibling-leaf landing: (1) the separately scoped
#1845 integration change lands `reachability` authorizations for
`maistro.runs.admission_identity` and `maistro.tasks.admission_generation`
on the base first (grant merge, then banking/wiring merge — the repo's own
precedent shape: the #61 events quartet and #458 interop pair grants), (2)
wires the reviewed consumer, and (3) converges the unchanged full quality
gates at its final head. Until (1), every merge-queue evaluation of this
stack deterministically fails exact-debt-ledger at step 1, exactly as the
leaf contract ("A candidate baseline update cannot grant itself permission")
requires it to.

## CI-repair round 10 (2026-10-05): independent re-execution at 1c59b17a42c0;
## develop advanced 9 commits past round 9 and stayed grantless; prescribed
## vulture amendment executed empty for the tenth consecutive round

Trigger: lane job 747e02f98 ended `state: failed`/BLOCKED — its result
record shows a driver-side provider timeout ("llama-cpp-gemma/
gemma4-26b-a4b-mtp: Request timed out") AFTER all five repo checks returned
rc=0 (sync, ruff check, ruff format --check, focused pytest 178 passed,
`check-suite-inventory.py --suite packages/maistro-core/tests` ok at
13468) — a dispatch-infrastructure failure, not a tree defect. This round
is a fresh attempt's independent re-execution of the whole acceptance
battery at the same head 1c59b17a42c0; nothing is taken from prior rounds'
claims. Everything below was executed at this head, not assumed.

- exact-debt-ledger step-for-step, CI's exact arguments: step 1
  `check-ratchet-provenance.py` exits 1 on exactly `reachability` ("NEW
  unreachable module absent from trusted base and not previously
  authorized") and `reachability-dispositions` ("NEW disposition absent
  from trusted ledger and not covered by an already-landed reachability
  authorization"), each naming only `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` vs trusted base b3662bb3719a (the
  merge base with origin/develop); step 2 `check-shipped-surface-truth.py`
  exits 0; step 3 `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exits 0 at 1338
  reviewed identities -> 1338 findings, unclassified 0. The prescribed
  vulture-ledger amendment has an empty fix-list for the tenth consecutive
  round; `git diff origin/develop HEAD -- quality/vulture-baseline.json
  quality/ratchet-authorizations.json` is empty and both ledgers stay
  byte-identical to develop.
- NEW: develop advanced and the state survived it. origin/develop moved 9
  commits past round 9's reference tip to cd5618223 (research/epic WIP
  merges, #1756, #1989, #1965…); `git diff 30677b185..origin/develop --
  quality/` touches only contract-markers-baseline.json (−1) and
  workflow-inventory.json (+7) — no reachability/vulture/authorization
  ledger row — and origin/develop still banks zero rows for either module
  (baseline rows 0, disposition rows 0, module files 0, authorization
  entries mentioning admission: none). `git merge-tree --write-tree HEAD
  origin/develop` exits 0 at the current tip, so the next merge-queue
  candidate synthesizes cleanly and the red job remains purely the
  provenance rule; no develop-sync conflict component exists.
- Acceptance battery re-executed at this head: focused classifier suite
  105 passed; `test_root_admission_identity.py` + unchanged
  `test_idempotency.py` 112 passed; the prescribed import-spy test passes
  by exact node ID
  (`::test_existing_live_claim_flow_does_not_import_v2_classifier`, 1
  passed); mypy clean on the classifier; ruff check + format clean on both
  leaf files; full `check-suite-inventory.py` ok (14 suites, 26171
  identities, zero duplicate evidence).
- Mutation teeth re-executed in the assigned tree (backup via cp, restore
  via cp, md5 96b9e665e4c4b53879b4065a90cb4445 verified identical before
  and after; no git restore/clean used): swap TAKEOVER/REPLACE_EXPIRED ->
  39 failed; lease row above binding row -> 12 failed; LEGACY_UNRESOLVED
  row deleted (legacy pending treated as v2) -> 7 failed; MISMATCH row
  above expiry row -> 17 failed; unmutated 105 passed. Same counts as
  rounds 8/9.
- Boundary re-verified: `git diff b3662bb3719a HEAD --` on
  `tasks/idempotency.py`, `tasks/__init__.py`, `runs/__init__.py`, and the
  queue is empty; grep over `packages/*/src` finds no reference to either
  new module outside the two modules themselves and the scanner-input
  `_vulture_whitelist.py` (no production caller, no re-export).

No source, test, or ledger file changed in this round: this commit edits
this note only. The unblock sequence is unchanged, upstream, and now
proven stable across two develop advances and one sibling-leaf landing:
the separately scoped #1845 integration change lands the `reachability`
authorizations on the base first (grant merge, then wiring merge), wires
the reviewed consumer, and converges the unchanged full quality gates at
its final head. Until then every merge-queue evaluation of this stack
deterministically fails exact-debt-ledger at step 1, which is the leaf
contract's own staging constraint working as designed.

## CI-repair round 11 (2026-10-05): independent re-execution at 891bc710ab5f;
## develop advanced to 30144ad0f (+1 past round 10) and stayed grantless;
## prescribed vulture amendment executed empty for the eleventh consecutive
## round; NEEDS-DEEP-REVIEW block resolved as upstream-only

Trigger: the last substantive repair verdict (job 36a9bd8e, NEEDS-DEEP-
REVIEW at 1c59b17a42c0) named only the two-merge provenance blocker and a
driver-side provider timeout — no tree defect; then job d62f5cbe died on
the same provider timeout after all five driver checks returned rc=0. This
round re-executed the entire battery independently at 891bc710ab5f;
nothing is taken from prior rounds' claims.

- exact-debt-ledger step-for-step with CI's exact arguments and
  `RATCHET_BASE_REV=origin/develop`: step 1 `check-ratchet-provenance.py`
  exits 1 on exactly two of its nine sub-ratchets — `reachability` and
  `reachability-dispositions`, each naming only
  `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` as NEW vs trusted base b3662bb3719a
  (still the merge base: `git merge-base HEAD origin/develop`); step 2
  `check-shipped-surface-truth.py` exits 0; step 3
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exits 0 at 1338 reviewed identities -> 1338 findings,
  unclassified 0, never_allowlist 0. The prescribed amendment has an empty
  fix-list for the eleventh consecutive round:
  `git diff origin/develop HEAD -- quality/vulture-baseline.json
  quality/ratchet-authorizations.json` is empty; both stay untouched.
- develop moved again and the state survived it: origin/develop advanced to
  30144ad0f (#1988 extensions publisher identity). `git diff --numstat
  b3662bb3719a..origin/develop -- quality/` touches only
  ac-state-notes/auto-119.json (+17), contract-markers-baseline.json
  (-1), durable-table-retention.json (+24), workflow-inventory.json (+7)
  — no reachability/vulture/authorization row; develop's
  ratchet-authorizations `reachability` section still names neither module.
  `git merge-tree --write-tree HEAD origin/develop` exits 0 at this tip, so
  the next merge-queue candidate synthesizes cleanly: the red job is purely
  the provenance rule, with no develop-sync conflict component to repair.
- Focused acceptance battery at this head: classifier suite 105 passed;
  `test_root_admission_identity.py` + unchanged `test_idempotency.py`
  112 passed; import-spy test by exact node ID 1 passed; mypy clean on the
  classifier; ruff check + format clean on both leaf files; full
  `check-suite-inventory.py` ok (14 suites, zero duplicate evidence);
  reachability meta-test family (`tests/test_check_reachability.py`,
  `tests/test_reachability_baseline_identity.py`,
  `tests/test_check_reachability_dispositions.py`) 51 passed.
- Quality family all green at this head: `check-reachability.py` rc=0
  (174/1268 unreachable attributed, rows banked);
  `check-reachability-dispositions.py` rc=0 (51 groups);
  `check-promotion-surface.py` rc=0; `check-radon-baseline.py` rc=0
  (143 -> 143, no new/regressed block); xenon with CI's exact invocation
  (installed ad hoc for the run) 143 blocks (<= 145), 0 module-rank, 0
  average — `admission_generation.py` absent from xenon's error output;
  `check-convergence-matrix.py` rc=0 (52 subsystems, 174 attributed).
- Mutation teeth re-executed with cp backup/restore, md5 96b9e665e4c4
  verified identical before and after: swap TAKEOVER/REPLACE_EXPIRED ->
  39 failed; LEGACY_UNRESOLVED row deleted (legacy pending treated as v2)
  -> 7 failed. Counts identical to rounds 8-10.
- Boundary re-verified: zero-line diff vs b3662bb3719a on
  `tasks/idempotency.py`, `tasks/__init__.py`, `runs/__init__.py`, the
  queue, `runs/store.py`, `runs/store_boundary.py`; grep over
  `packages/*/src` finds no reference to either new module outside the two
  modules themselves and the scanner-input `_vulture_whitelist.py`.

## CI-repair round 12 (2026-10-05): develop synced to this round's declared
## base 658a8f78c (actual merge, not merge-tree); block reproduced on the
## merged head; prescribed vulture amendment empty for the twelfth round

Trigger: the dispatch for this round names develop base 658a8f78c1800d264759a81dc8d87dd447f0f7f2
(capabilities effect-path #55) while the branch sat at the 30144ad0f-era merge
4efbb5ce0. Unlike rounds 9-11, which only proved merge-tree cleanliness, this
round actually merged `origin/develop` into `auto-1852` (merge commit
9cebadb809513ef52de4711cd477a0ba3c61fd13, conflict-free, admission ledger rows
untouched) and re-proved the entire battery on the merged head, so local
evidence now equals what the next merge-queue synthetic merge will build.

- The merge absorbs develop's quality-ledger moves without touching ours:
  `quality/reachability-baseline.json` loses two `maistro.events.*` rows
  (publisher/wiring became reachable on develop) while the two admission rows
  survive verbatim; `quality/vulture-baseline.json` gains five develop rows
  (jira_wait_for_subtasks, quota pg/sqlite invocation); radon,
  direct-effect-call-sites, promotion-surface and durable-table-retention
  update per develop's own green CI. No incoming develop commit touches
  `packages/maistro-core/src/maistro/tasks/` or `.../runs/`.
- exact-debt-ledger step-for-step with CI's exact arguments at the merged
  head: step 1 `check-ratchet-provenance.py` (`RATCHET_BASE_REV=origin/develop`,
  now resolving trusted base 658a8f78c180) exits 1 on exactly the same two of
  its nine sub-ratchets — `reachability` and `reachability-dispositions`, each
  naming only `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` as NEW vs the trusted base; step 2
  `check-shipped-surface-truth.py` exits 0; step 3
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exits 0 at 1343 reviewed identities -> 1343 findings
  (develop's +5 rows absorbed exactly by the merge). The prescribed amendment
  is empty for the twelfth consecutive round.
- Upstream state re-verified at the new tip: `origin/develop`'s
  `quality/reachability-baseline.json` and `quality/ratchet-authorizations.json`
  contain neither admission module — the base-landed grant the two-merge rule
  waits for still does not exist, so every merge-queue evaluation of this
  stack deterministically fails step 1 until the #1845 integration lands it.
- Integration-head quality family all green on the merged head:
  `check-reachability.py` rc=0 (1285 production modules, 172 unreachable,
  rows banked); `check-reachability-dispositions.py` rc=0 (51 groups: 150
  CONNECT, 20 LIBRARY, 2 RETIRE); `check-promotion-surface.py` rc=0;
  `check-radon-baseline.py` rc=0 (138 -> 138 after absorbing develop's
  ledger edits); xenon with CI's exact invocation and floor 138 blocks
  (<= 145), 0 module-rank, 0 average — `admission_generation.py` absent from
  xenon's output (the only "admission" hit is the long-banked canvas
  `_reconcile_admission` block); `check-convergence-matrix.py` rc=0
  (52 subsystems classify all 1285 modules, 172 attributed).
- Focused acceptance battery on the merged head: C1 + C2 suites 178 passed;
  C1 suite + unchanged live `test_idempotency.py` 112 passed;
  `test_existing_live_claim_flow_does_not_import_v2_classifier` 1 passed by
  exact node ID; mypy clean on both leaf modules; `ruff check .` and
  `ruff format --check .` clean repo-wide (2975 files); suite inventory ok
  both full (15 suites, 26763 unique identities — the merge brought develop's
  own baseline update) and CI-scoped (`--suite packages/maistro-core/tests`);
  reachability meta-test family 51 passed.
- Boundary re-proven through the merge: `git diff --numstat b3662bb3 HEAD`
  is zero-line on `tasks/idempotency.py`, `tasks/__init__.py`,
  `runs/__init__.py`, `runs/store.py`, `runs/store_boundary.py`, and the only
  `packages/*/src` file outside the two leaf modules mentioning either is the
  scanner-input `_vulture_whitelist.py`.
- Mutation teeth re-executed on the merged head with md5-verified restore
  (96b9e665e4c4b53879b4065a90cb4445, the same identity as rounds 8-11, byte
  identical after all four mutations; `git status` clean): swap
  TAKEOVER/REPLACE_EXPIRED -> 39 failed; lease before binding -> 12 failed;
  LEGACY_UNRESOLVED row deleted -> 7 failed; mismatch before expiry ->
  17 failed. Counts for the two repeated mutations are identical to rounds
  8-11; the round-12 firsts (lease-before-binding, mismatch-before-expiry)
  complete the issue's four-mutation list in one round for the first time.

No source, test, or ledger file changed in this round either: this commit
edits this note only (plus the develop merge itself). The unblock sequence
is unchanged and upstream: (1)
the separately scoped #1845 integration change lands `reachability`
authorizations for the two admission modules on the base (grant merge
first — `ratchet_provenance.load_authorizations` reads only the base
revision, so no commit on this branch can authorize its own banked rows),
(2) wires the reviewed consumer, and (3) converges the unchanged full
quality gates at its final head. Until (1), every merge-queue evaluation
of this stack deterministically fails exact-debt-ledger at step 1, exactly
as the leaf contract ("A candidate baseline update cannot grant itself
permission") requires it to.

## CI-repair round 13 (2026-10-05): exact-record-class input contract fixed
## (isinstance -> exact class); the issue's nine absent named tests added;
## fifth mutation (gate reverted to isinstance) proven caught

Prior verification named two tree defects besides the structural
provenance blocker: (a) `admission_generation.py` validated `record` with
`isinstance`, so a frozen-dataclass subclass (`V2Subclass(AdmissionRecordV2)`)
was accepted and classified (`takeover` from a live probe) instead of
raising `ValueError`, violating the issue's "one of these two exact record
classes" input contract; (b) nine of the issue's ten required test names
were absent (only `test_existing_live_claim_flow_does_not_import_v2_classifier`
existed). Both repaired this round; the provenance blocker is re-proven
structurally unchanged.

- **Exact-class gate**: validation now compares `type(record) is` the two
  record classes via a membership test (no boolean operator, so `_assess`
  stays at radon B (10) — an `and`-joined pair measured C (11) in a first
  draft and was rejected by that measurement before commit); the
  decision-table legacy row uses the captured `record_type is` form; the
  envelope-extraction branch keeps `isinstance` solely for mypy union
  narrowing, with a comment pinning its equivalence under the gate (mypy
  cannot narrow via `type() is`, and the issue's "sole production function"
  constraint rules out a TypeGuard helper). Rejection message now says
  "exactly an AdmissionRecordV2 or LegacyAdmissionRecord".
- **Named tests added** (suite 105 -> 131 collected cases; front-matter
  delta updated to +131; `check-suite-inventory.py --suite
  packages/maistro-core/tests` ok after `--update` folded the delta into
  this note): `test_assessment_matrix` (the issue's ten-row table as one
  parametrization with ids r1..r10),
  `test_exact_replay_deadline_replaces_generation_for_same_and_changed_payload`,
  `test_changed_payload_one_microsecond_before_expiry_remains_mismatch`,
  `test_lease_takeover_does_not_mean_replay_window_replacement`,
  `test_bound_unacknowledged_admission_replays_after_lease_expiry`,
  `test_legacy_pending_never_takes_over_inside_window`,
  `test_expired_legacy_pending_is_replaceable_without_inventing_old_identity`,
  `test_assessment_leaves_record_and_all_snapshot_bytes_unchanged` (full
  nested `dataclasses.asdict` dump plus snapshot `.text` bytes before/after),
  and `test_invalid_assessment_inputs_are_rejected` (subclass instances of
  both record classes, None/dict/object, malformed fingerprints and
  `now_us`). All ten issue-required names now exist; the earlier boundary
  sections remain as the detail behind them, superseding round 5's
  coverage-not-spelling note.
- **Mutation teeth re-proven on the final source** (cp backup/restore,
  md5 257a6e45c382349dd12f559099663fbc identical before/after; unmutated
  131 passed): swap TAKEOVER/REPLACE_EXPIRED -> 50 failed; lease row above
  binding -> 14 failed; LEGACY_UNRESOLVED row deleted (legacy treated as
  v2) -> 10 failed; MISMATCH row above expiry -> 22 failed; and the fifth,
  exact-class gate reverted to isinstance -> exactly
  `test_invalid_assessment_inputs_are_rejected` failed (1 failed, 130
  passed). All four issue-named mutations plus the new gate mutation are
  caught.
- **Gates at this head, CI's exact invocations**: vulture
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) exit 0
  at 1342 -> 1342, unclassified 0 — the prescribed amendment still has an
  empty fix-list, ledger byte-identical to the base;
  `check-reachability.py` exit 0 (172 unreachable of 1285, rows banked);
  `check-reachability-dispositions.py` exit 0 (51 groups, 150 CONNECT);
  `check-promotion-surface.py`, `check-shipped-surface-truth.py`,
  `check-radon-baseline.py` (138 -> 138) all exit 0; mypy clean on the
  classifier; ruff check + format clean (files and repo-wide).
- **Structural blocker re-proven, unchanged in kind**:
  `check-ratchet-provenance.py` exits 1 on exactly its two reachability
  sub-ratchets — `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` are NEW unreachable/dispositioned
  modules vs trusted base b672b799aba6 with no already-landed grant
  (develop carries none). Removing the candidate rows cannot fix this (the
  modules are genuinely in the tree and genuinely unwired; the scan is of
  the candidate tree, not the baseline file) and would only re-break
  `check-reachability.py` and its meta-tests — the round-7 deadlock stands,
  owned by the separately scoped #1845 integration change (grant merge on
  the base first, then wiring). The vulture-ledger amendment named by the
  lane brief remains contraindicated: executed empty for the thirteenth
  consecutive round.

Acceptance battery at this head: focused classifier suite 131 passed;
`test_root_admission_identity.py` + unchanged `test_idempotency.py` 112
passed; import-spy test by exact node ID 1 passed; driver-equivalent checks
(ruff check/format repo-wide, two-file pytest selection, scoped suite
inventory) all rc=0.

## CI-repair round 13 (2026-10-05, head 02dc2f8a894c + this commit): candidate reachability rows removed

The lane brief named `exact-debt-ledger` as the one red merge-queue check and
prescribed the vulture-ledger amendment procedure. Executed in order:

- **The prescribed vulture amendment is empty (13th consecutive round).**
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exits 0 at 1342 reviewed
  identities -> 1342 findings, unclassified 0. `quality/vulture-baseline.json`
  stays byte-identical to the base; there is nothing to bank or remove.
- **The two candidate reachability ledger rows and their paired disposition
  entries are removed.** `quality/reachability-baseline.json` (rows for
  `maistro.runs.admission_identity` and `maistro.tasks.admission_generation`)
  and `quality/reachability-dispositions.json` (groups
  `runs-root-admission-contracts`, `tasks-admission-generation-assessor`) are
  restored byte-for-byte to the develop trusted base (c560d4ccad82). They were
  prohibited additions for this leaf — "No fake callers, baseline additions,
  grants, disabled gates or quality waivers are permitted" — and the
  dispositions provenance sub-ratchet rejected them outright. Round 12 kept
  them because removal "would only re-break `check-reachability.py` and its
  meta-tests"; that trade is reversed here: the provenance outcome is
  identical in kind with or without the rows (see below), so the branch now
  carries zero prohibited ledger rows and eats the sanctioned red gates
  instead.
- **`check-ratchet-provenance.py` (exact-debt-ledger step 1) after the
  repair**: the reachability-dispositions sub-ratchet is now green; the
  reachability sub-ratchet still exits 1, on exactly four lines — both
  modules "NEW unreachable module absent from trusted base and not previously
  authorized" and both "current unreachable module missing from candidate
  baseline". This is the two-merge rule, not a ledger defect:
  `load_authorizations` reads grants from base c560d4ccad82, which has none
  for either module, so no in-branch state (rows banked or removed) can turn
  step 1 green. Steps 2 and 3 pass: `check-shipped-surface-truth.py` exit 0;
  the vulture command above exit 0.
- **Consequential red gates, re-derived and issue-sanctioned** (the staging
  constraint's "report implementation/test readiness plus the explicit merge
  blocker"): `check-reachability.py` exit 1 listing exactly the two leaf
  modules as NEWLY UNREACHABLE;
  `tests/test_check_reachability.py::test_baseline_matches_the_tree` and both
  `tests/test_reachability_baseline_identity.py` gate-identity tests fail for
  that same two-module delta and nothing else.
- **Everything else is green at this head**: `check-reachability-dispositions.py`
  (49 groups give all 170 unreachable modules a disposition),
  `check-convergence-matrix.py` (after reverting both matrix rows to the
  base-computed share word `none`, with the disposition prose now saying
  "newly unreachable — not baselined, in-leaf unauthorized" instead of the
  false "baselined-unreachable"), `check-promotion-surface.py`,
  `check-shipped-surface-truth.py`, `check-radon-baseline.py` (138 -> 138),
  ruff check + format repo-wide, mypy on the classifier, focused suites
  (131 + 112 passed), scoped suite inventory (13972 node IDs, unchanged —
  no tests moved in this round).
- **Mutation proof re-executed independently** (module restored byte-exact
  after each run, md5-verified): swap TAKEOVER/REPLACE_EXPIRED -> 50 failed;
  lease before binding -> 14 failed; legacy pending treated as v2 -> 10
  failed; mismatch before expiry (true reorder — the mismatch row moved above
  the expiry row; note that naively "swapping" the two adjacent lines around
  the interleaved comment block reproduces the original order and proves
  nothing) -> 22 failed. All four issue-named regression mutations are caught
  by the focused suite as it stands at this head.

What actually retires the blocker, in the only order the gates allow: land
authorizations for the two reachability identities on develop (outside this
lane's authority — no-push/no-PR rules), then rebase this stack and bank the
baseline + disposition rows; or land the #1845 integration consumer, wiring
both modules and pruning the entries the moment they are reached. Until one
of those happens the stack stays unmerged by design, with implementation and
focused-test readiness complete.

## CI-repair round 14 (2026-10-05, head 34e0559b7d6d): full battery re-derived; declared develop base 291bdd187a512 also grantless

Independent re-execution at the repaired head (round 13's row-removal commit);
no source or ledger edits this round, evidence only:

- **`exact-debt-ledger` steps re-run with CI's exact argv**
  (`.github/workflows/vulture-ratchet.yml`, `RATCHET_BASE_REV=origin/develop`):
  step 1 `check-ratchet-provenance.py` exit 1 — every sub-ratchet OK
  (adr-status-language, citation-status, promotion-surface,
  reachability-dispositions, shell-execution, contract-markers 371->371,
  enumerations, lifecycle) except reachability, which fails on exactly the
  same four lines as round 13 (both modules NEW-unreachable-unauthorized and
  missing-from-candidate-baseline). Steps 2 and 3 pass:
  `check-shipped-surface-truth.py` exit 0; `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exit 0 at
  1342 reviewed identities -> 1342 findings, unclassified 0 — **the prescribed
  vulture amendment is empty (14th consecutive round)**; the baseline stays
  byte-identical to base.
- **The declared job base `origin/develop` = 291bdd187a512 is itself
  grantless and baseline-less for both modules** — new check this round:
  `git show origin/develop:quality/reachability-baseline.json` contains zero
  `admission` rows; `quality/ratchet-authorizations.json` contains no grant
  for either module identity (its five `admission` substring hits are
  unrelated: chat-admission sweeper, a2a task admission, ScheduleRunAdmitter,
  canvas reconcile). So merging current develop into this branch cannot turn
  step 1 green either — the blocker is upstream in the strongest sense, not a
  sync artifact. The branch's `quality/` diff vs `origin/develop` is exactly
  two inherited-from-merge-history files (`direct-effect-call-sites.json`,
  `model-egress.json`, rows merged in from develop commits this branch
  already carries), neither in `exact-debt-ledger`'s scope; zero prohibited
  reachability/vulture rows.
- **Battery re-derived at this head**: focused suites 131 (assessment) + 112
  (identity + live idempotency) passed; ruff check + format repo-wide clean;
  mypy clean on the classifier; full `check-suite-inventory.py` exit 0 (15
  suites, 26935 unique identities, 0 duplicated evidence);
  `check-convergence-matrix.py` exit 0; `check-radon-baseline.py` exit 0
  (138 -> 138); `check-reachability-dispositions.py` exit 0;
  `check-promotion-surface.py` exit 0.
- **Sanctioned reds, re-derived**: `check-reachability.py` exit 1 listing
  exactly the two leaf modules as NEWLY UNREACHABLE; the two meta-tests
  (`tests/test_check_reachability.py::test_baseline_matches_the_tree`, both
  `tests/test_reachability_baseline_identity.py` assertions) fail for that
  same two-module delta and nothing else (assertion diffs name only
  `maistro.runs.admission_identity` / `maistro.tasks.admission_generation`).
- **Mutation proof re-executed independently** (backup/restore per mutation,
  md5-verified, `git diff` clean after): swap TAKEOVER/REPLACE_EXPIRED -> 50
  failed; lease before binding -> 14 failed; legacy pending treated as v2 ->
  10 failed; mismatch before expiry -> 22 failed. Identical to round 13.
- **Whitelist posture re-checked**: the branch's `_vulture_whitelist.py`
  additions name only the #1851 contract's enum members and envelope snapshot
  fields (classification input, never executed, ships in no wheel) — the same
  contract-ships-first posture as the CampaignSelector/#116 entries above
  them; no new finding identity was banked because of them (1342 -> 1342).

## CI-repair round 15 (2026-10-05, head 781296d2640e): supply-chain CVEs fixed in uv.lock; every remaining red re-derived as the sanctioned two-module blocker

Re-validation at the round head after it absorbed the M6 / M4-B / M9-B2 /
M9-D1 WIP merges (merge base with `origin/develop` moved to 56332162cf63,
which is itself grantless and baseline-less for both admission modules:
`git show 56332162cf63:quality/reachability-baseline.json` has zero
`admission` rows and no authorization names either identity):

- **Supply chain / security repaired — the round's one in-leaf-legal fix.**
  Reproduced the pip-audit gate locally on the exact CI recipe
  (`uv pip freeze --exclude-editable`, `pip-audit --strict --format=json`,
  `scripts/pip_audit_gate.py`): two advisories outside the triaged allowlist —
  `multidict==6.7.1 CVE-2026-104874` (fix 6.9.1) and `werkzeug==3.1.8
  CVE-2026-102598` (fix 3.1.9), the exact remediation the gate itself
  prescribes ("Fix by upgrading the dependency"). Fixed in `uv.lock` only
  (`uv lock --upgrade-package multidict --upgrade-package werkzeug`; diff
  touches exactly those two package blocks, no direct pins exist in any
  pyproject or the hive-conductor requirements). Post-fix: `uv sync --locked
  --extra dev` resolves clean, re-audit gives `pip-audit OK (1 known, all
  triaged in ALLOWED)` (the pre-existing ecdsa disposition) plus `direct-
  dependency usage OK` — gate exit 0. This greens the `Supply chain
  (pip-audit)` and `security` jobs' verdict step; both jobs share the one
  gate script.
- **Full root suite re-derived at this head** (`RATCHET_BASE_REV=origin/develop
  REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 pytest tests/ --ignore=tests/tools/registry
  -q --timeout=60`): **4529 passed, 122 skipped, exactly 3 failed**, and the
  three are the known gate-identity assertions naming only
  `maistro.runs.admission_identity` / `maistro.tasks.admission_generation`
  (`test_check_reachability.py::test_baseline_matches_the_tree`, both
  `test_reachability_baseline_identity.py` tests). Same sanctioned delta as
  rounds 11–14; nothing else in the suite reds at this head, including
  `test_check_convergence_matrix.py` (60/60).
- **`exact-debt-ledger` re-derived with CI's exact argv**: vulture step exit 0
  at 1336 reviewed identities -> 1336 findings against the new merge base —
  **the prescribed vulture amendment is empty (15th consecutive round)**;
  `check-ratchet-provenance.py` exit 1 with every sub-ratchet OK except
  reachability (same two NEW-unreachable-unauthorized identities);
  `check-shipped-surface-truth.py` exit 0.
- **Quality-gate components re-derived**: `check-radon-baseline.py` exit 0
  (138 -> 138 against the new base), `check-promotion-surface.py` exit 0,
  `check-reachability-dispositions.py` exit 0, `check-reachability.py` exit 1
  on exactly the two leaf modules (the sanctioned red).
- **Leaf diff-coverage re-measured** with the coverage job's own producer
  recipe on the leaf suites (`coverage run --branch --source=packages/
  maistro-core/src/maistro` over the two focused files):
  `admission_generation.py` 100% lines / 100% branches;
  `admission_identity.py` 97% lines / ~92% branches — both above the
  per-file 90% / 80% floors. The coverage job's remaining CI red is its
  root-suite producer running the same `tests/` tree as the `test` job
  (step-level confirmation on record from the b4d3ae948 round), i.e. the
  same two-module delta, not a coverage defect.
- **Mutation proof spot-re-derived at this head**: the "lease before
  binding" reorder (TAKEOVER row hoisted above REPLAYED, legacy guard
  inlined) fails 8 focused tests including
  `test_v2_binding_wins_over_lease_and_acknowledgement` and
  `test_bound_unacknowledged_admission_replays_after_lease_expiry`; module
  restored byte-exact after (sha256 re-verified). Full four-mutation battery
  on record from rounds 13–14 against byte-identical source.
- **Battery unchanged and green**: focused suites 131 + 112 passed; ruff
  check + format repo-wide clean; mypy clean on the classifier; scoped and
  full `check-suite-inventory.py` exit 0 (15 suites, 27197 identities).

The blocker statement is unchanged: no in-leaf edit can green the
reachability/provenance step (candidate-side ledger rows cannot authorize
themselves — the two-merge rule), and this leaf's scope forbids grants,
baseline rows, dispositions, fake callers, and production wiring. Retirement
paths remain exactly the two named in round 13: base-landed authorizations
followed by the banking rebase, or the #1845 integration consumer that wires
both modules and prunes the entries on arrival. Until one lands, the stack
stays unmerged by design.

## CI-repair round 16 (2026-10-06, head 6efe5a25b40c after develop sync to
11376c7bef4): merge absorbed, full battery re-derived, amendment empty 16th round

Round 15's head 926590632 was synced to the new `origin/develop` tip
11376c7bef4 (merge commit 6efe5a25b40c, conflict-free — develop's M9-E1 /
M4-B2 / M9-D3 content merged alongside). The new base is still grantless and
baseline-less for both admission modules (`git grep` over
`quality/ratchet-authorizations.json` and `quality/reachability-baseline.json`
at 11376c7bef4: zero `admission_identity` / `admission_generation` rows), and
the branch's `quality/` tree is byte-identical to the new base
(`git diff --numstat origin/develop -- quality/` empty), so the sanctioned
blocker translates unchanged. Full battery re-derived at this head:

- **Vulture ledger (exact-debt-ledger step 3) green, amendment empty the
  16th consecutive round**: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exit 0, 1332 reviewed
  identities -> 1332 findings, `unclassified: 0`. (1336 -> 1332 is the new
  base's own ledger trim, not a candidate edit.) Step 2
  `check-shipped-surface-truth.py` exit 0. Step 1
  `check-ratchet-provenance.py` exit 1 with every sub-ratchet OK except the
  reachability trusted-base gate — the same two
  NEW-unreachable-unauthorized identities, now against base 11376c7bef4.
- **Root suite re-derived** (`pytest tests/ --ignore=tests/tools/registry
  -q --timeout=300`): 4529 passed, 122 skipped, exactly 3 failed — the same
  three reachability gate-identity tests naming only the two leaf modules;
  nothing else reds at the merged head.
- **Quality-gate components**: `check-reachability.py` exit 1 on exactly the
  two leaf modules (the sanctioned red); `check-radon-baseline.py` exit 0
  (138 -> 138 against the new base); xenon with CI's exact argv 138 block
  violations (baseline 145), 0 module-rank, 0 average;
  `check-reachability-dispositions.py` exit 0 (49 groups, 170 modules);
  `check-promotion-surface.py` exit 0; `check-convergence-matrix.py` exit 0
  (52 subsystems classify all 1298 modules).
- **Supply-chain fix retained through the merge**: `uv.lock` still pins
  multidict 6.9.1 and werkzeug 3.1.9; CI check-runs at 6efe5a25b40c show
  `Supply chain (pip-audit)` and `security` = success (captured in this
  round's dispatch context), so round 15's CVE repair survived the sync.
- **Focused battery green**: 131 passed in the classifier suite (==
  `inventory-delta`), 112 passed in the #1851 + live-idempotency suites;
  ruff check + format clean repo-wide (driver) and on the two leaf files;
  mypy clean on the classifier; full `check-suite-inventory.py` exit 0
  (15 suites, 27401 identities).
- **Mutation proof spot-re-derived at this head** (cp backup/restore, tree
  verified clean after, module byte-identical): lease-before-binding reorder
  -> 14 focused failures; mismatch-before-expiry reorder -> 22 focused
  failures. Same catching pattern as rounds 13-15 against byte-identical
  source.

The round-15 NEEDS-DEEP-REVIEW attention request is resolved by this
evidence: at the new base there is still no authorization path for either
module, no new fixable red appeared from the develop sync, and every
remaining CI red (exact-debt-ledger, Quality gate, test, coverage producer)
reduces to the one sanctioned two-module delta that only the separately
scoped #1845 integration (or a base-landed grant followed by the banking
rebase) can retire. The stack stays unmerged by design; implementation and
test readiness stand proven at 6efe5a25b40c.

## CI-repair round 17 (2026-10-06, head 3e75c148ddee = merge of develop tip
## a8258ee24dd9 into the branch): full four-mutation battery re-derived; the
## acceptance-state design_coverage undercut bound to the same two-module delta

Round 16's head was synced once more (merge commit 3e75c148ddee brings
`origin/develop` tip a8258ee24dd9 into the branch; the PR's merge base IS
a8258ee24dd9, still carrying zero `admission` rows in
`quality/reachability-baseline.json` and `quality/ratchet-authorizations.json`,
and `git diff --numstat origin/develop -- quality/` is empty — the branch's
quality tree is byte-identical to the base). Everything below was re-derived
at this exact head in the round's environment:

- **Driver battery green**: `uv sync --locked --extra dev` ok; `ruff check .`
  and `ruff format --check .` clean (3040 files); focused driver pytest over
  `tests/runs/test_root_admission_identity.py` +
  `tests/tasks/test_admission_generation_assessment.py` 204 passed;
  `check-suite-inventory.py --suite packages/maistro-core/tests` ok (14513
  identities).
- **exact-debt-ledger re-derived with CI's exact argv, step by step**: step 2
  `check-shipped-surface-truth.py` exit 0; step 3 `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exit 0 (1332
  reviewed identities -> 1332 findings, `unclassified: 0` — the prescribed
  amendment stays empty, 17th consecutive round); step 1
  `check-ratchet-provenance.py` exit 1 with every sub-ratchet OK except the
  reachability trusted-base gate (both leaf modules NEW-unreachable,
  unauthorized at base a8258ee24dd9, and absent from the candidate baseline —
  the two-merge rule).
- **Quality gate re-derived component by component**: ruff both clean;
  `check-radon-baseline.py` exit 0 (138 -> 138); `bump_version.py --check`
  exit 0 (40 sites, 0.9.0); `check-release-consistency.py` exit 0;
  `check-doc-links.py` exit 0; `check_enumerations.py` exit 0;
  `check-workspace-retirement.py` exit 0 (89 entries);
  `check-route-permissions.py` exit 0 (40 declared);
  `check-principal-identity.py` exit 0 (4 tolerated, none new);
  `check-frontend-typed-client.py` exit 0 (60 + 142 tolerated, none new);
  `vendor_ifeval.py --check` and `vendor_bfcl.py --check` exit 0; xenon with
  CI's exact argv 140 block violations (baseline 145), 0 module-rank, 0
  average (138 -> 140 is the base sync's own movement, still under the
  floor); vulture step exit 0 as above; `check-reachability.py` exit 1 on
  exactly the two leaf modules (the sanctioned red — the first failing step
  of the CI job, so CI never reaches the steps below it);
  `check-credential-authority.py`, `check-wiring-reads.py`,
  `check-agent-store-writes.py`, `check-contract-markers.py`,
  `check-convergence-matrix.py`, `check-reachability-dispositions.py`,
  `check-security-inventory.py`, `check-image-inventory.py`,
  `check-image-pins.py`, `check-workflow-inventory.py`,
  `check-backlog-consistency.py` all exit 0; `mypy --strict
  packages/maistro-core/src` clean over 736 files.
- **NEW this round — the acceptance-state ratchet is bound to the same root
  cause.** `check-ac-state.py --run-tests --ratchet --mandate a8258ee24dd9`
  against a live PostgreSQL (the quality-gate job's pg18 service; CI never
  reaches this step because `check-reachability.py` fails first) fails with
  `design_coverage: 43.0887 falls below the floor of 43.2114`. The floor is
  the max-fold of the 30 committed `quality/ac-state-notes/*.json`; the
  current value is lower because the `-m ac` outcome run inside the ratchet
  fails exactly two AC-marked tests —
  `tests/test_reachability_baseline_identity.py::
  test_the_committed_baseline_passes_the_gate_it_now_carries` (SPEC-082926-
  f1c3/AC-2) and `::test_the_baseline_is_exactly_the_unreachable_set`
  (SPEC-082926-f1c3/AC-3) — the reachability gate-identity self-checks, whose
  criteria therefore drop from `reachable` to `covered` for this run. The
  mandate half is green (0 criteria added or newly claimed, 0 unproven; 0
  chain gaps). So the acceptance-state red is the same two-module delta, not
  an independent defect. (The core package suite run under the coverage
  producer additionally showed one environment-only failure,
  `test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_fallback`,
  caused by a local service already listening on 127.0.0.1:5432 in this
  round's environment; it passes in isolation and in the plain full-suite
  run, which showed 13574 passed / 938 skipped / 1 xfailed / 0 failed.)
- **test job fully bound at this head**: core suite 13574 passed / 938
  skipped / 1 xfailed / 0 failed; bootstrap 232 passed; server 516 passed;
  canvas 464 passed; turing 210 + backend 90 passed; design 572 passed;
  ext-sdk 118 passed; rsi 1111 passed; evolve 984 passed + 3 failed, the
  three being Docker-daemon-dependent sandbox/swebench tests that fail only
  because this environment's Docker daemon is unreachable (the docker binary
  is present, `docker ps` fails; CI's own docker-build and integration jobs
  are success at this head); root `tests/` re-derived 4530 passed / 122
  skipped / exactly 3 failed — the same three reachability gate-identity
  tests naming only the two leaf modules (4529 -> 4530 passed is the base
  sync's own test count, not a candidate edit).
- **Coverage gate bound at this head**: the leaf's own diff coverage
  re-measured with the coverage-unit producer recipe over the whole core
  suite — `check-diff-coverage.py coverage.xml --base a8258ee24dd9` exit 0
  ("ok: every measured file this change touches is at or above 90% lines /
  80% branch arcs"; the two leaf modules measured, tests exempt,
  `_vulture_whitelist.py` unmeasured-but-listed). The job's remaining red is
  its `combine` step's `--source=scripts` producer re-running the same root
  suite, whose 3 sanctioned failures abort the step under `set -euo pipefail`
  — the same two-module delta, not a coverage defect.
- **Full four-mutation battery re-derived at this exact head** (cp backup /
  restore after each, md5-verified byte-identical restoration,
  `git status` clean after): swap TAKEOVER/REPLACE_EXPIRED -> 50 focused
  failures; lease before binding (TAKEOVER row hoisted above REPLAYED,
  legacy-guarded) -> 8 focused failures; legacy pending treated as v2
  (LEGACY_UNRESOLVED row deleted so unbound legacy rows fall through to the
  lease comparison) -> 10 focused failures; mismatch before expiry without
  an expiry exception -> 22 focused failures. All four required mutations
  make the focused suite fail.
- **Focused battery green**: classifier suite 131 passed (== the
  `inventory-delta`); #1851 + live-idempotency suites 112 passed; mypy clean
  on the classifier module; full `check-suite-inventory.py` exit 0 (16
  suites, 27731 identities — 15 -> 16 suites is the base sync's own
  addition).

The blocker statement is unchanged and now exhaustive: every red gate at
this head (exact-debt-ledger, Quality gate incl. its acceptance-state step,
test, Coverage gate) reduces to the one sanctioned two-module reachability
delta that no in-leaf-legal edit can retire — candidate-side ledger rows
cannot authorize themselves (the two-merge rule), and this leaf's scope
forbids grants, baseline rows, dispositions, fake callers, and production
wiring. Retirement paths remain exactly the two named in round 13: a
base-landed authorization followed by the banking rebase, or the #1845
integration consumer that wires both modules and prunes the entries on
arrival. The stack stays unmerged by design; implementation and test
readiness stand proven at 3e75c148ddee.

## CI-repair round 18 (2026-10-06, head 74bc299f094d): round-17's design_coverage
## binding independently re-derived to the exact criterion pair; merge-base
## measured at the floor exactly; all four reds re-executed; prior
## NEEDS-DEEP-REVIEW resolved by full contract re-verification

Prior attempt died on a provider timeout after its five driver checks passed
(ruff, format, both focused suites, suite inventory). This round re-executed
every gate named in the merge-queue evaluation at this exact head, plus one
new experiment round 17 did not run: measuring the merge base itself.

- **exact-debt-ledger re-derived step by step**: step 2
  (`check-shipped-surface-truth.py`) exit 0; step 3 vulture with CI's exact
  arguments (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`)
  1332 reviewed identities -> 1332 findings, exit 0 — the prescribed ledger
  amendment is empty for the 18th consecutive round (nothing genuinely dead to
  fix, no unbanked identity to bank). Step 1 (`check-ratchet-provenance.py`)
  fails only in its reachability sub-gate: both admission modules NEW
  unreachable vs trusted base a8258ee24dd9 and missing from the candidate
  baseline (round 14 removed the self-authorizing rows). All other sub-gates
  green (170 dispositions, 3 shell calls, 371 contract markers, 1 enumeration
  gap, 0 lifecycle violations).
- **develop remains grantless**: origin/develop moved +4 commits since the
  merge base (3b8e090fe, d39a2e4ce, a9a27b063, 1e640df17 — all M9 WIP);
  `git show <commit> --name-only` for each touches no `quality/` path, and
  neither `ratchet-authorizations.json` nor `reachability-baseline.json` at
  origin/develop mentions either admission module. Merge-base with
  origin/develop is still a8258ee24dd9. The two-merge-rule line stands.
- **test job re-derived**: `pytest tests/test_check_reachability.py
  tests/test_reachability_baseline_identity.py
  tests/test_reachability_source_universe.py
  tests/test_check_reachability_dispositions.py -q` -> exactly 3 failed / 58
  passed, the same three sanctioned gate-identity tests
  (`test_baseline_matches_the_tree`,
  `test_the_committed_baseline_passes_the_gate_it_now_carries`,
  `test_the_baseline_is_exactly_the_unreachable_set`), each asserting
  `set(unreachable) == baseline` with exactly the two leaf modules as the
  extra items.
- **acceptance-state undercut re-derived with a NEW exactness proof**: with
  PG18 up, `check-ac-state.py --run-tests --ratchet --mandate a8258ee24dd9`
  fails ONLY on `design_coverage: 43.0887 falls below the floor of 43.2114`
  (mandate green: 0 criteria added/newly claimed, 0 unproven; 0 chain gaps).
  Round 17 bound the undercut to the two-module delta; this round proves the
  binding per criterion: diffing the fold's per-decision rows between the
  candidate (`quality/ac-state.json`, gitignored) and the base shows exactly
  ONE changed decision — ADR-082526-aef8 (reachability-for-repo-tooling) falls
  10/10 -> 8/10 reachable criteria — and the two lost criteria are
  SPEC-082926-f1c3/AC-2 and /AC-3, anchored on the very
  `test_reachability_baseline_identity.py` tests that fail above. The
  counterfactual was executed: the same measurement in a throwaway worktree at
  the merge base a8258ee24dd9 reports exactly 43.2114% over the same 163
  taken decisions — i.e. the base sits exactly AT the banked floor (folded by
  max from `quality/ac-state-notes/auto-961.json`), so the 8-file leaf delta
  alone causes the 0.1227-point fall. No independent defect.
- **Coverage gate re-derived**: leaf diff coverage with the coverage-unit
  producer recipe (`check-diff-coverage.py coverage.xml --base a8258ee24dd9`)
  exit 0 — both leaf modules measured above the 90% lines / 80% branch floors,
  tests exempt, `_vulture_whitelist.py` unmeasured-but-listed. The job's red
  stays the `combine` step's `--source=scripts` producer re-running the root
  suite, whose 3 sanctioned failures abort under `set -euo pipefail` — the
  same two-module delta.
- **Focused battery green**: both suites 204 passed; the four required
  mutations each re-applied from a cp backup and caught with `-x` (swap
  TAKEOVER/REPLACE_EXPIRED, lease before binding, legacy pending treated as
  v2, mismatch before expiry without an expiry exception), each restored
  byte-identical (git diff clean). `check-suite-inventory.py --suite
  packages/maistro-core/tests` exit 0 (14513 identities == recorded delta).
  mypy --strict on `packages/maistro-core/src`: zero errors in either leaf
  module (the 5 reported errors are pre-existing import-not-found environment
  artifacts in untouched `cli/` files under a `--extra dev` sync). radon
  138 -> 138. `check-reachability-dispositions.py` and
  `check-promotion-surface.py` exit 0; `check-reachability.py` fails with
  exactly the two leaf modules, as designed.
- **Deep-review block resolved**: the prior round's NEEDS-DEEP-REVIEW was
  closed by re-verifying the contract against the issue text: exact-record-class
  input gate (`type(record) is ...`, not isinstance), `[0-9a-f]{64}` fullmatch
  fingerprint, bool-rejecting signed-int64 `now_us`, the fixed six-branch
  decision order (inclusive expiry first, mismatch second, binding third,
  legacy fourth, lease fifth, PENDING fallback), `acknowledged_at_us`
  deliberately unread, no clock/store/log/UUID/mutation, initializers
  untouched, no exports added, `idempotency.py`/`queue.py` import neither new
  module (grep-verified), and the live flow still answering its unchanged
  four-variant contract.

The blocker statement is unchanged: every red gate at this head still reduces
to the one sanctioned two-module reachability delta that no in-leaf-legal edit
can retire — candidate-side ledger rows cannot authorize themselves (the
two-merge rule), and this leaf's scope forbids grants, baseline rows,
dispositions, fake callers, and production wiring. Retirement paths remain the
two named in round 13: a base-landed authorization followed by the banking
rebase, or the #1845 integration consumer that wires both modules and prunes
the entries on arrival. The stack stays unmerged by design; implementation and
test readiness stand proven at 74bc299f094d.

## CI-repair round 19 (2026-10-06, head 6747d4a63347 = the dispatched exact
## head, i.e. 74bc299f094d with develop's four grantless M9 WIP commits merged
## in): focused validation re-executed at the merged head; four-mutation
## battery re-derived with line-level formulations (50/14/10/22); amendment
## empty 19th round; blocker unchanged

Prior attempt died on a provider timeout after its five driver checks had all
passed at this exact head (uv sync, whole-tree ruff check, whole-tree format
check, both leaf suites 204 passed, suite inventory ok). This round
independently re-executed the acceptance evidence at 6747d4a63347:

- **Focused suites green**: `test_admission_generation_assessment.py` 131/131;
  `test_root_admission_identity.py` + `test_idempotency.py` 112/112 (combined
  243; C1 + this suite alone = 204, matching the driver's check-3 log). The
  driver's whole-tree `ruff check .` / `ruff format --check .` re-confirmed
  clean this round; `mypy` on `admission_generation.py` clean.
- **Suite inventory**: `check-suite-inventory.py` (all 16 suites) ok — 27826
  collected node IDs, 0 duplicates, matching the recorded inventory; the
  `inventory-delta` front-matter (+131) equals actual collection.
- **Four-mutation battery re-derived at this head**, each mutation applied as
  an exact decision-row replacement from a `cp` backup and the module restored
  byte-identical after each run (`git status` clean between runs; an earlier
  mutation harness that dropped a trailing comma was itself detected — it
  produced a collection error instead of test failures — and discarded):
  swap TAKEOVER/REPLACE_EXPIRED -> 50 failed; lease row before binding (last
  three rows rotated) -> 14 failed; legacy row answering REPLAYED -> 10
  failed; mismatch row before expiry without an expiry exception -> 22
  failed. The failing sets are the semantically right ones (m1 kills the
  takeover/expiry-boundary tests, m2 the binding-wins tests, m3 the
  legacy-unresolved tests, m4 the expiry-wins tests). The m2 count differs
  from round 17's 8 only because this round rotated all three tail rows
  rather than swapping two; every formulation kills its mutation.
- **exact-debt-ledger re-derived**: vulture with CI's exact arguments
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) exit 0 —
  1332 reviewed identities -> 1332 findings; the prescribed ledger amendment
  is empty for the 19th consecutive round. `check-reachability.py` exit 1
  with exactly the two leaf modules NEWLY UNREACHABLE
  (`maistro.runs.admission_identity`, `maistro.tasks.admission_generation`);
  `check-reachability-dispositions.py` OK; `check-promotion-surface.py` ok.
  Structural constraints re-verified by grep: no production module imports
  `admission_generation`; the module imports only `re`, `Callable`, and the
  three C1 names; `tasks/__init__.py`, `runs/__init__.py`, `idempotency.py`,
  `queue.py`, and all of `quality/` are byte-identical to the base.

The blocker statement is unchanged and remains the sanctioned two-module
reachability delta: candidate-side rows cannot authorize themselves, and this
leaf's scope forbids grants, baseline rows, dispositions, fake callers, and
production wiring. Retirement stays with the base-landed-authorization or the
#1845 integration consumer. The stack stays unmerged by design; implementation
and test readiness stand proven at 6747d4a63347.

## CI-repair round 20 (2026-10-06, head aee968654d6b): the merged M1-B1 commit
## (df00785bb) changed the live flow the leaf's tests mirror — test file
## repaired to the merged reality; collection error fixed; source untouched

The driver's pre-worker checks failed at this head: the focused suite no
longer collected (`AdmissionRecord.__init__() missing 2 required positional
arguments: 'claim_token' and 'completed_at_us'` at the module-level
parametrize), so both the pytest job and the suite-inventory job red.
Root cause: the branch merged `df00785bb` ("WIP: M1-B1 — Route every
ordinary task/chat request into a canonical Run (#1325)"), which evolved the
live `maistro.tasks.idempotency` flow this leaf's tests call as a witness:
`AdmissionRecord` gained required `claim_token` and `completed_at_us`
fields, the `admitted` property now reads the `completed_at_us` stamp
(`begun` — the announced `task_id` — is separate), and `_AssessmentKind`
ships a fifth `"ambiguous"` answer (begun, uncompleted, lapsed lease). The
merge changed none of this leaf's own files; the test file simply predated
it. The issue forbids editing `tasks/idempotency.py`, so the repair adapts
the witness tests to the merged live reality — the classifier module and
every ledger are untouched (`git diff` this round: the one test file, this
note, nothing else).

- **Repairs in `test_admission_generation_assessment.py` only**: both
  `idempotency.AdmissionRecord(...)` constructions (the raw-row stand-in in
  the input-validation parametrize and the `_live_record` witness helper)
  build the merged record shape; `admitted=True` now stamps
  `completed_at_us` (the live `admitted` semantics) and a new `begun=True`
  flag announces the receipt without stamping; the variant-set witness was
  renamed `test_live_flow_still_has_exactly_four_variants` →
  `test_live_flow_variant_set_is_unchanged_by_this_leaf` and now pins the
  merged loop's exact five-variant tuple (mismatch, replayed, pending,
  ambiguous, takeover) — the leaf's real guarantee (no classifier outcome
  leaked into the live loop) unchanged;
  `test_live_flow_answers_are_unchanged` gained one mirrored row pinning
  the merged flow's `"ambiguous"` answer (begun, uncompleted, lapsed lease
  → ambiguous, not takeover); the stale "four-variant" prose updated.
- **Re-derived at the repaired head**: focused suite 132 passed (131 + the
  new ambiguous row; `inventory-delta` updated +131 → +132 via
  `check-suite-inventory.py --update --note
  task-admission-generation-assessment`, gate exit 0);
  `test_root_admission_identity.py` + `test_idempotency.py` 140 passed (112
  prior + the merged flow's own expanded suite); driver check-4's exact
  recipe (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 pytest
  packages/maistro-core/tests --collect-only -q`) collects 14830 tests, 0
  errors (was: 1 collection error); whole-tree ruff check + format clean;
  mypy clean on the classifier.
- **Mutation teeth re-proven against the current tree** (cp backup/restore,
  md5 `257a6e45c382349dd12f559099663fbc` identical before and after — the
  same identity as rounds 13–19, so the source is untouched; `git status`
  clean between runs): with `-x`, swap TAKEOVER/REPLACE_EXPIRED → 1 failed;
  lease row hoisted above binding → 1 failed; LEGACY_UNRESOLVED row deleted
  → 1 failed; mismatch row hoisted above expiry → 1 failed. All four
  issue-named mutations are caught.
- **Structural blocker unchanged**: nothing in this round touches the
  sanctioned two-module reachability delta; no ledger, grant, baseline row,
  disposition, or production wiring was added or removed. The unblock
  sequence stays the base-landed authorization or the #1845 integration
  consumer.


## Round 20 — exact-debt-ledger CI-repair round at dispatched head 8ca328234496

Scope: the round was dispatched as CI gate repair for `exact-debt-ledger` and to
resolve the prior round's NEEDS-DEEP-REVIEW block. All evidence below was
re-executed fresh at HEAD `8ca3282344962cbf1975b11e7ab540a53258e5d0` (develop
base `e1b13dcd15dedd`, merge base `b78637f52be3`); no source file changed.

- **Sanctioned vulture amendment is EMPTY.** With CI's exact arguments
  (`uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`) the gate exits 0:
  1328 reviewed identities -> 1328 findings, `unclassified: 0`,
  `never_allowlist: 0`. No unbanked identity exists to fix or bank, so
  `quality/vulture-baseline.json` is deliberately not edited.
- **exact-debt-ledger red is one step, and it is the designed blocker.** The
  job's other steps pass (`check-shipped-surface-truth.py` exit 0;
  `check-vulture-baseline.py` exit 0). `check-ratchet-provenance.py` runs 9
  sub-ratchets: 8 OK, sole FAIL is reachability —
  `maistro.runs.admission_identity` and `maistro.tasks.admission_generation`
  are NEW unreachable (171 vs trusted 169), "absent from trusted base and not
  previously authorized". `load_authorizations` reads grants from the merge
  base, and `e1b13dcd15dedd:quality/ratchet-authorizations.json` contains 0
  rows for either module, so no edit on this branch can authorize them (the
  two-merge rule). Issue #1852 forbids baseline rows, grants, and fake wiring
  for this leaf; round 14 already removed the prohibited candidate rows
  (34e0559b7). Conclusion re-proven, not assumed: the red is the leaf's
  explicit merge blocker; the unblock lives in the #1845 integration consumer
  or a base-landed authorization.
- **Full root suite** `tests/`: 4667 passed / 4 failed / 128 skipped. Three
  failures are the sanctioned two-module delta
  (`test_check_reachability.py::test_baseline_matches_the_tree`,
  `test_reachability_baseline_identity.py` x2). The fourth
  (`test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once`) is a LOCAL
  ARTIFACT of this worktree only: `quality/ac-state.json` is an untracked
  file generated here by `scripts/check-ac-state.py` (absent from HEAD,
  origin/develop, and the merge-base trees), and the identical script +
  registry pass in a clean `b78637f52be3` checkout where the file does not
  exist. CI checkouts cannot see it. This corrects round 19's "all 4 the same
  two-module delta" claim: it is 3 + 1 local artifact.
- **Mutation battery re-executed** in a throwaway `git worktree` at HEAD
  (assigned tree never modified), full focused suite each time, source
  restored from `git show HEAD:` between runs: swap TAKEOVER/REPLACE_EXPIRED
  -> 50 failed; lease row above binding -> 14 failed; LEGACY_UNRESOLVED row
  deleted (legacy treated as v2) -> 10 failed; mismatch above expiry -> 22
  failed; unmutated -> 132 passed.
- **Focused and issue-required commands**: classifier suite 132 passed;
  classifier + `test_root_admission_identity.py` + `test_idempotency.py`
  272 passed; mypy clean; ruff check + format clean on the leaf pair;
  `check-reachability-dispositions.py` OK; `check-promotion-surface.py` OK;
  `check-suite-inventory.py --suite packages/maistro-core/tests` ok at 15275
  collected identities (the +132 delta still matches the front-matter).
- **Stack hygiene re-checked**: `packages/maistro-core/src/maistro/tasks/
  __init__.py`, `runs/__init__.py`, and `tasks/idempotency.py` contain no
  reference to either new module; no admission row was added to
  `quality/reachability-baseline.json` or `quality/ratchet-authorizations.json`;
  PR #1941 remains open with no closure keyword (only "Refs #1852").
- **Verdict-relevant statement**: implementation and test readiness are proven
  at this head; the exact-debt-ledger/Quality/test reds are the single
  sanctioned two-module reachability delta; integration approval remains with
  the separately reviewed #1845/C3 change. Coverage gate (publish-set floor +
  whole-integration-diff diff coverage) was not re-executed locally this round
  (requires the postgres producer set); the leaf's own files remain covered by
  the suites above, and prior rounds measured leaf diff coverage at 100%/97%.


## Round 21 — four-gate CI-repair round re-derived at merged head c1789f8b8a25

Scope: the round was dispatched as CI gate repair for the merge-queue reds at
HEAD `c1789f8b8a25254dd5e36bfc6234d93a98c76fa6` (the branch merged develop
`af799688335f9` — the failpoint-matrix WIP — as `c1789f8b8a25`), and to resolve
the prior round's NEEDS-DEEP-REVIEW block. No source or test file changed; the
front-matter delta above is unchanged. All evidence re-executed fresh:

- **exact-debt-ledger, step by step.** `check-shipped-surface-truth.py` exit 0.
  The prescribed vulture amendment is EMPTY for the 21st consecutive round:
  with CI's exact arguments (`uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) the gate
  exits 0 at 1328 reviewed identities -> 1328 findings, `unclassified: 0`,
  `never_allowlist: 0` — no unbanked identity exists to fix or bank, so
  `quality/vulture-baseline.json` is deliberately not edited. The job's red is
  its first step, `check-ratchet-provenance.py`: 8 of 9 sub-ratchets OK, sole
  FAIL is reachability — `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` are NEW unreachable (171 vs trusted
  169), "absent from trusted base and not previously authorized".
  `load_authorizations` reads grants from the merge base
  (`af799688335f9:quality/ratchet-authorizations.json` — 0 rows for either
  module), so no edit on this branch can authorize them (the two-merge rule);
  issue #1852 forbids baseline rows, grants, and fake wiring in this leaf, and
  round 14 already removed the prohibited candidate rows (34e0559b7).
- **Quality gate.** Fails at the reachability-ratchet step for the same two
  modules (2 annotations = 2 module names): `check-reachability.py` exits 1
  with both listed as NEWLY UNREACHABLE and not in
  `quality/reachability-baseline.json`. Everything locally runnable around it
  passes: `check-reachability-dispositions.py` OK (49 groups / 169 modules),
  `check-convergence-matrix.py` OK (52 subsystems / 1363 modules),
  `check-promotion-surface.py` OK, full `check-suite-inventory.py` OK (17
  suites, 29482 collected identities, 0 duplicates), vulture OK as above.
- **test job.** Root suite `tests/` (with `RATCHET_BASE_REV` at the develop
  base): 4761 passed / 4 failed / 128 skipped. Three failures are the
  sanctioned two-module delta (`test_check_reachability.py::
  test_baseline_matches_the_tree`, `test_reachability_baseline_identity.py`
  x2). The fourth
  (`test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once`) fails only on
  `unclassified quality state: quality/ac-state.json` — an untracked,
  gitignored local cache in this worktree — and re-running the same four tests
  in a throwaway clean worktree at HEAD (no such file, CI-like) gives exactly
  **3 failed / 1 passed**, confirming round 20. Every other `test`-job package
  suite re-run green at this head: maistro-core 14627 passed / 983 skipped /
  1 xfailed; bootstrap 232; server 535; canvas 465; turing 210 +
  turing/backend 90; design 572; ext-harness 138; ext-sdk 118. rsi+evolve
  shows 3 failures, reproduced identically on the develop base `af79968` in a
  throwaway worktree (Docker-dependent evolve benchmark tests) — inherited
  from the base, not caused by this leaf.
- **Coverage gate.** The diff-coverage half re-executed at this head for the
  first time since the merge: coverage produced with the coverage-unit
  producer's exact invocation (`coverage run --branch
  --source=packages/maistro-core/src/maistro -m pytest
  packages/maistro-core/tests --timeout=30 -q`; 14627 passed), then
  `check-diff-coverage.py coverage.xml --base af799688335f9` exits 0 —
  "every measured file this change touches is at or above 90% lines / 80%
  branch arcs" (the two admission modules measured; both test files exempt;
  `_vulture_whitelist.py` sits under no measured root and is named, not
  scored). The job's red is therefore the combine step itself: under
  `set -euo pipefail` its scripts producer runs `pytest tests/ ...`, which
  aborts on the same three sanctioned reachability failures before
  `coverage xml` is written. All four merge-queue reds remain one root cause.
- **Mutation battery re-derived** in a throwaway `git worktree` at HEAD
  (assigned tree never modified; source restored from `git show HEAD:`
  between runs): swap TAKEOVER/REPLACE_EXPIRED -> 50 failed; lease row above
  binding -> 14 failed; LEGACY_UNRESOLVED row deleted (legacy treated as v2)
  -> 10 failed; mismatch above expiry -> 22 failed; unmutated control ->
  132 passed. Same 50/14/10/22 profile as rounds 14–20.
- **Focused and issue-required commands**: classifier suite 132 passed;
  classifier + `test_root_admission_identity.py` + `test_idempotency.py`
  272 passed; `mypy` clean on the classifier; ruff check + format clean on
  the leaf pair; full driver battery (uv sync, ruff check ., ruff format
  --check ., focused pytest, suite inventory) green.
- **Verdict-relevant statement**: unchanged and re-proven — implementation and
  test readiness hold at this head; each of the four merge-queue reds is the
  single sanctioned two-module reachability delta, which no in-leaf edit may
  bank, grant, or wire away; the unblock lives in the separately reviewed
  #1845/C3 integration consumer (or a base-landed authorization landing
  before it). The stack stays unmerged by design.


## Round 22 — verification round at dispatched head afc11663491e: all leaf
## acceptance criteria independently re-proven; all four merge-queue reds
## re-derived as the same sanctioned two-module delta; no repairable defect
## exists in-lane

Scope: verify/repair round dispatched at HEAD `afc11663491e35090ddc353c74f75a6c982a7d72`
(develop base `8fbbbfb91d78d`, merge base `e46ad6708fda` — both develop WIP
merges already absorbed by the branch). Every claim below was re-executed
fresh this round; no source, test, or ledger file changed, so the
`inventory-delta` front-matter above is unchanged.

- **Leaf acceptance battery, all green, re-executed**: classifier suite 132
  passed; `test_root_admission_identity.py` + unchanged `test_idempotency.py`
  140 passed; ruff check + format clean on the leaf pair and repo-wide
  (driver logs); mypy clean on `admission_generation.py`; full
  `check-suite-inventory.py` exit 0 (17 suites, 30068 collected identities,
  0 duplicates — the `+132` front-matter delta still matches). All ten
  issue-named tests present by grep; the module carries the sole production
  function `_assess` with the exact-class input gate (`type(record) is ...`),
  `[0-9a-f]{64}` fullmatch fingerprint validation, bool-rejecting signed-int64
  `now_us`, and the fixed six-row decision table in issue order.
- **Four-mutation battery re-derived at this exact head** in a throwaway
  `git worktree` (assigned tree never modified; module restored from backup
  after each mutation, md5 `257a6e45c382349dd12f559099663fbc` byte-identical
  before and after): swap TAKEOVER/REPLACE_EXPIRED -> 50 failed; lease row
  before binding -> 14 failed; LEGACY_UNRESOLVED row deleted (legacy treated
  as v2) -> 10 failed; mismatch row before expiry -> 22 failed; unmutated
  control -> 132 passed. Same 50/14/10/22 profile as rounds 13–21.
- **No-wiring purity re-verified**: grep over `packages/*/src` finds no
  production importer of `maistro.tasks.admission_generation` (only the C2
  module itself); `maistro.runs.admission_identity` is imported only by the
  C2 module and the scanner-input `_vulture_whitelist.py` addition (named
  enum members and snapshot-field names; "never executes, ships in no wheel;
  wires nothing"); `tasks/__init__.py`, `runs/__init__.py`, and
  `tasks/idempotency.py` are byte-identical to the merge base.
- **exact-debt-ledger re-derived step by step with CI's exact argv**: step 3
  vulture (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`)
  exit 0 at 1326 reviewed identities -> 1326 findings, `unclassified: 0` —
  **the prescribed vulture-ledger amendment is empty for the 22nd consecutive
  round**; step 2 `check-shipped-surface-truth.py` exit 0; step 1
  `check-ratchet-provenance.py` exit 1 with 8 of 9 sub-ratchets OK
  (adr-status-language, citation-status, promotion-surface 74->74,
  reachability-dispositions 169->169, shell-execution 3->3,
  contract-markers 358->358, enumerations 1->1, lifecycle 0->0) and the sole
  FAIL in the reachability trusted-base gate: both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_generation`
  are NEW unreachable (171 of 1366 vs trusted 169), "absent from trusted base
  and not previously authorized" and "missing from candidate baseline".
  Mechanism re-read from source this round:
  `check-reachability-provenance.py` calls
  `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)` — grants are
  read from the merge base `e46ad6708fda`, whose
  `quality/ratchet-authorizations.json` contains zero rows for either module
  identity (the 5 `admission` substring hits in the candidate's copy are
  unrelated: stranded-chat-admissions recovery, a2a transport admission,
  ScheduleRunAdmitter, canvas reconcile). No candidate-side edit — baseline
  rows, dispositions, or grants — can turn step 1 green (the two-merge rule),
  and issue #1852 forbids exactly those edits for this leaf anyway ("No fake
  callers, baseline additions, grants, disabled gates or quality waivers are
  permitted"; the round-13 removal of the earlier prohibited rows stands —
  the candidate still carries zero admission rows in
  `reachability-baseline.json`).
- **Other three reds re-bound to the same delta**: `check-reachability.py`
  lists exactly the two leaf modules as NEWLY UNREACHABLE (the Quality gate's
  failing step); the 3 root meta-test failures
  (`test_check_reachability.py::test_baseline_matches_the_tree`, both
  `test_reachability_baseline_identity.py` gate-identity assertions) diff on
  exactly those two module names and nothing else; `check-reachability-
  dispositions.py` and `check-promotion-surface.py` exit 0. The Coverage
  gate's remaining red stays its root-suite producer re-running the same 3
  tests (leaf diff coverage measured 100%/97% in rounds 15+; not re-executed
  this round).
- **quality/ merge hygiene checked per AGENTS.md**:
  `git diff --numstat origin/develop -- quality/` shows exactly one differing
  file, `workflow-inventory.json` (0 added / 7 deleted): the branch predates
  develop's `graph-pattern-reuse-bench.yml` workflow, which is absent from
  the merge base too — the branch is behind, not row-dropped;
  `check-workflow-inventory.py` exit 0.
- **Verdict-relevant statement**: implementation, focused-test, and mutation
  readiness are proven at this head; no in-lane lawful repair exists for the
  four red merge-queue checks — wiring is outside the leaf's scope, and the
  two-merge rule makes every candidate-side ledger path mechanically
  ineffective even before the issue's prohibitions bite. Retirement paths
  remain the two named since round 13: a base-landed authorization followed
  by the banking rebase, or the separately reviewed #1845 integration
  consumer that wires both modules. The stack stays unmerged by design;
  this round's only artifact is this evidence appendix.

## Round 23 — exact-debt-ledger CI-repair round at merged head 954e08435:
## the named vulture red is retired by the develop merge itself (23rd
## consecutive empty amendment); every other red re-derived as the same
## sanctioned two-module delta or develop-inherited debt

Scope: CI-repair round dispatched at HEAD `954e08435159c34d2c6142022eb51587f55b3e33`
(develop base `d99e598e1084a183d1280fbe9a2c4de8b50b7f2b`, which is also the
merge base and `origin/develop` at capture time; the branch absorbed
`82097f6b7acca58ffc27a934b305faaee7a37915` and `d99e598e1` since round 22).
Every claim below was re-executed fresh this round at this head; no source,
test, or ledger file changed, so the `inventory-delta` front-matter above is
unchanged.

- **exact-debt-ledger (the named repair) is GREEN at this head**:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` — CI's exact argv — exits 0 with 1323 reviewed
  identities -> 1323 findings, `unclassified: 0`, `never_allowlist: 0`.
  **The prescribed vulture-ledger amendment is empty for the 23rd
  consecutive round.** The merge-queue red recorded at `afc11663491e` is
  retired by the develop merge, not by an edit: develop's side legitimately
  removed the three `unused method 'enable'` rows
  (`security/pg_strikes.py`, `security/strike_recovery.py`,
  `security/strikes.py` — methods wired by #2019-era changes), and after the
  merge `git diff --numstat origin/develop -- quality/` is EMPTY (the
  branch's quality/ tree is identical to develop's; no rows lost, per the
  AGENTS.md merge-hygiene rule).
- **check-ratchet-provenance** exits 1 with 8 of 9 sub-ratchets OK
  (adr-status-language, citation-status, promotion-surface, reachability-
  dispositions 169->169, shell-execution 3->3, contract-markers 358->358,
  enumerations 1->1, lifecycle 0->0) and the sole FAIL in the reachability
  trusted-base gate: `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` NEW unreachable, 171 of 1367 modules
  vs trusted 169. Grants are read from merge base `d99e598e1`, whose
  `quality/ratchet-authorizations.json` carries zero rows for either
  identity (11 reachability authorizations, none admission-related; the
  candidate's copy is identical). The two-merge rule makes every
  candidate-side ledger edit mechanically ineffective, and issue #1852
  forbids baseline additions, grants, and waivers for this leaf outright;
  the candidate still carries zero admission rows in
  `reachability-baseline.json`.
- **check-reachability** exits 1 listing exactly the two leaf modules as
  NEWLY UNREACHABLE — added = the two leaf modules, stale = none (scan 171,
  baseline 169, diff computed directly against
  `quality/reachability-baseline.json`). This is the Quality gate's failing
  step; every other deterministic step of that job was re-run green this
  round: ruff check + format, radon-baseline, release-consistency,
  doc-links, workspace-retirement, route-permissions, principal-identity,
  frontend-typed-client, credential-authority (both invocations),
  wiring-reads, agent-store-writes, contract-markers, convergence-matrix,
  reachability-dispositions, security-inventory, image-inventory,
  image-pins, workflow-inventory, backlog-consistency,
  execution-lifecycles, model-egress, foreign-harness-egress,
  shipped-surface-truth — all exit 0 — plus xenon with CI's exact
  invocation (139 block violations <= baseline 145, 0 module-rank, 0
  average; the one `admission`-named hit is the unrelated canvas
  `_reconcile_admission`, rank C, counted in the 139).
- **test job red re-derived at this head**: root suite
  (`uv run pytest tests/ --ignore=tests/tools/registry`) 4867 passed /
  4 failed locally. Three are the sanctioned reachability meta-tests
  (`test_check_reachability.py::test_baseline_matches_the_tree`, both
  `tests/test_reachability_baseline_identity.py` gate-identity assertions)
  diffing on exactly the two leaf module names. The fourth,
  `test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`,
  is proven a local-environment artifact this round: it fails only because a
  gitignored, regenerable `quality/ac-state.json` (output of
  `scripts/check-ac-state.py`, dated before this session, absent from
  `git ls-tree` and matched by `.gitignore:81`) sits in this worktree;
  with the artifact relocated the same test passes 1/1, and the artifact
  was restored byte-identical afterwards (599725 bytes). A fresh CI
  checkout has no such file, so the CI red is exactly the 3 sanctioned
  meta-tests.
- **Changed-package suite**: `packages/maistro-core/tests` 14973 passed /
  2 failed / 1030 skipped. Both failures
  (`extensions/test_cli_certification.py::test_certify_refuses_a_malformed_signing_key`,
  `extensions/test_cli_compat.py::test_compat_preflight_rejects_unreadable_input`)
  are **develop-inherited, not branch-caused**: both files ship unchanged
  from develop commit `2a11c1cc0` (#2019), and both tests fail identically
  at base `d99e598e1` itself, re-executed in a throwaway worktree
  (`git diff d99e598e1 HEAD -- packages/maistro-core/tests/extensions/` is
  empty). The failures are the tests' own wrap-sensitive assertion ("not
  a hex Ed25519 private key" split across wrapped lines when the pytest
  tmp path prefix is long); they are out of this lane's scope and stand as
  develop debt.
- **Coverage gate**: leaf diff coverage re-derived against base
  `d99e598e1` — `admission_generation.py` 100% lines, `admission_identity.py`
  97% (3 missed of 242 stmts), `check-diff-coverage.py` exit 0 (test files
  exempt by declaration; `_vulture_whitelist.py` unmeasured by any
  producer, as in every prior round). The CI Coverage-gate red remains
  bound to its root-suite producer re-running the 3 sanctioned meta-tests,
  not to any leaf surface.
- **Leaf acceptance battery re-proven, all green**: classifier suite 132
  passed; `test_root_admission_identity.py` + unchanged `test_idempotency.py`
  140 passed; mypy clean on both leaf modules; the module md5
  `257a6e45c382349dd12f559099663fbc` is byte-identical to round 22; full
  `check-suite-inventory.py` exit 0 — 17 suites, 30301 collected
  identities, 0 duplicates (grown from round 22's 30068 solely by
  develop's own additions; the recorded inventory baseline came with the
  merge and the `+132` front-matter delta still matches). Purity
  re-verified: no production importer of `maistro.tasks.admission_generation`;
  `maistro.runs.admission_identity` imported only by the C2 module and the
  scanner-input `_vulture_whitelist.py`.
- **Four-mutation battery re-derived at this exact head** in a throwaway
  `git worktree` (assigned tree never modified; module restored from
  backup after each mutation, md5 `257a6e45c382349dd12f559099663fbc`
  byte-identical before and after; worktree removed clean): swap
  TAKEOVER/REPLACE_EXPIRED -> 50 failed; lease row before binding -> 14
  failed; LEGACY_UNRESOLVED row deleted (legacy treated as v2) -> 10
  failed; mismatch row before expiry -> 22 failed; unmutated control ->
  132 passed. Same 50/14/10/22 profile as rounds 13–22.
- **Verdict-relevant statement**: the named exact-debt-ledger repair is
  complete and proven green at this head with an empty amendment; no
  in-lane lawful repair exists for the remaining merge-queue reds — the
  reachability/provenance pair and the 3 root meta-tests wait on the
  unchanged retirement paths (a base-landed authorization plus banking
  rebase, or the separately reviewed #1845 integration consumer), and the
  2 extension-test failures are develop-inherited debt on files this
  branch never touched. The stack stays unmerged by design; this round's
  only artifact is this evidence appendix.

## Round 24 — verification round at dispatched head c5acaf9ac170: hosted CI
## logs completed and read; all four red jobs root-caused to the single
## sanctioned two-module unwired delta; the named vulture red does not exist
## in CI's own log; no repairable defect exists in-lane

Scope: verification round dispatched at HEAD `c5acaf9ac1702c93d861dcd1003b08473c1932bb`
(develop base `675db8be6c41b020ffffb224b2748c159c78a122`; the branch tip is
byte-identical in leaf content to the head rounds 22–23 measured — module md5
`257a6e45c382349dd12f559099663fbc` re-verified). New evidence this round: the
four hosted check runs that prior rounds could only record as `in_progress`
finished, and their logs were read (read-only `gh run view --log`,
jobs 113646100595, 113646100253, 113646100590, 113648188332, run 37876462146/7/107).
No source, test, or ledger file changed, so the `inventory-delta` front-matter
above is unchanged; this appendix is the round's only artifact.

- **All four CI reds are one root cause.** In CI's own logs the candidate is
  the synthetic merge `8a817e58abd7` over base `1c55afe51896`:
  - *exact-debt-ledger* (job 113646100595) fails in its FIRST step,
    `check-ratchet-provenance.py`: "reachability ... 169 unreachable modules
    -> 171 unreachable of 1377 modules". The vulture sub-ratchet inside the
    same job printed GREEN: "1323 reviewed identities -> 1323 findings",
    `unclassified: 0`. The lane-brief repair target (unbanked vulture
    identities) does not exist; the red is the sanctioned unwired-module
    delta, so the prescribed `quality/vulture-baseline.json` amendment is
    empty for the 24th consecutive round.
  - *Quality gate* (job 113646100253) is green through every earlier step —
    ruff both, radon, xenon (139 block violations <= 145, 0 module, 0
    average), vulture ledger (1323 -> 1323) — and fails at the next step,
    `check-reachability.py`: "2 module(s) are NEWLY UNREACHABLE", naming
    exactly `maistro.runs.admission_identity` and
    `maistro.tasks.admission_generation`.
  - *test* (job 113646100590): "3 failed, 4900 passed, 128 skipped" — the
    three sanctioned reachability meta-tests
    (`test_check_reachability.py::test_baseline_matches_the_tree`, both
    `tests/test_reachability_baseline_identity.py` gate-identity assertions),
    each diffing on exactly the two leaf module names. The `##[error]`
    `RuntimeError('Event loop is closed')` lines in the server step are
    non-fatal teardown noise: that step totals "535 passed, 9 skipped".
  - *Coverage gate* (job 113648188332): its `combine` sweep totals
    "3 failed, 5004 passed" — the same three sanctioned meta-tests.
- **Local re-execution at this head matches CI**: focused suites 205 passed
  (132 assessment + 73 identity); `test_root_admission_identity.py` +
  unchanged `test_idempotency.py` 140 passed; mypy clean on both leaf
  modules; `ruff check .` and `ruff format --check .` clean; CI-exact
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exit 0 (1323 == 1323); `check-reachability.py` exit 1
  listing exactly the two leaf modules; `check-reachability-dispositions.py`
  OK (49 groups / 169 banked); `check-promotion-surface.py` OK; full
  `check-suite-inventory.py` OK (17 suites, 30588 collected identities,
  0 duplicates); `git diff --numstat origin/develop -- quality/` EMPTY
  (no self-granted baseline/grant; the two-merge rule makes a candidate-side
  grant mechanically ineffective anyway, and issue #1852 forbids one).
- **Meta-tests reproduced locally**: `pytest tests/test_check_reachability.py
  tests/test_reachability_baseline_identity.py` -> exactly 3 failed /
  35 passed, the same three identities CI failed on, for the same two-module
  delta.
- **Mutation spot-check re-executed at this head** (rounds 13–23 profile):
  swapping the TAKEOVER and REPLACE_EXPIRED rows in the decision table makes
  the assessment suite fail 50 / pass 82; the module was restored
  byte-identical afterwards (md5 `257a6e45c382349dd12f559099663fbc`,
  `git status` clean). A `/tmp` `pythonpath` overlay attempt was tried first
  and discarded with evidence: the installed regular package `maistro`
  shadows a namespace-portion overlay (`import` resolved to the worktree
  file), which is why rounds 20+ mutate in place from a byte-identical
  backup.
- **Develop-sync risk checked and retired**: `origin/develop` moved two
  commits past the merged base (`30a8ff9d7` #2073, `675db8be6` #2064, both
  research-test additions). `git merge-tree --write-tree HEAD origin/develop`
  is conflict-free; neither side touched the other's inventory-notes (develop
  added `894-critical-zone-mutation-strategy.md` and
  `925-planning-strategy-benchmark.md` with their own deltas), so the
  delta-sum ledger design keeps the synthetic merge's suite inventory
  consistent — CI's own run over candidate `8a817e58abd7` already exercised a
  develop-ahead merge and showed no inventory or research failure. The lane
  brief's merge-origin/develop trigger (a sync conflict) is not met.
- **Verdict-relevant statement**: unchanged from round 23 — the leaf's
  implementation/test/inventory acceptance is fully proven at this head with
  zero vulture-ledger debt; the only merge-queue reds are the sanctioned
  unwired-module reachability delta (four jobs, one cause), which issue
  #1852 forbids repairing in-lane (no wiring, no baseline entries, no
  grants) and which awaits the separately reviewed #1845 integration
  consumer or a base-landed authorization plus banking rebase. The stack
  stays unmerged by design.

## Round 25 — post-develop-merge re-validation at `e52a5b4440d2` (2026-10-09)

The branch now contains `origin/develop` (`675db8be6c41`) via merge commit
`e52a5b444`; the diff vs develop is exactly the eight sanctioned leaf files
(two production modules, two test files, two inventory notes,
`_vulture_whitelist.py` extension) and `git diff --numstat origin/develop --
quality/` is empty — no ledger, grant, or baseline row was touched. All
round-24 evidence was re-derived at this head rather than trusted:

- **Gates (CI argv)**: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exit 0, 1323 == 1323 (the
  lane-brief vulture amendment is empty — no unbanked identities exist);
  `check-ratchet-provenance.py` fails ONLY on the reachability ratchet (169 →
  171 of 1377, naming `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation`); `check-reachability.py` exit 1 with
  exactly those two NEWLY UNREACHABLE modules; `check-shipped-surface-truth.py`,
  `check-reachability-dispositions.py` (169 dispositioned) and
  `check-promotion-surface.py` all exit 0.
- **Tests**: focused battery `test_admission_generation_assessment.py +
  test_root_admission_identity.py + test_idempotency.py` = 272 passed; mypy
  clean on both new modules; ruff check/format clean on all four leaf files;
  meta-sweep `tests/test_check_reachability.py +
  tests/test_reachability_baseline_identity.py` = exactly 3 failed / 35
  passed (the same three gate-identity tests CI's `test` and Coverage jobs
  failed on, all diffing on the same two-module delta);
  `check-suite-inventory.py` full run OK, 17 suites, 30650 collected node
  IDs.
- **All four issue-named mutations re-executed at this head**; each restore
  verified byte-identical (md5 `257a6e45c382349dd12f559099663fbc`): swap
  TAKEOVER/REPLACE_EXPIRED → 50 failed / 82 passed; lease row before binding
  → 14 failed / 118 passed; LEGACY_UNRESOLVED row deleted (legacy falls
  through to v2 lease logic) → 10 failed / 122 passed; mismatch row before
  expiry → 22 failed / 110 passed.
- **Whitelist extension proven load-bearing, not cosmetic**: reverting only
  the `_vulture_whitelist.py` hunk (develop's file, branch modules present)
  makes the vulture gate fail 1325 vs 1323 with two unbanked identities —
  `admission_identity.py:222/223` `receipt_snapshot`/`provenance_snapshot`
  dataclass fields validated by name in `__post_init__` — demanding a
  base-landed grant. The extension is therefore the only issue-compliant way
  to ship C1's fields (the file's established shipped-first posture, e.g.
  CampaignSelector), changes no gate outcome on its own (reachability stays
  red by design), and keeps `quality/` byte-identical to develop.
- **Blocker statement (unchanged in substance)**: the four red hosted-CI jobs
  at `c5acaf9` share the single sanctioned two-module unwired reachability
  delta, reproduced locally in full at this head. Issue #1852 forbids
  in-lane repair (no wiring, no baseline entries, no grants, no waivers) and
  mandates reporting implementation/test readiness plus the explicit merge
  blocker while leaving the stack unmerged until the separately reviewed
  #1845 integration head. This lane takes no merge/PR action.

## Round 26 — verify/repair round at dispatched head `995de9cf3b0e` (2026-10-09):
## every acceptance criterion independently re-executed; all four hosted CI
## reds re-derived as the same sanctioned two-module delta; no repairable
## defect exists in-lane; prior deep-review block closed by fresh evidence

Scope: verification round dispatched at HEAD
`995de9cf3b0e809b66b7672937d0ad3d86e70db6` (develop base `d592654aca614`,
merge base `2b897bc78b68`; PR #1941 head == dispatched head, open, unmerged).
No prior verification claim was trusted: every item below was executed fresh
this round. No source, test, or ledger file changed, so the `inventory-delta`
front-matter above is unchanged; this appendix is the round's only artifact.
The assigned worktree was never mutated — the mutation and whitelist
experiments ran in a throwaway `git worktree` at HEAD.

- **Leaf acceptance battery, all green, re-executed**: classifier suite 132
  passed (front-matter `+132` == actual collection);
  `test_root_admission_identity.py` + unchanged `test_idempotency.py` 140
  passed; `ruff check` + `ruff format --check` clean on the leaf pair;
  `mypy` clean on `admission_generation.py`; full `check-suite-inventory.py`
  exit 0 (17 suites, 30691 collected identities, 0 duplicates). The module's
  decision table (`admission_generation.py:119-136`) re-read against the
  issue text row by row: inclusive expiry first, mismatch second, binding
  third, legacy fourth, lease fifth, `PENDING` fallback; exact-class input
  gate (`type(record) is ...`), `[0-9a-f]{64}` fullmatch fingerprint,
  bool-rejecting signed-int64 `now_us`; `acknowledged_at_us` never read.
  All ten issue-named tests present by grep.
- **Four-mutation battery re-derived at this exact head** in a throwaway
  worktree (`uv sync --locked --extra dev` first, assigned tree untouched):
  swap TAKEOVER/REPLACE_EXPIRED -> 50 failed / 82 passed; lease row hoisted
  above binding (diff-verified applied) -> 14 failed / 118 passed;
  LEGACY_UNRESOLVED row deleted (legacy falls through to v2 lease logic) ->
  10 failed / 122 passed; mismatch row hoisted above expiry -> 22 failed /
  110 passed; unmutated control -> 132 passed with md5
  `257a6e45c382349dd12f559099663fbc` byte-identical before and after and a
  clean `git status`. Same 50/14/10/22 profile as rounds 13–25. (One harness
  slip was caught by the battery itself: a pattern-based string replace that
  silently no-op'd produced 132 passed — repeated with a line-splice mutation
  proven by `git diff` before trusting the run.)
- **exact-debt-ledger re-derived step by step with CI's exact argv**: the
  prescribed vulture amendment is EMPTY for the 26th consecutive round —
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exits 0 at 1323 reviewed identities -> 1323 findings,
  so no unbanked identity exists to fix or bank and
  `quality/vulture-baseline.json` is deliberately not edited.
  `check-shipped-surface-truth.py` exit 0. The job's red is its first step,
  `check-ratchet-provenance.py`: 8 of 9 sub-ratchets OK (adr-status-language,
  citation-status, promotion-surface 74->74, reachability-dispositions
  169->169, shell-execution 3->3, contract-markers 358->358, enumerations
  1->1, lifecycle 0->0) and the sole FAIL in the reachability trusted-base
  gate: `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` are NEW unreachable (171 of 1377 vs
  trusted 169), "absent from trusted base and not previously authorized".
  Grants are read from the merge base, which carries zero rows for either
  identity (the two-merge rule), and issue #1852 forbids baseline rows,
  grants, and fake wiring for this leaf outright.
- **Quality gate / test / Coverage reds re-bound to the same delta, each
  reproduced locally**: `check-reachability.py` exit 1 listing exactly the
  two leaf modules as NEWLY UNREACHABLE (the Quality gate's failing step);
  `check-reachability-dispositions.py` exit 0 (49 groups / 169 banked) and
  `check-promotion-surface.py` exit 0; the root-suite meta-tests fail at
  exactly three identities — `test_check_reachability.py::
  test_baseline_matches_the_tree` (stderr `::error title=New unreachable
  modules::maistro.runs.admission_identity,maistro.tasks.admission_generation`)
  and both `test_reachability_baseline_identity.py` gate-identity assertions
  (`check.main() == 0` fails; `set(unreachable) == baseline` diffs on exactly
  the two leaf modules) — which is what CI's `test` job reds on and what
  aborts the Coverage gate's `combine` step (its `--source=scripts` producer
  re-runs `pytest tests/ ...` under `set -euo pipefail`, so it dies before
  `coverage xml`). Leaf diff coverage re-measured with the coverage-unit
  producer recipe against the merge base:
  `admission_generation.py` 100% (25 stmts / 12 branches, 0 missed),
  `admission_identity.py` 97% (3 of 242 missed), `check-diff-coverage.py
  coverage.xml --base 2b897bc78b68` exit 0 — the Coverage red is therefore
  not a coverage defect.
- **Whitelist extension re-proven load-bearing**: reverting only the
  `_vulture_whitelist.py` hunk (develop's file, branch modules present) in
  the throwaway worktree makes the vulture gate report 2 NEW unbanked
  identities — `admission_identity.py:222/223`
  `receipt_snapshot`/`provenance_snapshot` — demanding a base-landed grant;
  restored byte-identical afterwards.
- **Purity and stack hygiene re-verified**: grep over `packages/*/src` finds
  no production importer of `maistro.tasks.admission_generation`;
  `maistro.runs.admission_identity` is imported only by the C2 module and
  the scanner-input `_vulture_whitelist.py`; the branch diff vs the merge
  base is exactly the eight sanctioned leaf files; no commit subject and not
  the PR body carries a closure keyword (PR body says only "Refs #1852").
- **Develop-sync risk re-checked and not triggered**: `origin/develop` moved
  two commits past the merge base (`c4bd94439` M9-F WIP, `d592654ac` M8-F1
  WIP); `git merge-tree --write-tree HEAD origin/develop` is conflict-free;
  the only `quality/` difference is develop's own newer
  `fleet-routing-bench.yml` row in `workflow-inventory.json` (branch behind,
  not row-dropped). The lane brief's merge-origin/develop trigger (a sync
  conflict) did not occur, so no merge was made.
- **Verdict-relevant statement**: implementation, focused-test, inventory,
  and mutation readiness are all independently proven at this exact head;
  each of the four merge-queue reds reduces to the single sanctioned
  two-module unwired reachability delta, which no in-leaf lawful edit can
  retire (the two-merge rule makes candidate-side ledger rows mechanically
  ineffective before the issue's prohibitions even bite). Retirement paths
  remain the two named since round 13: a base-landed authorization followed
  by the banking rebase, or the separately reviewed #1845 integration
  consumer that wires both modules and prunes the entries on arrival. The
  stack stays unmerged by design; this lane takes no merge/PR action.

## Round 27 — repair round at dispatched head `10dfd9c1dea0` (2026-10-09):
## lane-brief vulture amendment re-run and proven EMPTY; all four hosted reds
## re-executed locally as the same sanctioned two-module delta

The repair brief asked for a vulture per-identity ledger amendment against
`exact-debt-ledger`'s red. Re-running the job's three steps at this exact
head shows there is nothing to amend:

- **`check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's argv) exit 0**: 1323 findings ==
  1323 reviewed identities, every bucket classified, `unclassified: 0`,
  `never_allowlist: 0`. Zero unbanked identities exist, so no
  `quality/vulture-baseline.json` row is added, removed, or touched
  (`git diff --numstat` over `quality/` vs merge base `d592654ac` is
  empty — unchanged from every prior round).
- **`check-shipped-surface-truth.py` exit 0**; the job's sole failing
  step remains `check-ratchet-provenance.py`, exit 1 with 8 of 9
  sub-ratchets OK and the one FAIL the reachability trusted-base gate:
  `maistro.runs.admission_identity` + `maistro.tasks.admission_generation`
  are NEW unreachable (171 of 1379 vs trusted 169), "absent from trusted
  base and not previously authorized". The two-merge rule reads grants
  from the merge base (zero rows for either identity), and issue #1852
  forbids candidate-side baseline rows, grants, and fake wiring for this
  leaf — so the red is the documented integration blocker, not debt to
  bank.
- **The other three hosted reds re-derived at this head**:
  `check-reachability.py` exit 1 naming exactly the two leaf modules as
  NEWLY UNREACHABLE (the Quality gate's failing step);
  `check-reachability-dispositions.py` exit 0 (49 groups / 169 banked) and
  `check-promotion-surface.py` exit 0; exactly three root-suite meta-tests
  fail and only on the two-module delta (`test_check_reachability.py::
  test_baseline_matches_the_tree`, both
  `test_reachability_baseline_identity.py` gate-identity assertions) —
  CI's `test` red, and the Coverage gate's `combine` step aborts on the
  same producer per round 26's trace.
- **Focused acceptance re-executed**: C2 suite 132 passed; C1 + unchanged
  live-flow suite 140 passed; `mypy` on the classifier clean; `ruff check`
  and `ruff format --check` on both leaf files clean; all ten issue-named
  tests present by name; no production importer of
  `maistro.tasks.admission_generation` under `packages/*/src`; no closure
  keyword in any commit subject/body since the merge base.
- **Mutation battery re-executed in a `/tmp` shadow copy (assigned tree
  byte-identical, `admission_generation.py` md5 `257a6e45…` before and
  after)**: swap TAKEOVER/REPLACE_EXPIRED -> 50 failed; lease before
  binding -> 14 failed; legacy pending classified as v2 -> 10 failed;
  mismatch before expiry -> 22 failed; pristine control -> 132 passed.
- **Verdict-relevant statement**: the lane brief's prescribed repair is
  empty by construction and the previous deep-review block stays closed —
  every acceptance criterion is independently proven at this exact head,
  and each hosted red reduces to the single sanctioned two-module unwired
  reachability delta that no lawful in-leaf edit can retire. The stack
  stays unmerged awaiting the separately reviewed #1845 integration
  consumer; this lane takes no merge/PR action.

## Round 28 — repair round at dispatched head `6b3226984c72` (2026-10-09):
## develop merge absorbed; lane-brief vulture amendment re-proven EMPTY at the
## new head; exact-debt-ledger red fully attributed to the sanctioned
## two-module reachability provenance delta

The dispatched head advances round 27's `10dfd9c1dea0` by exactly the
absorption of `origin/develop` `0d49d4e068de` (two research-WIP commits,
#2076/#2077): `git log 88240af..HEAD` is the merge commit plus those two, and
`git diff 88240af..HEAD` over the four leaf source/test files and
`_vulture_whitelist.py` is byte-empty, so the round 25–27 mutation battery
(50/14/10/22 failures + 132 pristine control) carries over unchanged to this
head. `origin/develop` is still `0d49d4e068de` after a fresh fetch and
`git merge-base HEAD origin/develop` equals it — the lane brief's develop-sync
trigger (a merge conflict) did not occur; the merge was already in place at
dispatch.

- **Lane-brief vulture repair executed and empty**: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact argv) exits 0 at this head — 1323
  findings == 1323 reviewed identities, `unclassified: 0`,
  `never_allowlist: 0`. Zero unbanked identities exist, so no
  `quality/vulture-baseline.json` row is added or removed;
  `git diff --numstat origin/develop -- quality/` is empty.
- **exact-debt-ledger red fully attributed**: of the job's three steps,
  `check-shipped-surface-truth.py` exits 0 and the vulture step exits 0; the
  sole failure is `check-ratchet-provenance.py` exit 1 ("ratchet provenance
  inventory is incomplete"), whose failing sub-gate is
  `check-reachability-provenance.py`: reachability ratchet 169 trusted ->
  171 current of 1379 modules, with `maistro.runs.admission_identity` and
  `maistro.tasks.admission_generation` NEW unreachable, "absent from trusted
  base and not previously authorized". All other sub-ratchets report OK
  (shell 3/3, contract-markers 358/358, enumerations 1/1, lifecycle 0/0).
  This is the issue-sanctioned #1845 integration blocker: #1852 forbids
  candidate-side reachability baseline rows, grants, or fake wiring for this
  leaf, and the two-merge rule reads authorizations from the grantless merge
  base, so no lawful in-leaf edit can retire the red.
- **Other hosted reds re-derived at this head**: `check-reachability.py`
  exit 1 naming exactly the two leaf modules as NEWLY UNREACHABLE;
  `check-reachability-dispositions.py` exit 0 (49 groups / 169 banked);
  `check-promotion-surface.py` exit 0. The root-suite reachability meta-tests
  fail 3 / pass 35 and every assertion diff names only the two-module delta
  (`test_check_reachability.py::test_baseline_matches_the_tree`, both
  `test_reachability_baseline_identity.py` gate-identity assertions, the
  set-diff "Extra items" being exactly the two identities) — CI's `test` red,
  with the Coverage gate's producers aborting on the same root suite.
- **Focused acceptance re-executed at this exact head**: C2 suite 132
  passed; C1 + unchanged live-flow suite 140 passed; `ruff check` and
  `ruff format --check` on both leaf files clean; `mypy` on the classifier
  clean; full `check-suite-inventory.py` exit 0 (17 suites, 30934 collected
  identities, 0 duplicates, matching the recorded inventory, whose C2 delta
  is this note's `+132` front matter); all ten issue-named tests present by
  name.
- **Hygiene re-verified**: grep over `packages/*/src` finds no production
  importer of `maistro.tasks.admission_generation`; whitelist additions
  remain C1 snapshot-field names and `AdmissionAssessment` StrEnum members
  only (never `_assess`/`admission_generation`); no commit subject or body
  in `0d49d4e068de..HEAD` carries a closure directive with an issue
  reference (0 matches for fix(es)/clos(es)/resolv(es) + number).
- **Verdict-relevant statement**: the round's prescribed repair (the vulture
  per-identity ledger amendment) is empty by construction at this head and
  the carried NEEDS-DEEP-REVIEW block is resolved by full fresh
  re-verification — every leaf acceptance criterion is independently proven
  at `6b3226984c72`, and every merge-queue red reduces to the single
  sanctioned two-module unwired reachability delta. Retirement paths remain
  the separately reviewed #1845 integration consumer (which wires both
  modules and prunes any banked rows on arrival). The stack stays unmerged
  by design; this lane takes no merge/PR action.

## Round 29 (independent repair-round re-verification at c531f4d8a682)

Fresh worker, no prior claims trusted; every gate re-run locally at the
dispatched exact head `c531f4d8a682fd9d66aa17e182a7c5f394c133a0`
(develop base `0d49d4e068de`). No source, test, or quality/ file changed this
round; the only tree edit is this evidence section. Per-command evidence:

- **Lane-brief vulture amendment re-proven empty (29th round)**:
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exit 0, 1323 reviewed identities ->
  1323 findings, 0 unbanked — `quality/vulture-baseline.json` needs no row.
  Load-bearing-whitelist probe: reverting the branch's
  `_vulture_whitelist.py` additions makes exactly 2 unbanked identities, both
  C1 `admission_identity.py` snapshot fields (receipt/provenance_snapshot);
  the C2 module and `_assess` contribute zero identities either way,
  matching the issue's symbol-collision caveat. Whitelist restored
  byte-identical (sha256 b13c13b4…).
- **exact-debt-ledger trio at CI argv** (`RATCHET_BASE_REV=origin/develop`):
  `check-shipped-surface-truth.py` exit 0; vulture exit 0 (above);
  `check-ratchet-provenance.py` exit 1 solely via the reachability
  sub-ratchet — 169 trusted -> 171 current unreachable, the two leaf modules
  "NEW … absent from trusted base and not previously authorized"; shell 3/3,
  contract-markers 358/358, enumerations 1/1, lifecycle 0/0 all OK. The
  two-merge rule makes this unretirable in-lane; the issue forbids
  candidate-side rows/grants and mandates leaving the stack unmerged.
- **Quality-gate attribution completed by full local step battery**: of the
  job's gates re-run with CI env, only `check-reachability.py` fails (exit 1,
  "171 unreachable", the two NEW modules named; +1 local-only red from a
  gitignored `quality/ac-state.json` artifact — `.gitignore:81` — that a
  clean CI checkout cannot contain). Verified exit 0 at this head:
  radon ledger, enumerations, workspace-retirement, route-permissions,
  principal-identity, frontend-typed-client, credential-authority,
  wiring-reads, agent-store-writes, contract-markers, convergence-matrix,
  reachability-dispositions, security-inventory, bump-version,
  release-consistency, doc-links, both vendored-benchmark checks, and xenon
  (139 block violations <= baseline 145; 0 module-ledger; 0 average).
- **Root suite re-derived as CI's `test` job runs it** (`REQUIRE_AUTH=false
  MAISTRO_DRY_RUN=1 RATCHET_BASE_REV=origin/develop pytest tests/
  --ignore=tests/tools/registry`): 4 failed / 4947 passed / 128 skipped —
  the 3 sanctioned reachability meta-tests (each diff naming exactly
  `maistro.runs.admission_identity` + `maistro.tasks.admission_generation`)
  plus the local gitignored ac-state artifact (CI-invisible). All other
  `test`-job Python suites green: server 535, turing 210, turing/backend 90,
  design 572, ext-harness 273, ext-sdk 147.
- **Coverage-gate attribution**: producers were green per the recorded
  check-runs; the combine step re-runs the root suite under `set -e`, so its
  red is the same three meta-tests. The diff-coverage gate itself re-proven
  green at this head: leaf-only branch coverage run over
  `--source=packages/maistro-core/src/maistro`, `check-diff-coverage.py
  coverage.xml --base origin/develop` exit 0 ("every measured file this
  change touches is at or above 90% lines / 80% branch arcs"; tests exempt;
  `_vulture_whitelist.py` named out-of-scope, not failed).
- **Leaf acceptance re-executed**: C2 suite 132 passed; C1 + unchanged
  live-flow suite 140 passed (272 with `test_idempotency.py` in one run);
  `ruff check .` + `ruff format --check .` clean; `mypy` clean on both leaf
  modules; full `check-suite-inventory.py` exit 0 (17 suites, 30934
  identities, 0 duplicates); all ten issue-named tests present by name;
  `git diff --numstat origin/develop -- quality/` empty (no baseline rows,
  no grants, no ledger edits).
- **Required mutations re-caught in place** (backup -> mutate -> focused run
  -> restore byte-identical sha256 578c1f17…): TAKEOVER<->REPLACE_EXPIRED
  swap 50 failed; lease-before-binding reorder 16 failed; legacy-pending-as-v2
  (LEGACY_UNRESOLVED row dropped) 10 failed; mismatch-before-expiry reorder
  22 failed. 132/132 pass on the restored file.
- **Verdict-relevant statement**: unchanged from round 28 and now re-proven
  first-hand — implementation and tests meet every #1852 acceptance
  criterion at this exact head; all four hosted merge-queue reds reduce to
  the single issue-sanctioned two-module unwired reachability delta whose
  lawful retirement is the separately reviewed #1845 integration consumer.
  The stack stays unmerged by design; this lane takes no merge/PR action.
