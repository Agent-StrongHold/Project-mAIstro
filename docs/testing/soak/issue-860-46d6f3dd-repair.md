# Issue #860 — repair job 46d6f3dd

## Frozen scope

- Issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting head: `ecb9cc5624b43aed0fe5b6357c0d3cf55470da0b`.
- Assigned develop base: `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
- Initial worktree clean; no incoming edits to salvage.
- Process the supplied dispatch snapshot only; no GitHub mutations or refreshes.
- Repair candidates: identities actually reported by the exact vulture scan,
  their source definitions and adjacent tests, and `quality/vulture-baseline.json`
  only if retained findings require amendment. Acceptance inspection is bounded
  to `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `tests/test_prod_stack_boot_contract.py`, server rate-limit/task middleware and
  adjacent tests, core PostgreSQL learning tests, `deploy/nginx.conf`, existing
  soak profile/evidence and the relevant governance/ADR documents.
- Output file: this report. Any new tests require an inventory note.

## Initial evidence and assumptions

The job directory contains no `check-*.log` files. The supplied previous result
is BLOCKED; its claimed checks will not substitute for fresh execution.
The assignment is a writer/CI-repair round, not verifier-only. Ledger permission
is not a reason to manufacture debt or alter a passing ledger. Existing soak
artifacts will be evaluated as historical evidence, not relabeled as current RC.

## Progress

The exact requested vulture command passed (exit 0): **1336 findings matched
1336 reviewed identities**, zero unclassified and zero never-allowlist findings.
No unbanked identity exists to repair or retain; no ledger amendment is justified.
This differs from the previous job's 1342 count and is fresh evidence at the
assigned head, not a copied claim.

Read ADR-085 (Accepted), ADR-081626-f383 (Accepted), and ADR-082426-82c7
(Accepted). Admission uniqueness is not proof of physical-work uniqueness;
Attempt fencing remains owned by the canonical Run store. ADR-081 is Proposed,
not an accepted waiver for missing deployment evidence. The existing local
rate-limiter semantics do not establish replica-independent enforcement. No
competing scheduler, authority, or authorization path will be introduced.

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1336/1336 exact identities. Arguments match `.github/workflows/vulture-ratchet.yml:82-85`.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3003 files already formatted.
- `git diff --check 56332162cf636e9a1e8a7e346101803ed6ec7b1f...HEAD`: PASS. The earlier EOF whitespace finding is not reproduced at this head.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 61 tests in 2.94 seconds. Includes actual production rate-limit middleware with independent replica allowances, real child-process resource sampling, fail-closed artifact checks, and task admission backpressure through the real router/spine.

No tests added or removed; inventory delta is zero and no inventory note is
needed. These are focused regression checks, not a production soak.
- `uv run python` importing the current runner and evaluating the retained
  `m3a-round6-shakedown.json`: PASS as a rejection regression; returned precisely
  `['sustain_duration', 'exact_rc_artifact']`. Current artifact check returns
  `ok=false`, topology `host-uvicorn-preflight`.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.

## Acceptance assessment

| #860 criterion | Evidence / result |
|---|---|
| Representative RC population and workload | UNVERIFIED. `m3a-load-profile.md:152-165` explicitly excludes users/Workspaces, Graph fan-out, successful tool/model work, Design/Canvas and Goal reconciliation from the executed preflight. |
| At least two deployed application replicas | UNVERIFIED for the RC. Profile lines 19-24 describe host uvicorn rather than the production Compose artifact. Middleware tests exercise two ASGI instances, not deployed replicas. |
| Sustained saturation, queue growth, reclaim, retries, leaks and restart observations | UNVERIFIED. Retained evidence lines 163-165 and 221-224 records 90.43 seconds, below the 14400-second threshold. No fresh soak executed. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | UNVERIFIED. Admission identity tests pass; profile lines 197-200 explains that its one occurrence probe cancels the queued Run without executing physical work. |
| Replica-selection non-bypass, security and degraded behavior | NOT MET for a replica-independent allowance: `tests/test_soak_promotion_gates.py:439-488` passes while observing `[200, 200, 429]` independently on both replicas with the same identity. Source `api/rate_limit.py:25-30,72-76` explicitly uses process-local state. Task ceiling backpressure is tested, but full concurrent production security/degraded behavior is UNVERIFIED. |
| Complete production telemetry with pass/fail thresholds | UNVERIFIED. Profile lines 157-165 distinguishes wrapper/process-group sampling and driver lag from application-loop/worker measurements. Resource sampler regression tests do not replace a production time series. |
| Active-work kill/restart, graceful drain and fenced recovery | UNVERIFIED. Historical process exit/rejoin and terminal counts do not prove physical effects or stale-worker rejection under load. |
| Long exact-RC soak, repeated after runtime changes | NOT MET. Current runner `scripts/soak/run_soak.py:635-646` always rejects its host topology. Re-evaluation of retained evidence fails duration and artifact gates. |
| Findings classified to earliest broken invariant | Historical findings documented, but completeness UNVERIFIED. This attempt made no GitHub changes. |
| Human/machine evidence bound to exact artifact/configuration | UNVERIFIED for the assigned RC. Retained evidence line 71 binds to `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head, and has no promoted application image identity. This report is validation evidence, not soak evidence. |

## Disposition and handoff

**BLOCKED**, not merge-ready. The requested CI defect is not reproduced; no
source, gate or ledger edits are justified by this scan. Only this report changed.
The earlier worker-attention blocker remains unresolved because production load
acceptance is absent, not because of vulture debt or a merge conflict. A further
identical ledger-repair retry cannot supply that evidence.

Next action: select and identify the exact production RC/configuration, complete
its representative workload and application telemetry, address the demonstrated
replica-budget contract gap through the existing enforcement path, then execute
a new >=4-hour two-replica soak with active physical work and failure injection.
Do not relabel historical preflight evidence or bypass the artifact gate.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0, errors 0
validation commands. No full-package suite or deployed soak is claimed. Local
report commit is the writer checkpoint, not integration approval.
