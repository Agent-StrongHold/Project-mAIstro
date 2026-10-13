# #1572 repair round 63 — 2026-10-12 (job 91ac255c9443408d8ee4eb84d81ace68)

Dispatch head `bc2e7062696f1a2b4364b0b36073ed1cc3304714` (round-62 docs commit; code-identical
to `db091060d`, so the rounds-37–62 code battery carries). Base
`3c761d14db944a727fa0744444bc67cfe36d49f7` (= merge-base). Every claim below was re-derived
first-hand this round; no prior verification claim was trusted.

## Sole blocker, re-proven at this exact head

`uv run python scripts/check-execution-lifecycles.py` (exact CI argv, quality.yml:1541) exits 1:

```
  baseline: base 3c761d14db94
  candidate: bc2e7062696f
  19 classified lifecycles  ->  20 discovered lifecycles
  - maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the
    trusted base and has no already-landed authorization
```

`tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
fails on the same sole finding (assert at tests/test_check_execution_lifecycles.py:374,
`main() != 0`): 1 failed / 28 passed — this is the merge-queue `test: failure`, and the
coverage `combine` step inherits the dead producer.

## No in-branch repair exists (re-derived from source, not from prior rounds)

- `scripts/ratchet_provenance.py` `load_authorizations` (line ~478) reads grants from the
  **base revision**; its docstring states the consequence verbatim: "a new grant does not
  take effect in the change that introduces it. Authorizing a floor-raise is now two
  merges". `resolve_baseline` precedence is explicit arg > `RATCHET_BASE_REV` > GitHub
  event base > `origin/develop`, with `_refuse_self_reference` blocking base==HEAD.
- `scripts/check-execution-lifecycles.py` `_unauthorized_additions` (:705) passes only with
  a base-revision grant OR base source visibility. `_discover_at_revision` (:674) does
  `git show {base}:packages/maistro-core/src/maistro/goals/model.py`, which cannot succeed —
  the module does not exist anywhere at the base (`maistro/goals` is new in this branch).
- origin/develop re-fetched this round: unchanged at `3c761d14db94` == merge-base. Its
  `quality/ratchet-authorizations.json` `execution-lifecycles` section contains exactly two
  grants (`services.rsi::RunStatus`,
  `maistro.graph.nodes.agent_delegate_remote::DelegationStatus`) and **zero** GoalStatus.
- The branch's own grant commit `2f5dd4696` is a structural no-op (proven empirically in
  round 59 and by the source above). Open PR #1938's head `2f5dd46969fc` **is** that grant
  commit — #1938 is this lane's implementation PR, not a standalone landed grant.
- GoalStatus is the issue-mandated vocabulary (`ACTIVE/SATISFIED/CANCELLED/FAILED/SUPERSEDED`,
  model.py:52-60; "e.g. active, satisfied, cancelled, failed, superseded … Terminal states are
  final"). Three of its members (ACTIVE, CANCELLED, FAILED) are in the detector's
  `_WORK_STATES`, exactly at `_MIN_WORK_STATES = 3`: removing/renaming any of them to dodge
  detection violates issue scope and/or weakens the gate — both prohibited.
- The lane brief's CI-repair exception targets the **vulture** ledger and has no target here:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (exact CI argv, quality.yml:1079) exits 0 with 1323 = 1323 —
  nothing unbanked, nothing to amend. The failing gate is the execution-lifecycles ratchet,
  which no lane brief authorizes amending, and an in-branch amendment of
  `quality/ratchet-authorizations.json` is a proven no-op regardless.

## Required external action (unchanged from round 62)

A maintainer lands an `execution-lifecycles` grant for `maistro.goals.model::GoalStatus`
(owner/issue/reason) **on develop first** — the same treatment grant PR #1833 received for
this branch's vulture identities (MEMBER precedent, 2026-10-03). After it lands, this branch
merges develop and the gate + shipped-ledger test pass with zero further edits.

Snapshot scan (365 issue comments, captured 2026-10-12T09:28Z): newest entries are
maistro-progress markers only; no maintainer authorization for the GoalStatus grant exists.

## Focused validation executed this round (first-hand)

- Driver checks (job logs, this round): ruff check / format --check green; 9-file pytest set
  161 passed / 28 skipped; suite inventory ok (16334 identities).
- `uv run pytest packages/maistro-core/tests/goals -q`: **48 passed / 22 skipped** (PG legs
  skip without DSN; live-PG legs were proven in rounds 58–62).
- `uv run pytest tests/test_check_execution_lifecycles.py -q`: 1 failed / 28 passed, sole
  cause = the external grant (above).
- `uv run pytest tests/migrations/test_migration_chain.py -q`: 18 skipped (needs Postgres;
  durable-migration legs proven live in rounds 58–62).
- Acceptance criteria (issue body re-read this round): all seven are covered by the shipped
  tests — 3-backend conformance (`test_goal_store_conformance.py`), append-only CAS /
  stale refusal, subgoal lineage, immutable Run binding (`test_run_goal_binding.py`),
  workspace isolation with foreign==missing, shipped Container wiring
  (`test_goal_wiring.py`), and the convergence freeze gate (exit 0 at CI argv, rounds 60–62).
  The closure boundary's "authorization" item is the external grant above — the only
  unproven criterion, and it is not satisfiable in-branch by design.

## Local-only noise (not a branch defect, untouched)

`tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
fails only via untracked gitignored scratch `quality/ac-state.json` (.gitignore:81) found by
the unconditional rglob in scripts/check-branch-independence.py:206. CI passed this test;
left untouched.

## Verdict

BLOCKED on the external maintainer grant. No code, test, or ledger changes this round;
no inventory delta (no tests added or removed).
