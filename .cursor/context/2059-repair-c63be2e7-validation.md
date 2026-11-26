# #2059 round-15 repair validation at c63be2e7808 (job 499f49242ccf4d6fb4639d011a29b5f0)

Verified: 2026-11-25, worktree /home/dev/Git/wt/cr-2059, HEAD `c63be2e78088a067d41d44bc7a17572595a6cad6`
(== assigned dispatch head, tree clean), base `c9636e99f1d77efe24fdc6f4c07a3bfc3bea3ae2`.

Driver check logs: none present for this job (`checks: []` in manifest) → full battery
re-executed manually per the prompt's "CI response truncated; manual inspection required".

## Dispatch blocks resolved

1. **"develop sync conflict preserved in worktree" — DISPROVEN (stale), no action.**
   `git fetch` → `origin/develop == c9636e99f1d7 == assigned base`;
   `merge-base --is-ancestor <base> HEAD` exit 0; 54 ahead / 0 behind;
   no `MERGE_HEAD`; `git status --porcelain` empty at the exact head.
2. **"CI GATE REPAIR (vulture exact-debt-ledger)" — nothing to repair, no-op.**
   CI-exact scan `RATCHET_BASE_REV=origin/develop uv run python scripts/check-vulture-baseline.py
   packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**:
   1220 reviewed identities = 1220 findings, unclassified 0, never_allowlist 0,
   vulture 2.16, baseline base c9636e99f1d7 / candidate c63be2e78088. Zero unbanked
   identities → no ledger amendment. `git diff origin/develop HEAD -- quality/vulture-baseline.json
   quality/ratchet-authorizations.json` empty; sole quality/ delta remains the
   +17 `quality/ac-state-notes/fix-vulture-single-owner-1357.json`.
3. **"CI GATE FAILURES … response truncated" — live read-only inspection: 0 failures.**
   Check-runs at exact head c63be2e78088 polled twice this round: **85 SUCCESS /
   1 skipped / 0 FAILED**, 2 in_progress (the long `test` and
   `Coverage gate (publish-set floor + diff coverage)` legs); explicit
   `conclusion in {failure, action_required, cancelled, timed_out}` scan → empty.
   The prior round's 9 UNREPORTED legs have all drained to SUCCESS.

## Acceptance criteria re-proven at head (executed this round)

| Criterion | Evidence |
|---|---|
| Sole semantic workflow change | Parsed-YAML recursive leaf walk base→HEAD over changed `.github/workflows/` files: exactly **1 delta** = ADDED `jobs.quality-vulture.steps[6].if` = `push && ref != develop && ref != integration && ref != main` (topic-push-only guard) |
| Single required owner on shared events | Only 2 `check-vulture-baseline` invocations repo-wide: vulture-ratchet.yml:82 (PR + merge_group + push:[develop,integration,main], required `exact-debt-ledger`, shared RATCHET_BASE_REV resolver) and quality.yml:1608 (now topic-push-only); check-required-checks exit 0 (79 PR checks) + check-branch-protection exit 0 (21 develop / 35 main) |
| Same command/env/trusted base | Identical scan command in both workflows; CI-exact re-run exit 0 (1220=1220, vulture 2.16, base c9636e99f1d7) |
| Ledger + floors unchanged | Ledger + authorization diffs vs origin/develop empty; check-ratchet-provenance exit 0 (55 consumers); check-shipped-surface-truth exit 0 |
| Event matrix incl. negatives | `tests/test_ci_vulture_ownership.py` inside the focused batch — 80 ownership cases green |
| Repo/shape gates exit 0 | check-required-checks, check-workflow-write-safety (33 workflows), check-suite-inventory (21 suites), check-backlog-consistency (167 items), check-ratchet-provenance, check-shipped-surface-truth, check-branch-protection, `ruff check .` ("All checks passed!"), `ruff format --check .` (3664 files) |
| Focused tests green | **292 passed** (10 diff test files) + **143 passed** (test_check_ratchet_provenance / test_ratchet_provenance / test_ratchet_provenance_integration_base / test_ratchet_provenance_repository / test_shipped_surface_truth) = **435**, 0 failed |

## Residuals (unchanged, live-confirmed this round)

1. **PR body closure keywords** (line 6: "This PR does not close #1357, #160 or #1605."):
   GitHub parses closers despite negation; live API: #1357 closed, **#160 OPEN, #1605 OPEN**
   → merge would auto-close two OPEN issues before verification. Fix is a GitHub-side body
   reword — lane-prohibited (no GitHub mutations from this lane). Also `draft:false`
   contradicts the body's keep-draft language, and body figures drift (measured 1220
   reviewed identities vs "1,328"; 435 focused tests vs "337").
2. **Hosted drain**: 2 long legs (test, Coverage gate) still in_progress at last poll,
   0 failed. Merge must await final drain (CI-side).
3. `mergeable_state` = blocked, consistent only with those 2 pending required legs.

No new tests added this round → no inventory-note delta required (check-suite-inventory
exit 0). Local repair item does not exist; tree otherwise untouched and committed as
this note only.
