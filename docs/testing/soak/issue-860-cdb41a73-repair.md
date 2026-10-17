# Issue #860 — cdb41a73 repair checkpoint

## Frozen scope

- Assigned item: issue #860, branch `auto-860`, starting head
  `91ca5526bb3153978111042eaf87c96f17660301`, base
  `68079320f8df9bdad827467490c0735dde7c03c1`.
- Worktree was clean. No incoming changes to salvage.
- Inspect existing soak runner, promotion tests, production rate-limit path,
  deployment/profile/evidence documentation and relevant ADRs. Run focused
  validation and the explicitly requested exact-debt-ledger gate. Change only
  this checkpoint unless actual validation identifies a repairable defect;
  amend the ledger only for reported, reviewed identities.
- Job directory has no `check-*.log` files. Driver-check claims cannot be
  independently inspected here. Prior result `ce66fe93.../result.json` exists
  and reports BLOCKED; it is context, not fresh acceptance evidence.
- Assumption: this is a writer/CI-repair round, not a read-only verifier round.
  No exact promotion RC artifact/configuration was supplied in the assignment.
  Existing preflight packs must not be relabeled as production soak evidence.

## Progress

- Required vulture command PASS: 1372 findings / 1372 reviewed identities,
  unclassified=0, never_allowlist=0. No unbanked identity exists to review or
  amend; no speculative ledger change.
- `uv run ruff check .` PASS; `uv run ruff format --check .` PASS (2715 files).
  Commands executed with a 1200-second timeout.
- Existing summary already retracts the shared-limiter claim. Existing profile
  explicitly lists missing representative workloads and says host preflight
  cannot sign an exact-RC soak. The prior wording finding does not reproduce.
- ADR-085 is Accepted and requires principal-keyed rate limits, not an established
  shared counter. ADR-081 is Proposed. Accepted ADR-081626-f383 assigns fencing
  authority to the canonical Run store: admission counts cannot prove physical
  Attempt uniqueness. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt;
  no alternate execution or authorization path is introduced.
- Focused pytest PASS: 88 passed, 5 skipped in 11.78s. PostgreSQL integration
  tests require `MAISTRO_TEST_PG_DSN`; no live DB proof claimed. The production
  middleware regression executes both identity classes and demonstrates another
  allowance on replica 2 after replica 1 is exhausted (test lines 480–486).
- Compose-secret gate PASS (8 files); root suite inventory PASS (4320 cases).
  Validation used a 1200-second timeout. No tests added, so no inventory delta.
- Historical-pack check PASS: imported current `failed_promotion_checks` and
  asserted each of the four existing packs fails both `sustain_duration` and
  `exact_rc_artifact`. Run 5 is 90.17s; run 6 is 90.43s, versus 14400s minimum.
  Earlier two packs omit top-level sustained duration. No raw evidence changed.
  No GitHub mutation or integration approval.

## Commands executed

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run ruff check .
uv run ruff format --check .
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs
uv run python scripts/check-compose-secrets.py
uv run python scripts/check-suite-inventory.py --suite tests/
uv run python -  # import current gate; assert duration/artifact rejection; hash four packs
```

Fresh SHA-256 results for `evidence/` (historical identity, not new soak proof):

| Pack | SHA-256 |
|---|---|
| `m3a-soak-evidence.json` | `f9a3e0f594188f3008ccd614b92bc02dfcdd26925122b41a1c12a369848241be` |
| `m3a-repair-validation.json` | `076cd80bd6e295ce99bb33f6045426a80f9ba68294d4f9be86549d3fdfb0fec5` |
| `m3a-round5-final.json` | `47fcdd3ddaad286d6498027af7b64f91bb89f35aa0c85ccac35e9b824791a89f` |
| `m3a-round6-shakedown.json` | `19813c32aa5229489cc44e52d9bf91b83906f176085b370815d3539d95cd880b` |

## Acceptance disposition

| Criterion | Evidence and remaining gap |
|---|---|
| Representative RC load profile | PARTIAL: `m3a-load-profile.md` defines traffic and thresholds but explicitly lacks multi-user/Workspace, graph fan-out, successful model/tool, Design/Canvas and Goal workloads. Completeness UNVERIFIED. |
| Two application replicas | Executed production Compose contract tests pass; reference Compose defines two replicas. Actual exact-RC deployment under load UNVERIFIED. |
| Sustained saturation, queues, reclaim, retry, leaks and shutdown | Current gate rejects all four historical packs. Long-window observations UNVERIFIED. |
| No duplicate physical work; Goal reconciliation | Admission-oracle tests pass, but use mock HTTP receipts; task backpressure test uses the real router and in-memory canonical spine without a runner. Schedule preflight cancels its probe Run without execution. Physical Attempt and Goal proof UNVERIFIED. |
| Rate/security/degraded non-bypass | NOT MET: executed `tests/test_soak_promotion_gates.py:480-486` gives the same identity independent `[200,200,429]` sequences on two production middleware instances. Installed in production at `packages/maistro-server/src/maistro_server/main.py:588`. Full concurrent security/degraded load proof UNVERIFIED. |
| Complete telemetry and explicit thresholds | Live Linux child sampler test passes. Application event-loop latency, detached workers and sustained pool/query/lock/queue/error observations UNVERIFIED. |
| Active-work kill/restart and recovery | Historical process exit/rejoin is not physical-work drain/fencing/recovery evidence. UNVERIFIED. |
| Long soak of exact RC artifact/config | UNVERIFIED: `scripts/soak/run_soak.py:635-645,1465` always rejects its host-process topology as exact-RC proof; historical durations fail. No immutable promotion image/config supplied. |
| Findings filed/reclassified | Existing local F1–F12 records preserved. External filing UNVERIFIED; GitHub mutations prohibited. |
| Hash-tied machine/human evidence | Historical pack hashes freshly computed above. Qualifying RC-image/config-bound soak evidence UNVERIFIED. |

## Final handoff

**BLOCKED**, not acceptance-complete. The requested CI failure does not reproduce;
there is no actual unbanked identity to repair. Prior H3 wording is already
corrected. Only this validation report changed; no runtime/config, tests, ledger,
grants or historical evidence changed. No cosmetic or speculative repair.

Next owner must identify the immutable #89 RC image and frozen configuration
(including a working model gateway), resolve the independent-rate-budget mismatch,
complete representative workloads and physical Attempt/fencing/recovery oracles
and telemetry, then execute at least 14400 seconds on that exact topology. Any
code/runtime-config change requires a fresh soak. Running the current emulator
longer cannot discharge the exact-artifact requirement. Local findings need
external triage by an authorized owner before promotion.

Checkpoint: checked 1 assigned issue, done 0 acceptance-complete issues, skipped
0 assigned issues, errors 0 validation command failures. Validation/reporting
complete; acceptance remains blocked. Commit this report locally without pushing.
