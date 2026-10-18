---
inventory-delta:
  packages/maistro-core/tests: +32
---
# 116-canonical-promotion-contract

Thirty-two tests in `test_promotion_contract.py`: the twenty-six this note
originally recorded, plus the six reversal-decision tests added by the CI
repair round below. Nothing removed or reparametrised; the 151 pre-existing
tests in `tests/graph/test_template_store.py`,
`tests/graph/test_node_template_store.py` and `tests/governance/` still pass
unchanged after the template family's approval type was reconciled onto the
canonical one.

## What the tests are for

`maistro.governance.promotion` is a value layer with no I/O, so its tests
are the enforcement: the module states the promotion contract (M4-A9,
#116), and these tests are what makes a fence firing an audit answer rather
than an opinion. One test class per acceptance criterion in
SPEC-100126-a9c4, in the spec's numbering, plus a fence-edges class and the
one-approval-type class.

## The two defects the tests caught before any review could

* **Exact-membership matching in the own-constitution fence.** The first cut
  checked `ref in protected_refs` — set membership, so `quality/x.json`
  sailed past a `quality/` entry, which is precisely the
  one-omission-at-a-time failure #303 fixed when it derived the containment
  surface instead of enumerating paths. The fence now does fragment
  matching: a protected entry ending in `/` covers everything under it, any
  other entry is an exact ref. `test_candidate_cannot_edit_its_own_judge_or_constitution`
  pins the fragment case directly.
* **A falsy-dict test helper**, not a module defect: `evaluators or {default}`
  silently replaced an explicitly empty evaluator map with a populated one,
  so the "empty evaluator versions are refused" assertion was testing the
  default. `evaluators if evaluators is not None else ...`, and the test
  now genuinely exercises the refusal.

## Per-criterion mapping

* **AC-1 (candidacy is inert)** — `evaluate` leaves the ledger empty and
  the candidate value untouched (asserted by dataclass equality);
  `promote` is the only path that appends.
* **AC-2 (explicit new version, immutable history)** — mint-then-rollback-
  then-repromote takes v3, never a reassigned v2; stale base refused by
  number and by hash; duplicate version record refused at the ledger.
* **AC-3 (complete record)** — every governed field read back off a
  promoted prompt record (scope, subject, versions, both hashes, evidence,
  evaluator versions, approver/authority/policy, rollback target and
  mechanism), plus a frozen-ness check, because "records are never edited"
  should be enforced by the type, not the reviewer.
* **AC-4 (own evaluator/constitution)** — protected-ref edits refused even
  under a chief-security-officer approval; unrelated refs still promote
  (the fence must not become a general blocker); construction without a
  classification for a scope refused (fail closed); the template scope's
  own constituents enforced through the same mapping.
* **AC-5 (no self-approval)** — `rsi` approving `rsi` refused; approver as
  effective authority when no authority is named; external authority passes.
* **AC-6 (traceability)** — trace returns record + effects + reversals;
  unknown record, duplicate measurement id, double reversal, and a
  measurement citing no Runs all refused; reversal appends without
  rewriting the record (content hash asserted intact after reversal).
* **AC-7 (one approval type)** — `maistro.graph.templates.PromotionApproval`
  *is* the canonical class, two-kwarg construction still validates blank
  fields, and the defaulted policy/authority behave.

## Not covered here

* Adoption per family (template/pg stores writing `PromotionRecord`s,
  genome rewiring) is declared follow-up in the spec's family-mapping
  table — the tests cover the contract, not the migrations.
* The pg-backed template stores' promotion audit tests are skipped in this
  environment (no Postgres up); the sqlite/in-memory equivalents run and
  the reconciliation change is import-level only for them.

## CI-repair addendum (second round): reversal decisions made binding

The exact-debt-ledger gate flagged 13 unbanked identities in
`governance/promotion.py`. The prior round banked them; the gate's trusted
leg reads authorizations from the merge base, where no vulture grants exist,
so banking alone cannot turn the gate green. This round eliminated ten of
the thirteen by making the module do what its docs and SPEC-100126-a9c4 R4
already claimed, each with a test:

* `REVERSAL_MECHANISM_BY_SCOPE` — the rollback `mechanism` is now the
  scope's sanctioned reversal path (prompt label move, template
  `promote_audited`, skill trust-tier step; the three store-less families
  record the contract's generic reversal) instead of one template-flavored
  default for every family. Clears the three `PromotionScope` members and
  `mechanism`.
* `mark_reversed` honors the record's rollback metadata: an irreversible
  record refuses (`IrreversibleReversal`, clearing `reversible` and citing
  `mechanism`), a superseded version refuses direct reversal until the
  newer unreversed promotion is reversed (`SupersededReversal`, clearing
  `rollback_target_version`), and the double-reversal refusal now says
  *when* the first reversal happened (clearing `reversed_at`).
* `evaluate` cross-checks the prior a promotion cites against recorded
  history: a store whose claimed current content contradicts what this
  ledger minted for that version is refused (`StaleCandidate`), closing a
  gap where two agreeing lies from the calling store passed the
  base-vs-current fence. Clears `prior_version`/`prior_content_hash`.
* The module now declares `__all__` (the templates.py precedent for public
  core surfaces), clearing `PromotionContract`.

The remaining three identities (`PromotionContract.promote`,
`PromotionLedger.attach_effect`, `PromotionLedger.mark_reversed`) are the
gate methods whose first production consumers are the spec's declared
follow-up store adoptions; manufacturing in-repo callers for them would be
the success-shaped no-op the repo hunts, so they stay banked in
`quality/vulture-baseline.json` (candidate leg exact against the scan,
11 stale rows pruned) pending vulture grants landing on develop — the
two-merge doctrine's own resolution, as in the #82 round-5 repair.

## Round 4 (develop sync): counts unchanged

The branch was synced to origin/develop (1e4933e2a1). No test was added,
removed or reparametrised: `test_promotion_contract.py` +
`test_template_store.py` + `test_node_template_store.py` re-ran on the merged
tree at 145 passed / 58 DB-skipped, identical to the round-2 record. The
`inventory-delta` above is unchanged.
