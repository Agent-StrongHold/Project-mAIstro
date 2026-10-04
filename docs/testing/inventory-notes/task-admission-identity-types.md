---
inventory-delta:
  packages/maistro-core/tests: +73
---

# #1851 root-admission identity types evidence

Adds the inactive contract module
`packages/maistro-core/src/maistro/runs/admission_identity.py`
(`CanonicalJsonObject`, admission ticket/envelope/binding/record DTOs, claim
and mutation result variants, `AdmissionAssessment`) with its contract test
suite `packages/maistro-core/tests/runs/test_root_admission_identity.py`. No
production module imports the new module in this leaf, and
`maistro.runs.__init__` is unchanged, so no other suite moves.

Collected node IDs on `packages/maistro-core/tests`: 12749 before, 12822 after
(`pytest --collect-only -q`), net **+73** — the new file only; it covers
canonical-JSON normalization/rejection, DTO freezing, the scope+generation+
owner fencing conjunction, binding/acknowledgement invariants, legacy-record
shape, parameterized constructor rejection, result/snapshot agreement, and
owner-token repr omission.

Focused validation at this leaf: 73 passed, ruff check/format clean, mypy
strict clean on the module.

## CI-repair round (merge-queue evaluation at 46af4b5f6f2e)

The merge queue blocked on four checks with two root causes, both expected
drift from shipping an inactive contract leaf:

- **exact-debt-ledger + Quality-gate vulture step:** the scan surfaced 9 new
  `pydantic-declarative-field` identities (the two envelope snapshot fields,
  both `format_version` discriminators, five `AdmissionAssessment` members).
  Banking them in `quality/vulture-baseline.json` cannot pass the gate —
  `ratchet_provenance.load_authorizations` reads grants **from the merge
  base**, which predates the module, so the identities are unauthorizable in
  this branch by construction. Repaired the way the repo already handles
  contract-first surfaces (CampaignSelector, the learning lifecycle, the
  HarnessTargetKind/EvalMethod members): scanner-input references in
  `packages/maistro-core/src/_vulture_whitelist.py`, with the rationale
  inline. The ledger and `ratchet-authorizations.json` are untouched; the
  scan returns to exactly the trusted 1342 identities. When the #1845
  consumer lands, these references should be deleted in the same change.
- **`test` + Coverage `combine`:** `maistro.runs.admission_identity` was
  newly unreachable. Baselined it in `quality/reachability-baseline.json`
  and dispositioned it CONNECT (group `runs-root-admission-contracts`,
  subsystem "Run / NodeRun / Attempt lifecycle") naming the #1845 admission
  backend as the root that will reach it; the gate enforces pruning the
  entry the moment that consumer lands, so the record cannot outlive the
  wiring.

Re-run locally with CI's exact invocations: `check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (1342
reviewed identities → 1342 findings, exit 0), `check-reachability.py` (175
unreachable, exit 0), `check-reachability-dispositions.py` (50 groups cover
all 175, exit 0), the three previously failing tests
(`test_baseline_matches_the_tree`,
`test_the_committed_baseline_passes_the_gate_it_now_carries`,
`test_the_baseline_is_exactly_the_unreachable_set`) plus the full 38-test
reachability pair, ruff check/format, and mypy (no new errors vs the
pre-existing 5 `maistro_bootstrap` import-not-found). No test files moved:
inventory re-checked at 12833 collected node IDs on
`packages/maistro-core/tests`, delta unchanged (+73).

**Correction to the paragraph above and to the 9a15e6830 commit subject:**
"green the merge-queue gates" overstated what was proven. The candidate-side
layer (the `quality.yml` Quality-gate steps listed there) does pass at this
head, but the trusted-base layer of the exact-debt-ledger job was and is
still red. The next section records the verified state and the only actions
that can turn it green.

## Trusted-base state at eeb4c600 (second repair round, measured 2026-10-04)

Executed at this head with `RATCHET_BASE_REV=2a57094fe0d62d942f950601bce748ea3a79e33b`
(the effective merge base: `git merge-base HEAD origin/develop`, with
`origin/develop` at 91996e19):

- `check-reachability-provenance.py` → rc=1: "maistro.runs.admission_identity:
  NEW unreachable module absent from trusted base and not previously
  authorized" (174 → 175 unreachable).
- `check-reachability-dispositions-provenance.py` → rc=1: "NEW disposition
  absent from trusted ledger and not covered by an already-landed reachability
  authorization" (174 → 175 dispositioned).
