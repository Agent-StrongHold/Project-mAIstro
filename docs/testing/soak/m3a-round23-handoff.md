# Issue #860 — round 23 validation checkpoint (CI-repair round)

**Not promotion evidence or integration approval.** This round re-proves the
branch state left by round 22 (`31c82fe84`), resolves the completed CI
evidence for the PR head `cd77bb81c` that was still pending at round 22's
capture, and dispositions the one newly completed required-gate failure
(`quality` → Coverage gate) with fleet-wide evidence that it is not
branch-caused. The issue's soak acceptance blockers are unchanged external
prerequisites.

## Frozen scope

Only issue #860 and the CI failures observable on its heads, in
`/home/dev/Git/wt/auto-860`, starting at clean HEAD `31c82fe84a4f7` (matches
the assigned job head; `git status` clean, `1e640df17c` assigned develop base
is an ancestor). The job directory contained **no `check-*.log` files** — the
driver ran no deterministic checks this round — so every check below was
executed locally at `31c82fe84`. No tree edits were needed beyond this
checkpoint; the round-22 repair commit already contains the gitleaks fix.

## New evidence: completed GitHub CI on cd77bb81c (read via gh, read-only)

Round 22 recorded `test` and `Coverage gate` as `in_progress`. All runs have
now completed for PR #1672 head `cd77bb81c` (triggered 2026-10-06T14:31Z):

| Required context (branch-protection.json) | Result on cd77bb81c |
| --- | --- |
| `security` / `SAST (bandit + semgrep + gitleaks)` | **failure** — the gitleaks leak **repaired by `31c82fe84`** (re-verified below) |
| `test` (CI workflow, 41m33s) | **success** |
| `quality` → `Quality gate (Pillars 1–4, 7, 8)` | success |
| `quality` → `Coverage gate (publish-set floor + diff coverage)` | **failure** — see disposition |
| `coverage (no services)` / `(MinIO)` / `(PostgreSQL)` | success (producers) |
| `Vulture Ratchet` (`exact-debt-ledger`) | success |
| Gate C, Formal Conformance, Integration Scope, Registry, Cage Guard, DevSkim | success |

### Coverage-gate failure disposition: shared-runner congestion flake, not branch-caused

The `combine` step of the Coverage gate runs a broad pytest sweep; its log
(run 37479652264, job 112329590632) ends with:

```
FAILED tests/test_check_security_inventory.py::test_the_shipped_document_passes - Failed: Timeout (>30.0s) from pytest-timeout.
1 failed, 4672 passed, 122 skipped, 20 warnings in 1007.88s (0:16:47)
```

Evidence this is environmental, in decreasing order of force:

1. **Four other lanes' PRs failed the identical job in the same window**
   (13:16–14:31Z): runs 37469446962 (#860 @ 20c975f3b), 37471366492
   (auto-966 #2009), 37473154729 (auto-1572 #1938), 37473654685 (auto-82
   #1702), 37477840537 (auto-1852 #1941) — all red on `Coverage gate
   (publish-set floor + diff coverage)` while **develop's own
   `merge_group`/`push` runs stayed green at 14:30 / 15:03 / 15:15Z**
   (37479545245, 37484152566, 37485914321).
2. **Zero causal content in the branch**: `git diff
   1e640df17..HEAD -- SECURITY.md scripts/check-security-inventory.py
   tests/test_check_security_inventory.py` is empty, and the branch's only
   two files under the scanned `packages/*/src` trees
   (`maistro/persistence/pg_learnings.py`,
   `maistro_server/api/tasks.py`) cannot move a repo-walk scan by the
   ~3× its timeout would need.
3. **Local runtime**: the test passes at `31c82fe84` in **10.43s** of its
   30s `pytest-timeout` bound — a loaded shared runner mid-sweep crosses
   that; this worktree does not.

The branch does not own the 30s bound (`tests/test_check_security_inventory.py`,
#157) and raising it would weaken a shared gate, so the disposition is:
**re-run on a decongested window**; no in-tree repair exists that is not
either a no-op or a gate weakening.

## Revalidation at 31c82fe84 (all executed this round)

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS (3048 files) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` (prior verifier argv) | 38 passed, 6 skipped |
| `uv run pytest tests/test_gitleaksignore_contract.py tests/test_soak_promotion_gates.py -q` | 60 passed |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI args) | PASS: 1332/1332, base `1e640df17c8a` |
| `uv run python scripts/check-suite-inventory.py` | PASS: 16 suites match |
| `gitleaks git --redact --log-opts="1e640df17c..HEAD" .` (CI PR arm) | **no leaks found** (185 commits) |
| `gitleaks git --redact --log-opts="--all" .` (develop push arm) | 10 findings, each on a commit verified `git merge-base --is-ancestor`-**not reachable** from HEAD (other lanes' rebased refs) |
| `uv run bandit -r packages/maistro-core/src packages/hive-conductor/backend packages/maistro-server/src -ll --confidence-level=medium` | Medium+ count: 0 |
| `uvx semgrep --metrics off --config tools/semgrep/maistro-rules.yaml --config p/security-audit --config p/owasp-top-ten --config p/secrets --exclude 'packages/hive-conductor/eval' --exclude 'packages/hive-conductor/cage' --error packages/ tests/` | 0 findings (364 rules, 2067 files) |
| `uv run mypy packages/maistro-core/src … packages/maistro-design/src` (CI argv) | Success: no issues found in 976 source files |
| `uv run python scripts/check-required-checks.py` | PASS: 33 PR checks match |
| `uv run python scripts/check-merge-markers.py` | PASS |
| `test_the_shipped_document_passes` (the CI-timeout test) | PASS locally in 10.43s (30s bound) |
| `failed_promotion_checks(m3a-round8-prodstack-extended.json)` replay | reproduces the pack's own recorded `promotion_gate_replay.failed_checks` (10 gates) byte-for-byte — the pack is honestly labelled *not promotion evidence* |

## Acceptance audit (unchanged in substance)

The external prerequisites recorded by rounds 19–22 stand and are not
reachable by this lane:

1. **No release-owner RC designation** of an immutable image/configuration
   exists, so the ≥4 h soak of the exact RC artifact cannot start;
   `scripts/soak/run_soak.py` `preflight_artifact_check` deliberately returns
   `ok: false` for host-process runs with no CLI override, and the longest
   committed observation remains 1200 s vs the 14400 s floor
   (`sustain_duration: ok:false` in the round-8 pack, whose gate replay this
   round reproduced byte-for-byte).
2. **#842 aggregate cross-replica rate-budget ownership decision** — the
   owning lane's call, not this one's.
3. **Provider-credentialed production-path workloads** (physical Attempt
   fencing, Goal reconciliation under load) remain unverifiable without
   credentials.
4. **GitHub filing of load findings** stays prohibited in-lane; the local
   M3-A classifications from earlier rounds remain the record.

What this round adds: the completed CI picture for the PR head (the `test`
required check is green; the only branch-caused required failure — gitleaks —
was repaired in `31c82fe84` and re-proven clean in both scan arms), and a
fleet-evidenced, non-branch-caused disposition for the Coverage-gate
congestion flake. `origin/develop` advanced by two M9 commits
(`e28835544`, `bc40b6cda` — connectors/SDK/extension authority) with no file
overlap with this lane; integrating them is the driver's merge-window call,
not a repair this round owed.

`{checked: 2, done: 2, skipped: 0, errors: 0, next: designated RC artifact,
#842 aggregate-rate ownership decision, provider-credentialed soak, Coverage
gate re-run on a decongested window, then a ≥4 h soak of that exact artifact
before final promotion}`
