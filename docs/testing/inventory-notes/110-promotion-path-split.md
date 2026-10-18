---
inventory-delta:
  packages/maistro-rsi/tests: +22
  packages/hive-conductor/backend/tests: +8
---
# Issue #110 (M4-A3): mechanical non-judgment promotion path vs judgment review

Splits the checkpoint-time promotion pass into two routes and gives the review
inbox a full deterministic decision set.

## Behavioral groups

1. **Classification (`classify_promotion`, fail-closed)** — a promotion takes
   the mechanical non-judgment path only when its touched surface is
   quarantine-clean (the SAME `matches_sensitive_pattern` matcher the
   quarantine gate escalates on), no test-inventory governance override was
   exercised, and the evidence is decisive (composite ≥
   `MECHANICAL_COMPOSITE_FLOOR`, RLPHD's own cold-start theta). Sensitive
   surface, override, weak evidence, or an undeterminable touch surface all
   take the judgment path. Unit cases cover each rule plus `deny`→`reject`
   normalization and unknown-verb rejection.

2. **Loop split (`LocalRsiLoop._review_promotions`)** — real-git integration
   cases: a decisive non-sensitive promotion is kept with NO RLPHD state file
   even written (no judge — not even the predictive one) and a promotion
   record linking candidate/evaluation/decision/version; a sensitive-surface
   promotion escalates even with decisive evidence (revert + flagged with
   `sensitive_paths` recorded); weak evidence escalates; a governance
   override escalates via the trace-note evidence; a superseded mechanical
   promotion still needs no judge.

3. **Deterministic inbox verbs (`resolve_review`)** — `approve` trains RLPHD,
   settles the item, exports the patch; `reject` (alias `deny`) trains,
   settles, never exports; `revise` keeps the item pending with a bumped
   revision, trains nothing, exports nothing, and is retry-idempotent;
   `resume` exports the patch and keeps the review open, trains nothing, and
   is idempotent (no duplicate export; approve-after-resume exports once).
   Every decision persists a sidecar embedding the policy/evidence snapshot
   (features, predicted p, theta, classification), and reviewer decisions
   link into the sha's promotion record (`decision.outcome`,
   `version.export_patch`).

4. **API inbox (hive-conductor `POST /v1/rsi/runs/{id}/reviews/{sha}`)** —
   the route delegates to the same core: revise/resume keep the item listed
   unresolved and write no RLPHD state; retries are idempotent; approve after
   resume trains exactly once and exports once; unknown verbs are refused by
   validation (422); unreadable metadata is refused 409 before anything is
   recorded. The pre-existing idempotency contract (first decision wins) is
   preserved; its seeded fixture now carries the full metadata shape real
   inbox files always have.

## Deliberately unchanged (reconciliation notes)

- The LLM regression judge stays part of the protected correctness gates
  (ADR-070126-6386, fail-closed #307): it runs only after every deterministic
  gate passes and is operator-disableable; the judgment REVIEW (#110) is the
  checkpoint-time RLPHD/human pass, which mechanical promotions now skip.
- `--no-promotion-review` remains an explicit operator opt-out of the whole
  checkpoint pass (pre-existing, pinned by tests); when the pass runs, the
  classification is fail-closed and sensitive promotions escalate
  unconditionally.
- The conductor route's PR-on-approve behavior and `repo_path` refusal are
  untouched.

## Mutation spot-checks

Disabling the mechanical short-circuit (forcing every promotion through
RLPHD prediction) fails `test_mechanical_promotion_needs_no_judge` (RLPHD
state file appears) and `test_mechanical_superseded_promotion_still_needs_no_judge`;
making `classify_promotion` fail-open on undeterminable touch surfaces fails
`test_undeterminable_touch_surface_fails_closed_to_judgment`; dropping the
`already-decided` guard regression-fails the #262 idempotency case.

## Repair round (CI gate failures at d3c3d41cc)

- **exact-debt-ledger / vulture**: #110's CLI verb refactor removed the local
  `approve = review_sub.add_parser(...)` binding, whose name-level match was
  the only thing keeping vulture from flagging `LearningApprovalGate.approve`
  (an uncalled-in-src admin verb of a Stronghold-ported public gate, sibling
  of the banked `reject`/`get_pending`/`get_all`). Named in
  `packages/maistro-core/src/_vulture_whitelist.py` with rationale — the
  repo's mechanism for retained maistro-core public API — rather than banked
  as new debt, which the ratchet correctly refuses to let this branch
  self-authorize (grants must already exist at the merge base). The
  `trace_notes.py::inventory` ledger row was pruned: #110's governance-override
  escalation reads `note.inventory` (`local_loop.py`), genuinely fixing that debt.
- **diff coverage**: the changed CLI dispatch lines (`review
  approve|reject|revise|resume`) and the conductor route's error mapping
  (`_locate_review` miss → 404; `_review_http_error` 404/400/409; the
  apply-verb `except`) had no tests. Added: three CLI dispatch tests (shared
  core, core-FileNotFoundError → exit 2, unknown sha → exit 2) and three
  route tests (unknown sha → 404, the error-class → status mapping, and a
  real TypeError path — garbage feature values pass the key-subset check and
  must be refused 409 with nothing settled). Also pinned the artifact-keying
  acceptance criterion: a decision for one candidate sha never settles a
  different candidate's review
  (`test_a_decision_never_leaks_across_candidate_shas`).
- **radon CC ratchet**: `resolve_review` crossed into C(13) with the revise/
  resume verbs. Grants must already exist at the merge base, so the branch
  cannot authorize the increase — the verb branches are extracted into
  `_resolve_revise`/`_resolve_resume` (behavior pinned by the existing tests),
  bringing `resolve_review` back under C; the `_review` improvement the same
  CLI work produced (13 → 12) is banked in `quality/radon-baseline.json`, as
  that ledger's own rationale directs for complexity reductions.
