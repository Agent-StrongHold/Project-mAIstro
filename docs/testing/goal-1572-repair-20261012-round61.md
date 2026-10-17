# #1572 repair lane — round 61 verification (2026-10-12)

Head `e79a48a7752cf27ebde56d34e0d706e6a7f07ba0` (branch `auto-1572`), base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Job
`a472a42b47a842d7b440697a86202e75`. Every claim below was re-executed
first-hand at this exact head this round; no prior verification claim was
assumed true. **No code, test, or ledger changes were made this round; no
inventory delta.**

## Code state

`git diff --stat db091060d..HEAD` = three round-note docs files only
(`round58/59/60.md`); zero non-docs, non-quality diffs. HEAD is therefore
code-identical to `db091060d`, whose full battery (including live-PG legs) was
executed in rounds 58–60. The grants file is byte-identical to `origin/develop`
(`git diff origin/develop..HEAD -- quality/ratchet-authorizations.json` empty):
the in-branch GoalStatus grant added at `2f5dd4696` is fully removed.

## Driver checks at this head (job logs `check-0..4.log`)

- `uv sync --locked --extra dev` — exit 0 (256 packages).
- `uv run ruff check .` — exit 0. `uv run ruff format --check .` — exit 0 (3288 files).
- 9-file goals pytest set — 161 passed, 28 skipped.
- `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` — ok,
  16334 collected identities, 0 duplicates.

## Sole CI blocker, re-proven first-hand at this head

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  `.github/workflows/quality.yml:1541`) — **exit 1**, sole finding:
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from
  the trusted base and has no already-landed authorization` (19 → 20).
- `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`
  (`tests/test_check_execution_lifecycles.py:368-374`) — **1 failed**, body is
  literally `assert gate.main() == 0`; this IS the merge-queue "test: failure"
  and the coverage-combine inheritance. Same sole cause, no second failure.
- `uv run python scripts/check-m1-convergence-freeze.py --base 3c761d14db94…`
  (CI argv, `formal-conformance.yml:77`) — **exit 0**: no unapproved new
  architecture island; the canonical Goal lifecycle is not a second executor.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact CI argv,
  `quality.yml:1079`) — **exit 0, 1323 reviewed → 1323 findings, unclassified
  0**. The vulture CI-repair lane is empty: there is nothing genuinely dead to
  fix and no identity to amend into `quality/vulture-baseline.json`. The lane
  brief's amendment exception has no target at this head.
- `git fetch origin`: `origin/develop` still `3c761d14db94` ==
  `git merge-base HEAD origin/develop` — no sync conflict, nothing to merge.
- Base-side facts: `git show origin/develop:quality/ratchet-authorizations.json
  | grep -c GoalStatus` = 0; base ledger has 19 rows, 0 GoalStatus; branch
  ledger delta is exactly one added row (`quality/execution-lifecycles.json:88`,
  classification DOMAIN with rationale). All `quality/` numstat vs develop is
  additive (17/0, 39/0, 4/0).

## Why no in-branch repair exists (gate mechanics, re-read in source)

1. **Grants are read from the base revision, not the branch.**
   `check-execution-lifecycles.py:main` calls
   `prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`;
   `scripts/ratchet_provenance.py:478-495` resolves the grants file with
   `git show {base_commit}:quality/ratchet-authorizations.json`. The docstring
   states the consequence verbatim: "a new grant does not take effect in the
   change that introduces it … two merges". Empirical proof: round-59 head
   `2f5dd4696` carried the in-branch grant and the gate still failed. Re-adding
   it is a proven no-op.
2. **The base-visibility path cannot fire.** `_discover_at_revision`
   (`check-execution-lifecycles.py:674`) runs the detector over base versions
   of candidate modules; `maistro/goals/model.py` does not exist at
   `3c761d14db94`, so `GoalStatus` can never be "visible at base" via any
   candidate-side edit.
3. **Issue scope mandates the vocabulary.** Issue #1572 Scope: "*Goal
   lifecycle:* e.g. active, satisfied, cancelled, failed, superseded.
   Transitions are compare-and-set on revision and state. Terminal states are
   final." Removing the enum, or reusing an execution-state vocabulary
   (`maistro.runs.model::RunStatus` et al. — all 19 base identities are
   execution-state), would violate the issue and conflate desired state with
   the canonical Run/NodeRun/Attempt execution spine the gate protects.
   Obfuscating the enum to dodge the detector would be weakening the gate.
   Any goal-lifecycle vocabulary anywhere in the tree is, by construction, a
   new identity requiring a **prior** base grant.
4. `resolve_baseline` (`ratchet_provenance.py:300-355`) fixes the trusted base
   at `origin/develop` (merge-base), with `_refuse_self_reference` blocking
   candidate-pinned baselines; `RATCHET_BASE_REV` is CI-controlled.

## Required external action (one maintainer merge, zero branch changes)

Land on `origin/develop` a grant in `quality/ratchet-authorizations.json`
under `"execution-lifecycles"` → `"maistro.goals.model::GoalStatus"`, with
`owner`, `issue` (#1572), and `reason` (canonical Goal desired-state lifecycle, DOMAIN-classified). After it
lands, this branch passes with **no further edits**: `added = {GoalStatus}` ⊆
`authorized` → `unauthorized = []`; `unbanked_authorized = []` because the
candidate ledger banks it; `audit()` is clean. This is the repo's documented
two-merge flow (`docs/quality-gates.md`; AGENTS.md "a floor raise takes two
merges"), and it is outside worker scope: workers never push or edit GitHub.

## Local-only non-issue (unchanged)

`tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
fails in this worktree only because untracked, gitignored scratch
`quality/ac-state.json` (`.gitignore:81`) is picked up by the unconditional
rglob in `scripts/check-branch-independence.py:206`. CI passed it (its one
failure is the ledger test above). The scratch file is salvage/foreign state —
left untouched per campaign prohibitions.

## Verdict

NEEDS-DEEP-REVIEW, now with complete first-hand proof: every acceptance
criterion has executed evidence (rounds 37–60 batteries, code-identical tree;
driver checks green this round), and the single failing gate is blocked on the
documented two-merge grant that only a maintainer-side merge to develop can
provide. Not NEEDS-REPAIR: no legitimate in-branch change exists. Not
MERGE-READY: a named CI gate provably exits 1 at this head.
