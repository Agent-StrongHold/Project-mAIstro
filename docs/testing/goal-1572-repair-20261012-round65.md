# #1572 repair round 65 — 2026-10-12 (job ccd494042dae42218249a88913817c54)

Dispatch head `ae7aeecb04c4bf322fef336363e41ec7fa5146c5` — the round-64 commit itself, so
the round-64 acceptance battery (mypy, convergence freeze, pg18.6 + pg17.11 migrations
empty->063, goals suite with PG legs on both majors, installed-base legs) carries at this
byte-identical tree. Base `3c761d14db944a727fa0744444bc67cfe36d49f7` (== merge-base,
re-fetched fresh this round — **origin/develop has NOT moved; the GoalStatus
execution-lifecycles grant has still not landed**). The prior job (7e70d01a) died on a
provider timeout AFTER all five driver checks exited 0; this round re-proves the blocker
legs first-hand rather than trusting either prior round.

## Sole blocker, re-proven at this exact head

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv, quality.yml:1541)
  exits 1: `19 classified lifecycles -> 20 discovered lifecycles`, sole finding
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted
  base and has no already-landed authorization`.
- `uv run pytest tests/test_check_execution_lifecycles.py -q` → `1 failed, 28 passed`;
  sole failure `test_the_shipped_ledger_matches_the_shipped_code` asserting
  `main() == 0` on the same finding — this IS the merge-queue `test: failure`; the
  coverage `combine` step inherits the dead producer (no independent floor/coverage
  deficit).
- Lane-brief vulture CI-repair exception has NO target:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (exact CI argv, quality.yml:1079) exits 0,
  `1323 reviewed identities -> 1323 findings`, unclassified 0 — nothing to amend.
- Worktree clean; `quality/ratchet-authorizations.json` cmp-identical to origin/develop
  (rounds 60/826cd0879 repair held); `git diff --numstat origin/develop...HEAD`
  additive-only (new `maistro/goals/*`, runs touches, goals tests, quality ledger rows).
- Driver checks green from job logs: `uv run ruff check .` (all checks passed),
  `uv run ruff format --check .` (3288 files), 9-file pytest set `161 passed, 28
  skipped`, suite inventory ok (16334 unique identities).

## No in-branch repair exists — the driver's "resolve BLOCKED" instruction was
## executed and the block re-derived as external, from source

- `scripts/ratchet_provenance.py::load_authorizations` (:478) reads grants **from the
  base revision**; docstring verbatim: "a new grant does not take effect in the change
  that introduces it. Authorizing a floor-raise is now two merges -- the grant, then the
  regression it permits". `resolve_baseline` (:301) precedence explicit arg >
  `RATCHET_BASE_REV` > GitHub event base > `origin/develop`, with `_refuse_self_reference`
  (:258, :314) blocking base==HEAD self-authorization.
- `scripts/check-execution-lifecycles.py`: `main()` (:747) computes
  `authorized = load_authorizations(RATCHET, base=trusted_ref.base_sha)` and
  `visible_at_base = _discover_at_revision(base_sha, found)` (:674, a `git show` of
  `maistro/goals/model.py` at base — impossible, `git grep GoalStatus origin/develop
  -- quality/` exits 1 and the module is new in this branch);
  `_unauthorized_additions` (:705) = added − authorized − visible_at_base → the sole
  finding. Both exits require base-side content.
- origin/develop re-fetched this round: tip `3c761d14db94` == merge-base — nothing to
  sync, no conflict to resolve, and no GoalStatus grant anywhere in develop's
  `quality/`; its `execution-lifecycles` grants are exactly
  `services.rsi::RunStatus` + `maistro.graph.nodes.agent_delegate_remote::DelegationStatus`
  (the #1136 pre-existing-vocabulary precedents).
- The candidate ledger classifies GoalStatus as DOMAIN with a rationale — but
  `_unauthorized_additions` exists precisely so a candidate classification cannot
  authorize its own new identity. Removing/renaming the vocabulary violates the
  issue-mandated lifecycle (issue body: "Goal lifecycle: e.g. active, satisfied,
  cancelled, failed, superseded") or dodges the 3-member detector
  (`_MIN_WORK_STATES = 3`; ACTIVE/CANCELLED/FAILED are exactly state-like) — gate
  weakening, prohibited.

## Required external action (unchanged, now re-proven a 65th time)

A maintainer lands the execution-lifecycles grant for `maistro.goals.model::GoalStatus`
on develop first (owner/issue/reason record in `quality/ratchet-authorizations.json`;
PR #1833 is the MEMBER precedent for vulture identities), then this branch merges
develop — after which the gate and the shipped-ledger test pass with zero branch edits.

## Verdict

BLOCKED on the external maintainer grant. Everything in branch scope is green and
re-proven; the single red leg is un-satisfiable in-branch by the ratchet's own
two-merge design. No code, test, or ledger changes this round; no inventory delta.
