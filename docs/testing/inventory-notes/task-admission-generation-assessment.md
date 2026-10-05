---
inventory-delta:
  packages/maistro-core/tests: +105
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
