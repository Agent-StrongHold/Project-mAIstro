# #860 interrupted-recovery handoff

## Frozen scope and preservation

- Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified as `b26a6cd95e464dcb2c3092fa720c31127da82850`; supplied base `fa2deb0a45155641f1c5c396d452ab47855bd028` resolves.
- Scope: inspect instructions, existing soak profile/evidence, relevant ADRs, supplied prior result, and execute focused read-only validation. Only this new handoff will be committed. No production, test, configuration or debt-ledger edits are authorized by actual findings yet.
- Initial status has 271 entries. The pre-existing staged diff spans 261 files (26497 insertions, 6448 deletions), including unrelated release, installer, Canvas, campaigns and scheduling work. Many staged additions are absent from the working tree; 34 HEAD-tracked soak files are staged deleted but present as untracked paths. There are no unmerged index entries. This is not an ordinary develop merge conflict.
- Preserved unstaged tracked changes in `../incoming-860.patch` and staged changes in `../incoming-860-index.patch` using `git diff --binary` and `git diff --cached --binary`. Existing untracked files remain untouched in place. These patches alone do not back up untracked files.
- Reported previous failure: `orphan rebuild apply failed: error: corrupt patch at line 529873`. Its original patch was not supplied in the job directory. Do not retry a guessed patch, reset the index, discard files, or commit the unrelated staged tree.
- Assumption: the mixed index/working-tree state is incomplete recovery, not permission to integrate 261 unrelated files. Under the destructive-git prohibition, stop implementation and preserve this state for recovery by its owner. The recovery block remains unresolved.

## Available inputs

The job directory snapshot contains only `events.jsonl`, `manifest.json`, `prompt.txt`, and `state.json`; no `check-*.log` files were supplied. Driver checks are unavailable, not presumed passing. The prior result exists and reports BLOCKED, but is not fresh validation.

The existing `m3a-load-profile.md` explicitly describes a host-process preflight rather than the exact production artifact, with incomplete representative workload coverage. No immutable promotion RC artifact/configuration is designated in the assignment. A new four-hour promotion soak cannot honestly be claimed from these inputs.

## Validation

Fresh commands, each with a 1800-second timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1402 reviewed identities / 1402 findings, zero unclassified or never-allowlist findings. No ledger change is justified by this result.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2624 files already formatted.

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`: 84 passed, 5 skipped in 9.21s. Skips are not live PostgreSQL acceptance evidence. Executed real-middleware tests demonstrate independent per-replica allowances for the same authenticated and unauthenticated identity; CLI tests reject missing/null/preflight RC artifact records even at four hours.

No tests added or modified; inventory delta is zero. No deployment or soak was executed.

## Architecture and acceptance reconciliation

Read repository instructions and accepted ADR-081626-f383 (Attempt lease authority belongs to the canonical store), ADR-082426-82c7 (occurrence identity belongs to the Run), and ADR-085 (principal rate limiting). No competing scheduler, store, event or authorization authority was introduced. Admission uniqueness is not proof of physical-effect uniqueness; per-process rate limiting is not cluster-wide enforcement. The issue's broader acceptance remains blocked rather than overriding those boundaries.

| Criterion | This round's evidence / remaining gap |
| --- | --- |
| Representative release profile | PARTIAL: existing profile explicitly excludes users/Workspaces, Graph fan-out, successful tool/model traffic, Canvas and Goal workers. Representative RC coverage UNVERIFIED. |
| Two production application replicas | UNVERIFIED: tests use ASGI instances, not exact production images. |
| Sustained saturation/reclaim/retry/leak observation | UNVERIFIED: no sustained deployment traffic this round. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: passing regression gates are not physical-work oracles under multi-replica load. |
| Rate-limit/security/degraded non-bypass | NOT MET for cluster-wide allowance: executed `test_replica_selection_has_an_independent_production_allowance` returns `[200, 200, 429]` independently for each replica and identity class. `api/rate_limit.py:25-30` explicitly documents N-times aggregate allowance. Other full-RC security/degraded behavior UNVERIFIED. |
| Complete metrics and explicit thresholds | UNVERIFIED: no fresh sustained metrics; profile itself distinguishes driver-loop from application-loop lag. |
| Kill/restart active-work recovery | UNVERIFIED: no replica kill/restart or physical-effect correlation executed. |
| Long-running exact-RC soak / rerun on changes | UNVERIFIED: no designated immutable RC artifact/configuration, no new soak; passing CLI tests establish that four-hour preflight evidence is insufficient. |
| Findings filed/reclassified | Existing local classifications retained, external filing UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence tied to exact artifact/config | Historical preflight pack retained; promotable exact-RC evidence UNVERIFIED. |

## Disposition

BLOCKED. Implementation stopped to avoid absorbing or discarding unrelated recovery state. Next: owner reconciles the preserved staged/unstaged recovery inputs without loss, designates exact RC images/configuration, then resumes the production-path workload and soak work. A handoff-only commit is not issue completion or integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner-assisted non-destructive recovery, then exact-RC prerequisites}`. The one error is the unresolved incoming recovery state, not a failing vulture/lint/regression command. This handoff is the only new file changed by this worker; all pre-existing staged, unstaged and untracked work is intentionally left in place. Commit with an explicit single-path `git commit --only` so the unrelated index is not absorbed.
