# Issue 42 repair checkpoint

Frozen scope: issue #42 only; starting HEAD 6731bffddef2c0d89544f76d8baf5ff0c4f19b11; supplied base 626683154ce9dbd521e6754cee494190c0fb29f0. Assigned worktree /home/dev/Git/wt/auto-42.

Incoming state: unfinished merge of 11376c7bef4ea7d17195b90bea8ca9a64a769bb1 with one conflict in tests/migrations/test_capability_invocation_effect_index_migration.py. Staged and unstaged backups saved to ../incoming-42-index.patch and ../incoming-42.patch. Preserve all incoming changes.

Frozen repair file scope: existing merge files; migration conflict; frontend package-lock.json/package.json only if audit reproduces; uv.lock/pyproject.toml only if supply-chain failures reproduce; quality/vulture-baseline.json only for the expressly authorized reviewed identity repair; issue-42 inventory notes and this report. Acceptance inspection scope: canonical runtime/runs/task/chat/graph production adapters and their adjacent tests, relevant ADRs, workflow gates, supplied job evidence. No remote mutations or unrelated implementation.

Assumption: finish the existing resolved-ref develop merge rather than start another merge. Need inspect supplied logs, conflict, and applicable ADRs before editing implementation. Acceptance is not inferred from historical claims.

Initial evidence: supplied check-1/check-2 fail parsing the unresolved migration conflict; check-3 records 607 passed/124 skipped; inventory checks pass. The conflict would resurrect assertions for deleted 043/045 migrations on the incoming side; current revision 058 follows 057. Preserve the surviving 035 conformance checks and absent-043/045 guards while advancing the tested head to 058.

Fresh exact vulture command passed (1,332 findings, 1,335 reviewed identities, zero unclassified); no additional ledger edit justified. Docker at the instructed socket fails to connect, so live PostgreSQL validation is blocked. Historical acceptance claims are not adopted.

Merge resolution committed as f13e0c1d3; incoming staged work preserved. Updated the existing migration chain test to require head 058, preserving absent-043/045 guards and revision-035/store DDL agreement. Focused migration checks: 5 passed, 14 skipped. Ruff check/format pass; both frontend npm audits report zero vulnerabilities.

Supply chain: uv sync --locked --all-extras; uv pip install pip-audit; freeze --exclude-editable; pip-audit --strict --format=json: raw exit 1 (two occurrences of already-triaged ecdsa PYSEC-2026-1325), scripts/pip_audit_gate.py passed including direct dependency usage. No multidict or werkzeug finding. No dependency or allowlist changes warranted.

Fresh focused acceptance: runs/runtime/durable_graph/one_trace suites: 1,791 passed, 295 skipped, 6 SQLite teardown warnings (/tmp/auto-42-repair-runtime.log). Hive physical cancellation/Hyperlight cleanup: 13 passed. Server task restart: 1 skipped because MAISTRO_TEST_PG_DSN is unset. Read Attempt creation/launch and exception cleanup, correlation test, ambiguous-effect real Graph test, and chat lease/recovery test. Bounded execution evidence is strong; no claim of exhaustive production reachability or live PostgreSQL durability.

Final acceptance gates: execution-lifecycles passed (19 classified), foreign-harness-egress passed, wiring-reads passed (11 reviewed unread). Suite inventories pass: tests/ 4,730, core 14,156. CI root test command (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ --ignore=tests/tools/registry -x -q`) passed: 4,532 passed, 122 skipped, 19 warnings (/tmp/auto-42-repair-root.log). Exact supplied dispatch entries confirm #1169/#1170/#1194 closed; no remote re-enumeration.

Post-merge exact vulture rerun passed against base 11376c7bef4e: 1,332 reviewed identities / 1,332 findings. No ledger amendment beyond the preserved incoming merge was needed. In-memory mutation checks proved the updated chain guard rejects an old 057 head and a resurrected 043 revision; no repository files were mutated for these checks. Final ruff check/format and git diff --check passed.

## Acceptance disposition

| Criterion | Executed evidence / residual gap |
| --- | --- |
| Every physical execution has an Attempt | Inspected runs/execution.py:395 persist-before-launch and :591 Runtime execution_id=attempt.attempt_id. Executed runs/durable Graph suites. Universal production-path coverage UNVERIFIED. |
| Chronological retry Attempts | Executed runs/test_execution_is_correlated.py:76 and chat recovery suite; stable Run/NodeRun, distinct Attempt IDs and ordinals [1, 2]. Passed. |
| Canonical idempotency/effect contract, no blind ambiguous retry | Executed graph/durable_runs/test_ambiguous_effect_replay_guard.py:147: real durable Graph/Invocation service, one dispatch across three visits, two refusals, original correlation on UNKNOWN Invocation. Live PostgreSQL concurrent claim semantics UNVERIFIED. |
| Cancellation/deadline physically stops work or classifies non-abortable | Executed Runtime/runs suites plus Hive cancel route and Hyperlight tests (13 passes), exercising provider unwinding and process reaping. Arbitrary external provider behavior UNVERIFIED. |
| Chat lease/fence/reclaim and terminal-write recovery | Inspected chat_execution.py:212-224 canonical TTL/service wiring; executed test_chat_attempt_recovery.py through Container, stopped renewals and failed terminal writes. Live cross-process PostgreSQL restart UNVERIFIED (server restart test skipped). |
| No direct physical bypass on migrated core paths | Inspected canonical Attempt, chat and durable Graph adapters; execution-lifecycles, foreign-harness-egress and wiring gates pass. Exhaustive production reachability UNVERIFIED. |
| Persistence/Events/Invocation correlation across retry/recovery | Executed correlation, one-trace, spine and ambiguous-effect tests on available backends. Cross-process PostgreSQL durability/Event correlation UNVERIFIED. |
| #1169/#1170/#1194 close first | Exact supplied dispatch snapshot entries closed on 2026-09-13, 2026-09-10, 2026-09-29 respectively. No GitHub mutations. |

## Changed files and handoff

Direct repair edits: `tests/migrations/test_capability_invocation_effect_index_migration.py`, `docs/testing/inventory-notes/auto-42-11376c7-merge-repair.md`, and this report. Merge commit f13e0c1d3 also preserves all incoming develop changes (migration 058, provider adapters, learning validation and their tests/notes/ledger changes); its commit diff records that inherited file manifest. No competing scheduler, execution identity, store, event authority or authorization path introduced. No dependency updates, grants or gate weakening.

The specifically observed parser/test merge failure is repaired; npm audits, Python audit policy, exact vulture and ruff gates pass. Root tests: 4,532 passed/122 skipped. Focused core: 1,791 passed/295 skipped. Hive: 13 passed. Focused migrations: 5 passed/14 skipped (overlaps root suite). Server restart: 1 skipped. Existing SQLite teardown warnings remain. The entire multi-package CI test job was not reproduced; these are the precise commands actually executed.

Verdict: BLOCKED for complete issue acceptance, not a demonstrated remaining code regression. Live PostgreSQL service and exhaustive migrated-path review remain necessary; do not interpret skipped tests or historical claims as passes. No issue closure or integration approval.

Progress: {checked: 1, done: 1, skipped: 0, errors: 1, next: provide PostgreSQL and complete remaining production-path acceptance review}. One assigned repair completed and committed locally, one environment error. Final report committed separately; no push.
