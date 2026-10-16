# Issue #860 — bounded repair 719d658c

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `39b74bf9b77c72acf53781881f02eb4da7685edf`.
- Base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Only issue #860; no linked PR processing or GitHub mutations.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production schema implementation, `quality/vulture-baseline.json` only if the mandated scan establishes retained debt, associated inventory note, and this report. Read-only acceptance inspection: soak runner/profile/tests, task admission/rate-limit/receipt paths, relevant ADRs and CI definitions.
- Initial worktree clean; no incoming uncommitted changes to salvage.

## Initial evidence and assumptions

The supplied historical `98a11313167b41a98a420abfda80c292/check-3.log`
reports 24 schema statements versus 21 expected. This is not assumed current.
The supplied prior result reports BLOCKED, not release readiness.
No `check-*.log` files were present in the current job directory at entry.
The full dispatch issue body supplies ten acceptance criteria, including an
exact-RC long soak and physical-work uniqueness. No RC designation is supplied
by this assignment; local probes will not be relabeled as production proof.

## Reproduced results (checkpoint 1)

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 reviewed identities / 1322 findings, zero unclassified. No ledger amendment justified; no retained/unbanked identities to repair.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: PASS, 37 passed / 6 skipped. The supplied historical failure is already repaired: lines 173–177 explicitly cover all three Gauntlet audit columns. Production `ensure_schema` still holds the transaction advisory lock over every DDL statement. No new test or production edit justified by that stale failure.
- Logs: `/tmp/860-719d-vulture.log`, `/tmp/860-719d-schema.log`.

## Focused validation (checkpoint 2)

All commands ran in the assigned worktree with a 1200-second timeout:

| Command | Result | Local log |
| --- | --- | --- |
| `uv run ruff check .` | PASS | `/tmp/860-719d-ruff.log` |
| `uv run ruff format --check .` | PASS, 3301 files | `/tmp/860-719d-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | PASS, 72 tests | `/tmp/860-719d-soak-tests.log` |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS, 1 test | `/tmp/860-719d-tasks-tests.log` |

The soak-contract tests execute actual production rate middleware and task router
with in-process ASGI transports. The independent allowance probe at
`tests/test_soak_promotion_gates.py:439` gets `[200, 200, 429]` independently
from each middleware instance for both authenticated and unauthenticated
identities. The receipt probe at line 564 gets 200 on the admitting queue and
404 on the peer despite sharing the canonical admitter. These are current
counterexamples to stronger claims, not production load evidence. Production
sources agree: `api/rate_limit.py:32` documents process-local budgets, and
`api/tasks.py:144` reads `queue.get`, returning 404 for a missing local receipt.
The backpressure test proves the existing HTTP 429 / Retry-After mapping without
admitting excess canonical Runs; it does not prove physical-work uniqueness.

## Architecture reconciliation

Read repository AGENTS and documentation hierarchy, plus ADR-081 (Proposed),
ADR-085 (Accepted), ADR-081226-a66b (Accepted), and ADR-081626-f383 (Accepted).
The Proposed deployment ADR is not treated as accepted authority. Canonical
Goal -> Graph -> Run -> NodeRun -> Attempt ownership remains unchanged.
The accepted lease ADR explicitly excludes lease-expiry takeover semantics;
issue #860 cannot justify inventing a reclaim scheduler or interpreting one
successful occurrence admission as physical-work fencing proof. ADR-085's
per-principal requirement and documented process-local implementation do not
establish the issue's stronger replica-selection protection criterion.
No competing scheduler, execution store, event authority, or auth path added.

## Acceptance assessment

| # | Issue criterion | Current evidence / disposition |
| --- | --- | --- |
| 1 | Representative RC profile | UNVERIFIED. `m3a-load-profile.md` defines a preflight mix but explicitly lacks multi-user/Workspace, Graph fan-out, successful model/tool, Design/Canvas and Goal-worker coverage. No exact RC supplied. |
| 2 | At least two deployed replicas | UNVERIFIED this round. Executed ASGI probes instantiate two middleware/queue instances, not deployed application replicas. |
| 3 | Sustained saturation, queue growth, reclaim, retries, leaks | UNVERIFIED. No sustained production run executed; unit probes cannot substitute. |
| 4 | No duplicated physical work, canonical admission and Goal reconciliation | UNVERIFIED. No active-work recovery/physical Attempt audit executed. Admission-only evidence is insufficient under accepted lifecycle/fencing ADRs. |
| 5 | Replica-resistant rate/security/degraded behavior | NOT PROVEN: executed independent-allowance test demonstrates additional requests accepted on the peer; local 429 and backpressure tests pass. Whole deployment security remains UNVERIFIED. |
| 6 | Production telemetry with thresholds | UNVERIFIED. Profile lists thresholds; sampler tests pass but do not measure production event-loop, pool/worker and long-window leak behavior. |
| 7 | Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. No deployed active-work kill/restart was performed. |
| 8 | Long exact-RC soak | UNVERIFIED and blocked: `scripts/soak/run_soak.py:744` declares host-process preflight non-equivalent; executed four-hour-preflight CLI tests confirm refusal even at nominal sufficient duration. |
| 9 | Findings classified to earliest broken invariant | UNVERIFIED for completeness. Local rate/receipt findings reproduced above; no GitHub mutations permitted or performed. |
| 10 | Hash-bound machine/human production evidence | UNVERIFIED. This human validation report is not exact-image/configuration soak evidence. Historical artifacts were not re-certified. |

## Handoff

No current scanner/test failure justifies a source, test or ledger change.
Only this bounded report is changed; test inventory is unchanged, so no new
inventory note is needed. Do not repeatedly redispatch the stale schema log as
an unfixed failure. Next work requires a designated immutable RC configuration,
a production-topology runner, and explicit disposition of replica allowance,
receipt visibility and physical recovery gaps before a long promotion soak.
Additional CI policy checks completed successfully:

- `uv run python scripts/check-ratchet-provenance.py`: PASS (53 quality consumers); only nonfatal escape-sequence SyntaxWarnings. Log: `/tmp/860-719d-provenance.log`.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS. Log: `/tmp/860-719d-surfaces.log`.
- `git diff --check`: PASS.

The ratchet tools automatically resolved trusted base `321cbdb8fe9b`, as printed
in their logs; the dispatch comparison base remains `ac7370141e8e`. No baseline
selection, grant, or gate was changed to force a pass.

Disposition: **BLOCKED**, not MERGE-READY. Historical CI failure cleared by
current validation; issue acceptance not established. Progress: checked 1 issue,
done 0 acceptance-complete issues, skipped 0 issues, validation errors 0.
This report is the sole file staged for a local checkpoint commit; no push.
