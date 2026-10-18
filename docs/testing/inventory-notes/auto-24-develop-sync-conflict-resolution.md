---
---

# auto-24 develop-sync conflict resolution and gate repair (job 58ea0a2b)

The previous block left a mid-flight merge of develop into auto-24 with one
unresolved conflict in
`packages/maistro-evolve/src/maistro_evolve/fitness.py`; every driver check
failed only because the conflict markers made the file unparseable. This
round resolved the conflict semantically, merged the newer develop tip, and
re-proved the named CI failure (exact-debt-ledger) plus the full acceptance
battery. No tests were added or removed — suite inventory unchanged.

## The conflict and the resolution

HEAD (#24 / SPEC-282) had the pre-#853 fitness structure plus the curriculum
guard: reserved-namespace (`self_generated/`) exclusion in
`_check_hard_gate` and `_weighted_eval_score`. The develop side (33bcd3ce)
refactored fitness onto the population-owned `EvaluationObjective`
(`objective.weight_for`, missing-evidence policy, evidence hash,
`capability_score`) without the curriculum guard. Resolution takes develop's
objective-based structure and re-expresses the #24 exclusion inside it:

- imports: both sides (hashlib/json/typing + `RESERVED_BENCHMARK_PREFIX` +
  objective/diversity);
- `_weighted_eval_score`: develop's `sorted` + `objective.weight_for` loop
  with the reserved-prefix `continue` retained — curriculum scores are
  excluded even from the default-weight fallback and the renormalisation
  denominator;
- `_check_hard_gate` empty-corpus branch named distinctly: no scores at all →
  `"no benchmarks evaluated"` (pinned by
  `test_fitness_ownership.py::test_do_nothing_candidate_scores_zero_...`),
  curriculum-only scores → `"no external benchmarks evaluated"` (pinned by
  `test_fitness.py::test_genome_scored_only_on_curriculum_cannot_breed`).

Merge commits: `28fbd1340` (stale tip 33bcd3ce, completing the preserved
mid-flight merge) then `2a3a4ecf5` (live origin/develop `83db0175d`,
auto-merged clean). HEAD after the round: merge of `83db0175d` into auto-24.

## Gates re-proven at the merged head (all executed this round)

- exact-debt-ledger: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0,
  `1359 reviewed identities -> 1359 findings` (develop's Wave-2 vulture
  banking merged consistently with the #24 amendments; no unbanked
  identities).
- Registry front-matter: `maistro_registry.cli lint . --strict` → 422 files
  clean, 0 errors, 0 warnings, 0 extra.
- Quality gate: `check-contract-markers.py` → OK, exit 0.
- Chain mandate (previously failing component):
  `check-ac-state.py --run-tests --mandate 83db0175d` → "every criterion this
  change declares is proven"; introduced absent links
  specs_implementing_nothing / adrs_without_implementing_spec /
  specs_declaring_no_criteria all 0 — now proven end-to-end (the prior lane
  could only prove inputs individually).
- ruff check `.` clean; `ruff format --check .` 2769 files formatted.
- Evolve suite: 804 passed + 6 skipped; the 3 docker-boundary failures
  (benchmarks/test_sandbox_exec.py, benchmarks/test_swebench.py) were
  environmental — stale `/var/run/docker.sock` with no daemon; re-run against
  the live rootless daemon (`DOCKER_HOST=unix:///run/user/1000/docker.sock`)
  → 46/46 passed. SPEC-282 target files
  (test_curriculum/test_fitness/test_harness): 73 passed.
- Suite inventory: `check-suite-inventory.py --suite
  packages/maistro-evolve/tests` → ok, 813 matches, no delta.
