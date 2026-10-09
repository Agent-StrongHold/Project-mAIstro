# Issue #860 — c99b4bd1 repair checkpoint

## Frozen scope and preservation

Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
Starting HEAD: `deaa43a30b3e3171fd88cba5302c0a145e5d8d74`.
An incoming merge of `1e4933e2a1b7a0bc1bdecfdbafca846c7cb458f4`
(the assigned develop base and resolved origin/develop) is unfinished.
Preserved unstaged/staged binary patches and unmerged index listing in
`../incoming-860-c99b4bd1.patch`, `../incoming-860-c99b4bd1-index.patch`,
and `../incoming-860-c99b4bd1-unmerged.txt`.

Frozen repair files: `.gitleaksignore` (sole conflict), this checkpoint,
and `quality/vulture-baseline.json` only if the requested scan supports an
amendment. Preserve all already staged develop changes. Inspect existing
soak runner/profile/evidence/tests, adjacent production seams, ADRs, Compose
and CI gate definitions; do not expand to other issues. No new tests planned.

The job directory snapshot contains no `check-*.log` files. Prior result read,
not accepted as fresh verification. Missing immutable RC manifest remains an
explicit ambiguity: no host-process run will be substituted for an exact RC
soak. Resolve the existing merge against its frozen base, not a moving remote.

## Progress

- Initial merge conflict is additive historical gitleaks fingerprints; retain
  both sides without expanding any suppression.
- Existing profile explicitly rejects host-emulator promotion and documents
  independent per-replica rate budgets. Old contrary claims are not current.
- Conflict markers removed while retaining both fingerprint blocks.
- Requested exact Vulture command PASS: 1345 findings, zero unclassified or
  unbankable identities. Candidate ledger matches the scan; its comparison
  against the older merge-base ledger prints 1355 -> 1345, not a failure.
  `git diff --numstat origin/develop -- quality/` is empty: the incoming
  develop ledger is preserved exactly. No speculative ledger edits warranted.
- Read Proposed ADR-081 and Accepted ADR-085, ADR-081626-f383,
  ADR-082426-82c7, ADR-082526-b36a. Per-principal identity is not shared budget;
  occurrence admission is not physical-work uniqueness. Keep the canonical
  Goal -> Graph -> Run -> NodeRun -> Attempt ownership and lease authority.
- No execution, authorization, scheduling or rate-policy changes introduced.

## Executed validation

All commands used 1200-second timeouts. No driver check logs were present.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1345 findings.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2859 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: **88 passed, 5 skipped** (missing `MAISTRO_TEST_PG_DSN`).
- `uv run python scripts/check-suite-inventory.py`: PASS, 14 suites.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-compose-secrets.py`: PASS, 8 Compose files.
- `uv run python scripts/check-merge-markers.py`: PASS.
- Inline `uv run python` loaded the current runner and re-evaluated the four
  frozen historical packs (`m3a-soak-evidence.json`,
  `m3a-repair-validation.json`, `m3a-round5-final.json`,
  `m3a-round6-shakedown.json`). All fail both `sustain_duration` and
  `exact_rc_artifact`. Assertions passed; this is not fresh load evidence.
- The same script asserted both merged Vulture and Radon ledgers are
  byte-identical to the assigned develop base. Vulture has 1345 multiset rows,
  1289 distinct identities: duplicates retained, no lost merge rows.

Local transcripts: `/tmp/860-c99b4bd1-{vulture,ruff,pytest,gates,evidence}.log`.
No new tests or changed test counts in this repair; incoming develop test
additions retain their original inventory notes. No inventory amendment needed.

## Acceptance accounting

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | PARTIAL: inspected profile defines traffic/thresholds, but its remaining-profile-gaps section excludes users/Workspaces, Graph fan-out, successful model/tools, Design/Canvas and background reconciliation. Complete RC coverage UNVERIFIED. |
| At least two application replicas | Compose boot-contract tests pass for declaration; two live exact-RC replicas UNVERIFIED. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leaks | UNVERIFIED: historical round 6 is 90.43 seconds, not 14400. No live load executed this round. |
| Schedule/task/Run/Attempt physical-work uniqueness and Goal reconciliation | UNVERIFIED: HTTP admission-oracle regressions pass, but admission uniqueness cannot establish physical-effect fencing or sustained reconciliation. |
| Concurrent rate/security/degraded non-bypass | UNMET: both authenticated and unauthenticated production-middleware regressions reproduce another allowance on replica 2. Full production security/degraded coverage UNVERIFIED. |
| Required metrics with pass/fail thresholds | PARTIAL: live-child process sampler regression passes; production application-loop lag, workers, pools, leases and long-window resource/error observations UNVERIFIED. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: historical rejoin/terminal-count observations cannot establish physical recovery; no fresh RC run. |
| Long-running exact RC artifact/configuration soak | UNMET: all four packs rejected by current duration/artifact gates; exact immutable RC deployment/provider manifest not supplied. |
| Findings filed/reclassified to earliest milestone | Local F-series classifications inspected, external filing UNVERIFIED. No new load findings or GitHub mutations. |
| Human/machine evidence bound to image/package/commit/config | Historical packs inspected; qualifying exact-RC evidence UNVERIFIED. This checkpoint is validation evidence only. |

## Handoff

**BLOCKED**, not promotion-ready. Completed the inherited develop merge without
losing either historical fingerprint block or ledger identities. Local repair
writes only `.gitleaksignore` and this report in addition to preserved staged
develop changes. Commit the complete merge locally; do not push.

The substantive blocker requires release-owner selection of an immutable RC
artifact/configuration/provider manifest, completion of production-path workload
and physical-effect instrumentation, resolution of the replica-budget acceptance
mismatch at the canonical policy seam, then at least 14400 seconds on that exact
artifact. Any runtime/configuration change invalidates the soak. More static
repair rounds cannot manufacture that evidence.

Progress: checked 1 issue; merge repair done 1; acceptance-complete 0;
skipped items 0; validation command errors 0; blocked 1. Next: exact-RC owner
handoff, not another unchanged shakedown or a speculative ledger amendment.