- `check-ratchet-provenance.py` (the exact-debt-ledger step "Require enforced
  ratchet provenance policy") → rc=1, with exactly those two sub-gates red;
  its other nine sub-ratchets (adr-status-language, citation-status,
  promotion-surface, shell-execution, contract-markers, enumerations,
  lifecycle, vulture, reachability's sibling set) all report OK.
- `check-vulture-baseline.py` (CI exact args) → rc=0, 1342 → 1342 via the
  whitelist references; `check-shipped-surface-truth.py` → rc=0;
  `check-reachability.py` → rc=0; `check-reachability-dispositions.py` →
  rc=0; `check-convergence-matrix.py` → rc=0.

**Why this red cannot be repaired inside this leaf.** Both provenance
wrappers compare the *measured* candidate state against the trusted state at
the merge base and against grants read from `quality/ratchet-authorizations.json`
**at the merge base** (`scripts/ratchet_provenance.py::load_authorizations`):
a grant added on this branch cannot authorize the module this same branch
adds — that is the documented two-merge rule, and it holds even locally. The
unblocking change is therefore outside this worktree's authority, and the two
in-leaf alternatives are forbidden by the issue's staging constraint: wiring
a production caller (fake caller), or editing the gate's source-universe
classifications (gate weakening). Removing the candidate baseline/disposition
rows does not help either: the wrappers measure the import graph, not the
candidate ledger, so the failures above persist verbatim, while two more
candidate-side gates (`check-reachability.py`,
`check-reachability-dispositions.py`) would turn red and the CONNECT record
naming the future consumer would be lost. The rows therefore stay, staged
pending the same authorization as the code.

**What turns the exact-debt-ledger job green (handoff to the #1845 parent
integration):** either

1. land a `reachability` grant for `maistro.runs.admission_identity` in
   `quality/ratchet-authorizations.json` on `develop` as its own reviewable
   merge (owner/issue/reason, the flow used for the #458 interop surfaces,
   whose grant landed as #1004), then re-evaluate this branch; or
2. land the parent #1845 consumer, making the module reachable — at which
   point `check-reachability.py` forces pruning the baseline row and the
   disposition, and the whitelist references are deleted in the same change.

Until one of those lands, this leaf's merge-queue evaluation is expected to
stay red on exactly the two reachability provenance sub-gates, which is the
issue's own "not independently mergeable or releasable while unwired"
posture, not a defect of the leaf code.

## Prerequisite revalidation update (#1841)

The earlier leaf recorded revalidation at #1841 head
5daf1ee3442b5361c674d1968bd3711a7a077dc7. #1841 has since **merged**; its
final head is c66c5c8f60135b0f8b6ed3d43fa116a15399237d. Re-diffed:
`runs/store.py`, `runs/store_boundary.py`, and `runs/model.py` are unchanged
between 5daf1ee3 and c66c5c8f, and `runs/store.py` / `runs/store_boundary.py`
are byte-identical to origin/develop 91996e19 (model.py differs there only by
the unrelated cancellation_cause work; `actor_principal_id` untouched). The
accepted signatures at this branch's HEAD remain exactly:
`require_admitted_actor(actor_principal_id: str | None) -> str`,
`RunStore.get_run(self, run_id: str, *, principal_id: str | None = None) ->
Run | None`, `create_run`/`claim_run_by_effect` retaining
`actor_principal_id: str | None = None` with the admitted-actor guard, and
`Run.actor_principal_id: str | None` — no type conflict with this contract.

## Spec conformance spot-check against the full issue text

The issue snapshot embedded in the repair job was truncated mid-enum. The
full issue text (fetched read-only) specifies `REPLACE_EXPIRED =
"replace_expired"` and `LEGACY_UNRESOLVED = "legacy_unresolved"`; the module
implements all six members with those values, and its `__all__` is exactly
the required 21 names. All **12** test functions named in the issue's
"Prospective tests and acceptance" section exist and pass, alongside one
extra issue-conformant rejection case the issue does not name
(`test_canonical_json_rejects_non_string_constructor_input`); 73 tests
total, parametrized. (An earlier revision of this note said "all 13 test
functions named in the issue" — that overcounted; the issue names 12.)

## Third repair round (convergence-matrix drift after the develop merge)

At c43cac60 — the head that merged develop 91996e19 — the merge-queue
evaluation failed the `test` job and the Quality gate (Pillars 1–4, 7, 8) on
`scripts/check-convergence-matrix.py`: the "Run / NodeRun / Attempt
lifecycle" row's Unreachable cell said `none` while the checker measured
`few` (1 of 32 modules, 3.1%). The one baselined-unreachable module is
`maistro.runs.admission_identity`, baselined in the first repair round; the
census counts the baselined set
(`check-convergence-matrix.py::unreachable_modules`), so the cell went stale
the moment that row landed, and only the develop merge exposed it on the
queue. Repaired in-leaf by updating the cell to `few` — the truthful share
for an inactive contract leaf — with no code change. The same round
corrected this note's two drifted claims: the test-function count above
(12, not 13), and the second round's `check-convergence-matrix.py → rc=0`,
which was true at eeb4c600 but did not survive the develop merge into
c43cac60; it is rc=0 again at this round's head.

Executed at this round's head with `RATCHET_BASE_REV` =
`git merge-base HEAD origin/develop` = 91996e19223db61bab49ce2e8a8d5b8f6eb2728e:

- `check-convergence-matrix.py` → rc=0 (52 subsystems classify all 1257
  production modules; 175 unreachable attributed);
  `pytest tests/test_check_convergence_matrix.py -q` → 60 passed;
  `check-m1-convergence-freeze.py --base 91996e19` → rc=0.
- `check-reachability.py` → rc=0 (1257 production modules, 175 unreachable,
  baselined); `check-reachability-dispositions.py` → rc=0 (50 groups: 151
  CONNECT, 22 LIBRARY, 2 RETIRE).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (CI exact args) → rc=0, 1342 reviewed identities →
  1342 findings, `unclassified: 0`, `never_allowlist: 0` — **no unbanked
  identities**, so there is nothing to amend in `quality/vulture-baseline.json`
  this round and no identity was eliminated by a fix.
- `check-shipped-surface-truth.py` → rc=0.
- `check-reachability-provenance.py` → rc=1,
  `check-reachability-dispositions-provenance.py` → rc=1, and
  `check-ratchet-provenance.py` → rc=1 failing on exactly those two
  sub-gates ("NEW unreachable module / disposition absent from trusted base
  and not previously authorized") — unchanged and unfixable in this leaf by
  the two-merge rule; the unblock paths remain the grant-first develop merge
  or the #1845 consumer, as recorded in the previous section.
- Focused suite `packages/maistro-core/tests/runs/test_root_admission_identity.py`
  → 73 passed; ruff check and `ruff format --check` clean; suite inventory
  unchanged (no test files moved this round).

## Fourth repair round (merge-queue re-evaluation at the advanced develop base, 2026-10-04)

At HEAD ac0b821acc4f with `origin/develop` advanced to
928993dda1c958ada2e6f8e54b5e5c04bf86bf77 (the merge-queue base; `git
merge-base HEAD origin/develop` is still 91996e19):

- Ledger integrity across the develop merges: `git diff --numstat
  origin/develop -- quality/` shows this branch adds one reachability
  baseline row and one disposition group relative to develop and removes
  nothing — the merges did not silently drop `quality/*.json` rows.
- Develop's new commit (#1934) touches `maistro/graph/durable_runs/**` and
  its tests only, with no overlap with this leaf's seven files, so no
  develop merge was performed: there is no sync conflict, and the merge
  queue evaluates the merged result itself.
- `check-ratchet-provenance.py` executed with **both**
  `RATCHET_BASE_REV=928993dd…` and `RATCHET_BASE_REV=91996e19…`: identical
  outcome — rc=1 failing on exactly the two reachability provenance
  sub-gates; the other nine sub-ratchets (including vulture,
  promotion-surface, contract-markers) all report OK. The red is
  base-independent and structural for an inactive contract module.
- The lane's CI-repair step, `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: rc=0, 1342 reviewed
  identities → 1342 findings, `unclassified: 0`, `never_allowlist: 0` —
  **zero unbanked identities**, so `quality/vulture-baseline.json` required
  no amendment and no fix eliminated an identity this round.
- First-hand read-only fetch of issue #1851 confirms the 12 named test
  functions from the issue's acceptance section (all present; the extra
  `test_canonical_json_rejects_non_string_constructor_input` remains the
  only unnamed case).
- Re-executed green: `check-reachability.py`,
  `check-reachability-dispositions.py`, `check-shipped-surface-truth.py`,
  `check-convergence-matrix.py` (+ its 60-test suite),
  `check-m1-convergence-freeze.py --base 91996e19`, the focused suite (73
  passed), `tests/test_check_reachability.py` (24 passed), ruff
  check/format, and mypy on the module (no issues).
- Residual, unchanged: the two trusted-base provenance sub-gates stay red
  until the grant-first develop merge or the #1845 consumer lands (handoff
  above); the `_vulture_whitelist.py` references and the candidate
  baseline/disposition rows are deleted in that same parent-integration
  change.
