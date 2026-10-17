---
inventory-delta:
  tests/: +27
---

# #860 focused repair: direct rate-limit coverage

## Frozen scope and starting evidence

- Issue snapshot: #860 only; assigned worktree `/home/dev/Git/wt/auto-860`,
  branch `auto-860`, starting HEAD `7993e290430ce66f8831ea3b952885f20cbaf919`.
  This continuation received the four files below uncommitted; tracked changes
  and this note were backed up in the assigned job directory before editing.
- Files in this repair: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  and this note. No runtime/scheduler/authorization changes or evidence overwrite.
- Executed the requested vulture command at starting HEAD: PASS, 1402 reviewed
  identities / 1402 findings, zero unclassified. No ledger amendment is justified.
- The current job directory contains no `check-*.log` files. The prior result
  was read as context only, not accepted as fresh validation.
- Confirmed reachable driver passes only replica 1 to `phase_rate_limit`.
  The production middleware explicitly documents independent process-local
  budgets. Assumption: test each replica's documented budget, not introduce a
  cluster-wide limiter or claim this proves a shared budget.
- Exact-RC production Compose identity and a four-hour soak are absent from
  the existing preflight evidence. This repair cannot confer promotion approval.

## Implementation checkpoint

The phase now probes both identity classes through the LB and each direct
replica (six paths), records direct results by origin, and includes all six
results in H3. It rejects empty/single/duplicate/LB-as-replica topology input.
Twenty-five added test nodes cover successful evidence, every path failing
(disabled limiter, missing Retry-After, transport failure), topology rejection,
and two real production middleware instances behind an ASGI routing fixture.
Disabling replica 2 must fail H3 even though both LB bursts still observe 429.
The fixture is not deployment or long-running soak evidence.

ADR reconciliation: ADR-085 (Accepted) requires per-principal request budgets;
its token-quota/approval policy is not altered here. ADR-081 is Proposed, not
an accepted authority overriding the reference Compose artifact. Accepted
ADR-081626-f383 makes Attempt fencing canonical and explicitly leaves
lease-expiry takeover outside its current boundary. This patch introduces no
scheduler, execution authority, or authorization path and makes no claim to
prove physical exactly-once execution from admission-only probes.

## Validation and acceptance

Fresh validation in this continuation (logs in job directory
`/home/dev/maistro/jobs/d8e10b05fa03453ea6d25062997338a6`):

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  — **79 passed, 5 skipped**, 534.22 s. PostgreSQL integration tests skip
  without `MAISTRO_TEST_PG_DSN`; these are not counted as acceptance proof.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 2624 files formatted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS, 1402 reviewed identities / 1402 findings, zero unclassified.
  The explicitly permitted ledger repair has no outstanding identities; no
  ledger amendment or dead-code removal is warranted.
- `uv run python scripts/check-deployment-claims.py` — PASS (component names
  resolve; this gate does not validate topology behavior).
- `uv run pytest tests/test_soak_promotion_gates.py --collect-only -q`
  — **29 collected**, versus four test functions at starting HEAD: +25.
- `git diff --check` — PASS.
- First `uv run python scripts/check-suite-inventory.py --suite tests/`
  attempt timed out after 600 s. The incoming note's older 4173/4175 result
  was not assumed to be a current successful gate. After the reconciliation
  below, `uv run python -u scripts/check-suite-inventory.py --suite tests/`
  — **PASS, 4175 collected / 4175 expected** (1200 s timeout).

Inventory reconciliation: this note records **+27 = 25 new probe nodes + 2
previously unrecorded missing/null-drain regression nodes**. The existing
`m3a-860-promotion-gates.md` records only the first two nodes; the later two
are documented in `m3a-860-multi-replica-soak.md` but have no front-matter
delta there. The inventory baseline has no folded notes. No baseline or
unrelated ledger is changed.

## Acceptance disposition / handoff

| #860 criterion | Evidence and remaining gap |
|---|---|
| Representative RC profile | Partial: profile documents HTTP mix and thresholds; multiple users/Workspaces, Graph fan-out, real tool/model calls, Design/Canvas and background-worker applicability are **UNVERIFIED**. |
| Two production replicas | **UNVERIFIED** for the promoted configuration. Two real middleware instances in ASGI tests are not two deployed applications. |
| Sustained saturation, retry/reclaim and leaks | **UNVERIFIED**. Preserved round-6 evidence sustained only 90.43 s. Accepted Attempt fencing ADR intentionally does not yet define lease-expiry takeover; no competing reclaim authority is introduced. |
| Exactly-once physical work / Goal reconciliation | **UNVERIFIED**. Schedule admission races and duplicate Run IDs do not count physical effects or prove ongoing Goal reconciliation. |
| Rate limiting/security/degraded behavior | Six-path probe regression is proven, including a disabled second replica hidden by healthy LB bursts. Cluster-wide non-bypass remains **UNVERIFIED**: production state is process-local (`rate_limit.py:25-30`). |
| Required metrics and explicit thresholds | **UNVERIFIED** under sustained production load. Driver-loop lag is not application-loop lag; soft observations do not enforce every requested threshold. |
| Kill/restart without lost/duplicated work | **UNVERIFIED** on exact RC. Historical preflight drain/rejoin records are not physical-effect fencing proof. |
| Long soak of exact promoted artifact/config | **UNVERIFIED**: no four-hour production Compose soak or promoted image/config identity supplied. Any changed code/config requires re-soak. |
| Findings filed/reclassified | Historical evidence pack records findings; external filing/earliest-invariant classification is **UNVERIFIED**. No GitHub mutation performed. |
| Machine/human evidence bound to artifact | Historical JSON/Markdown preserved, not upgraded to the six-probe schema. Exact production image/package/config evidence remains **UNVERIFIED**. |

Residual misleading historical prose is not acceptance evidence:
`m3a-soak-evidence.md` run-6 H3 asserts shared-store rate-limit non-bypass,
contradicted by production middleware's process-local contract. Its physical
exactly-once language exceeds the admission-only probe. The profile's claim
of sustained task/schedule reconciliation likewise exceeds the one-off
post-load schedule race. These remain blockers for issue #860's full proof;
this focused repair is not a promotion signature.
