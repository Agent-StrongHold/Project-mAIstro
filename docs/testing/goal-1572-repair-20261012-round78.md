# #1572 round-78 repair verification (2026-10-12)

Dispatch head `77388d89e26987eae5bd9856bc242c58830a03a0`; base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Every item below was re-derived or
re-executed first-hand this round; none is carried on trust from round 77.

## Tree identity to round-77's validated evidence

`git diff f4efdee21bfd HEAD` is exactly one docs-only file
(`docs/testing/goal-1572-repair-20261012-round77.md`, +135/-0). The code, test,
ledger, and CI trees are byte-identical to the dispatch head where round 77
executed the full acceptance battery (goals suite 70p/0f/0s with
MAISTRO_REQUIRE_PG_LEGS=1 on fresh pg18 AND pg17, migration battery 168p,
convergence freeze exit 0 at CI argv, mypy 899 files clean). That evidence
applies to this head unchanged.

## The one blocker (unchanged, external)

- `uv run python scripts/check-execution-lifecycles.py` at the exact CI argv
  (`.github/workflows/quality.yml:1541`) re-run this round: **exit 1**, single
  finding `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent
  from the trusted base and has no already-landed authorization` (19 -> 20).
- `tests/test_check_execution_lifecycles.py` re-run: **1 failed / 28 passed**
  (`test_the_shipped_ledger_matches_the_shipped_code`), stdout gate-identical —
  this is the merge-queue `test: failure`, 1:1 (coverage `combine` inherits the
  dead producer).
- `origin/develop` re-fetched: tip **unchanged** `3c761d14db94` == merge-base,
  branch 179 commits ahead; `git grep GoalStatus origin/develop -- quality/` =
  0 matches; `git ls-remote origin refs/pull/1938/head` = `2f5dd46969fc` — the
  grant-only PR **still exists unmerged** and no grant has landed.
- The branch's `quality/ratchet-authorizations.json` diff vs develop is
  **0 lines** — an in-branch grant re-add is a proven no-op and outside this
  round's permitted amendment scope. Mechanics re-read from source this round:
  `load_authorizations` (`scripts/ratchet_provenance.py:478-495`) reads grants
  **from the base revision** — docstring verbatim: "a new grant does not take
  effect in the change that introduces it. Authorizing a floor-raise is now two
  merges"; the gate calls it with `base=trusted_ref.base_sha`
  (`scripts/check-execution-lifecycles.py:773`); `_unauthorized_additions`
  (`:705-707`) blocks the candidate's own DOMAIN classification
  (`quality/execution-lifecycles.json:89-92`, present with full rationale) from
  self-authorizing — so the ledger entry is not the defect.
- No in-branch repair exists: renaming/removing `GoalStatus` violates the
  issue-mandated lifecycle (ACTIVE/SATISFIED/CANCELLED/FAILED/SUPERSEDED) or
  dodges the work-state detector (prohibited weakening); `RATCHET_BASE_REV=HEAD`
  self-reference is refused by `_refuse_self_reference`
  (`ratchet_provenance.py:258-270`).
- Handoff (proved by execution in rounds 74 and 77 on this code-identical tree):
  with PR #1938's single grant landed on the base, the same gate exits **0**
  (`OK: 20 work-state vocabularies, all classified`) with **zero branch
  edits**; the control run without the grant reproduces this round's exit 1.

## Lane-brief vulture CI-repair exception: no target

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (exact argv,
`quality.yml:1076-1081`) re-run this round: **exit 0**, 1323 reviewed
identities -> 1323 findings, `unclassified: 0`, `never_allowlist: 0`. Nothing
is unbanked; there is no vulture identity to fix or amend, so the one permitted
ledger amendment has no object.

## Driver checks at this head (job eb36e7ee6a13468685772da265242e10)

check-0 sync ok; check-1 `ruff check .` "All checks passed!"; check-2 `ruff
format --check .` 3288 files formatted; check-3 targeted pytest **161 passed /
28 skipped**; check-4 suite inventory **ok** (16334 identities match).

## Verdict

**BLOCKED** on the external maintainer `execution-lifecycles` grant for
`maistro.goals.model::GoalStatus` — merge grant-only PR #1938 first, after
which this branch's failing gate and shipped-ledger test pass with zero branch
edits (execution-proven). Docs-only round; no code, test, or ledger changes; no
inventory delta.
