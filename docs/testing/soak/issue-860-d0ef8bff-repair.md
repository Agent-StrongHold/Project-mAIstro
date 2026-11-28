# Issue 860 — d0ef8bff CI repair

## Frozen scope

- Sole item: issue #860, branch `auto-860`, starting head
  `e88f90f9af4d6f97f187759fc1f0bea6860af44f`, supplied base
  `b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`.
- Initial worktree clean; no incoming edits to salvage.
- Repair scope: evidence-driven vulture per-identity CI failures; reviewed
  retained identities may be amended in `quality/vulture-baseline.json`.
- Inspection scope: repository instructions, supplied dispatch/prior result,
  relevant ADRs, soak production code and adjacent tests, CI gate implementation
  and workflow. Only files implicated by the actual scan will be repaired.
- No GitHub mutations, new scheduling authority, or promotion claims.
- No driver `check-*.log` files were present in the supplied job directory at
  initial inspection. Writer will run validation locally.

## Progress

The requested exact Vulture invocation passed (exit 0): 1,338 findings match
1,338 reviewed identities; zero unclassified and zero never-allowlist findings.
The default resolver compared against `cd5618223cbd`; an explicit supplied-base
check will also be run. No unbanked identities exist to review or amend, so no
ledger/source change is justified by this scan. The previous job's result was
read, not accepted as verification. Its promotion blockers need fresh checks.

Current production middleware still constructs `InMemoryRateLimiter` per
instance (`packages/maistro-server/src/maistro_server/api/rate_limit.py:72-78`).
The preflight driver explicitly rejects exact-RC equivalence
(`scripts/soak/run_soak.py:635-646`). These are acceptance blockers, not Vulture
failures. No new tests have been added; inventory counts remain unchanged.

Fresh validation: `uv run ruff check .`, `uv run ruff format --check .`, and
`git diff --check b672b799aba6d3db9edc3e1be18b1a3335dd3bc0` passed. The explicit
`RATCHET_BASE_REV=b672b799aba6d3db9edc3e1be18b1a3335dd3bc0` Vulture run also
passed (resolved merge base `cd5618223cbd`).
`uv run pytest tests/test_soak_promotion_gates.py -x -q`: **52 passed**,
including both real middleware-instance allowance counterexamples and
missing/null/preflight exact-artifact rejection cases. These are local ASGI
counterexamples, not a deployed two-replica soak.

Architecture review: ADR-081 is **Proposed**, not accepted authority. Accepted
ADR-081226-a66b retains the single Run/NodeRun/Attempt hierarchy; accepted
ADR-081626-f383 requires durable Attempt fencing and explicitly does not define
lease-expiry takeover. No timeout-based reclaim authority was invented to
satisfy the issue wording. Testing those production contracts remains necessary.

## Final focused validation

All commands used the assigned worktree and ran synchronously with 1,200-second
validation timeouts. Logs are in the supplied job directory under
`check-*-local.log` (worker-created, not driver claims).

- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  **22 passed**.
- `RATCHET_BASE_REV=b672b799aba6d3db9edc3e1be18b1a3335dd3bc0 uv run python
  scripts/check-ratchet-provenance.py`: passed; 49 consumers classified.
- Same base with `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git merge-base HEAD b672b799aba6d3db9edc3e1be18b1a3335dd3bc0` confirmed
  `cd5618223cbdd9ac55d40695987e09fd8b4ef184`; neither Vulture run compared
  against the candidate ledger as its own authority.
- Imported the current `run_soak.py` and executed `failed_promotion_checks`
  against retained `m3a-round6-shakedown.json`: returned
  `['sustain_duration', 'exact_rc_artifact']`. This is re-evaluation of historical
  evidence, **not** a new soak. Its nested `hashes.git_head` is
  `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head.

## Acceptance matrix and handoff

| Issue criterion | Fresh assessment |
|---|---|
| Representative release-candidate profile | UNVERIFIED: load-profile.md:152-164 acknowledges missing multi-user/Workspace, Graph, tool/model, Canvas and reconciliation traffic. |
| Two production application replicas | UNVERIFIED: deploy/docker-compose.prod.yml:15-77 declares two; this attempt did not run them. ASGI middleware instances are not deployment proof. |
| Sustained saturation, reclaim, retries and leaks | UNVERIFIED: retained evidence:163-165 has only 90.43 seconds; no new sustained run. |
| No duplicate physical work/Goal reconciliation | UNVERIFIED: current preflight races admission, not physical Attempt completion/reclaim; load-profile.md:197-200 explicitly limits the claim. |
| Non-bypassable rate limiting/security under concurrency | NOT MET for replica-selection allowance: tests/test_soak_promotion_gates.py:439-489 executes production middleware and observes a fresh budget on replica 2 for both identity classes. Wider security/degradation acceptance remains UNVERIFIED. |
| Complete thresholded production telemetry | UNVERIFIED: load-profile.md:157-164 distinguishes driver-loop lag and process-group samples from application-loop/worker telemetry. |
| Active-work restart/drain/fencing recovery | UNVERIFIED: no new production kill/restart; exit/rejoin alone is not physical-work fencing proof. |
| Long exact-RC artifact/configuration soak | NOT MET: current evaluator rejects retained evidence on duration and artifact identity. |
| Findings classified before promotion | UNVERIFIED for completeness; no new load was run and no GitHub mutations made. Existing local classification is not proof of all load findings. |
| Machine/human evidence bound to exact current hashes | UNVERIFIED for current RC: retained JSON hashes bind an older commit; this note and check logs are validation evidence only. |

Outcome: **BLOCKED** for issue acceptance. The assigned CI failure did not
reproduce; no dead identity removal, ledger amendment, production edit or new
test was justified. The sole changed file is this handoff. Existing source,
tests, evidence and ledgers are preserved. No inventory delta is needed.

Next prerequisite: an explicitly selected immutable RC image/configuration and
production-path representative workload/telemetry runner, with the independent
replica-budget finding reconciled before a promotion-signing long run. Do not
repeat host preflight or ledger scans as substitutes for those prerequisites.
Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0; command
errors 0. CI-repair investigation complete; acceptance remains blocked.
