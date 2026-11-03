# Issue #860 — bounded repair validation

## Frozen scope

Job `dfa46a70f137465f8cba065d54cc84a4`, writer in `/home/dev/Git/wt/auto-860`.
Starting head `cc64ce9096a601445a30fe2ef7b72333aa9f435e`; supplied base
`c4fd9fbc6217e5b1a75ff92ca7e7dc195fb6f7a3`. Initial tree clean.
Only issue #860 is processed; no remote enumeration or GitHub mutations.
No driver `check-*.log` files were present in the supplied job snapshot.

Frozen repair targets: this report; `quality/vulture-baseline.json` only if the
required live scanner identifies reviewed retained debt; an inventory note only
if the reported root-suite delta can be attributed to an actual test change.
Read/validation scope: issue body and supplied prior result, repository
instructions, relevant execution/fencing/rate/inventory ADRs, soak runner,
load profile, round30 evidence, soak/production boot tests, task concurrency
tests, rate middleware, inventory checker and notes, CI gate commands.
No replacement scheduler, execution authority, authorization path or Goal store.

Ambiguity: dispatch labels this a CI repair but gives no fresh scanner output.
Proceed by executing the exact requested scan, not by guessing ledger edits.
The previous BLOCKED verdict is a claim to check, not acceptance evidence.

## Progress

- Confirmed starting head and clean worktree; read full issue acceptance body.
- Exact requested vulture scan PASS: 1322 reviewed identities, 1322 findings,
  zero unclassified / never-allowlist. No ledger amendment is warranted.
- Root inventory gate FAIL: expected 5353, collected 5354; 5354 unique identities,
  no byte-identical files. Do not invent a +1 delta to silence it.
- Production profile explicitly calls the runner a host-process preflight,
  incapable of attesting the promoted Compose artifact even after four hours.
  It excludes multi-user/Workspace traffic, Graph fan-out, successful tools/models,
  Canvas and sustained Goal/physical Attempt work. No promotion claim.

## Executed validation

Commands ran in this worktree with 600–1200 second timeouts. Logs are
`/tmp/860-dfa46a70-{vulture,inventory,ruff,format,tests,deployment,evidence}.log`.

| Command | Observed outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1322/1322 identities, no new debt |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3306 files |
| `uv run python scripts/check-suite-inventory.py --suite tests` | FAIL; expected 5353, collected 5354 |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | PASS; 119 tests |
| `uv run python scripts/check-deployment-claims.py` | PASS; declared components/backends exist, not a deployed-soak proof |
| `uv run python` loading `scripts/soak/run_soak.py` with `importlib`, reading round30 JSON and calling `failed_promotion_checks(evidence)` | Rejected: `sustain_duration`, `exact_rc_artifact`; 420.08 seconds, head `c4f45b309fd622f2e8a4b315dad35e721d81aad3`, host-uvicorn-preflight |

Inventory provenance remains **UNRESOLVED**. Bounded inspection of changes from
scanner-selected merge base `2f56be40ad241262b0384ab0b97834ebd37fe4d7` identified
three changed root test files and associated inventory notes, not the origin of
the extra node. No test was added or removed in this round, so no guessed delta,
baseline update, or test deletion is justified. The supplied develop tree must
not be confused with that merge base. This report does not certify the entire
inherited branch diff.

## ADR reconciliation — correction to the previous handoff

Read accepted ADR-081226-a66b (one logical lifecycle), ADR-081626-f383
(fenced Attempts), ADR-085 (per-principal limits), and ADR-082526-547c
(per-change inventory deltas). Also read the **later accepted**
ADR-082526-b36a and ADR-082826-08f0. The previous handoff's reliance on the
original f383 statement that reclaim is not defined is incomplete: b36a defines
TTL/renewal/reclaim, and 08f0 defines recovery dispositions by proven liveness.
A live lease refuses recovery; a lapsed lease is reclaimed through the existing
canonical seam and reconciled with `RECOVERED`. No new reclaim authority or
scheduler is needed or permitted. Those contracts do not themselves prove
physical-work safety under this issue's sustained multi-replica workload.

ADR-085 requires per-principal rate limits; it does not turn process-local
middleware into a shared budget. Existing documented N×limit behavior cannot
be silently reclassified as proof of #860's stronger replica-selection criterion.
No authorization, lifecycle, runtime configuration, or policy changes were made.

## Acceptance — all ten criteria

1. **Representative profile: UNVERIFIED.** `m3a-load-profile.md:167-183`
   explicitly leaves users/Workspaces, fan-out, tools/models, Canvas, Goal
   reconciliation and long-window observations uncovered. The one-key degraded
   preflight is not representative production traffic.
2. **At least two production RC replicas: UNVERIFIED.**
   `deploy/docker-compose.prod.yml:26-77` declares two services. Executed boot
   tests check rendering/startup validation only; no fresh RC deployment ran.
3. **Sustained saturation, reclaim, retry, growth and leaks: UNVERIFIED.**
   Current evaluator rejected the historical 420.08-second run; the documented
   minimum is 14400 seconds. Unit tests do not observe a sustained window.
4. **Exactly-once/fenced physical work and Goal reconciliation: UNVERIFIED.**
   `m3a-load-profile.md:215-217` says the schedule probe cancels its queued Run
   without executing it. Admission counts cannot prove physical deduplication.
5. **Replica-independent rate/security/degraded behavior: NOT MET in the
   exercised middleware path.** Both authentication variants of
   `test_replica_selection_has_an_independent_production_allowance` executed:
   each replica independently returns `[200, 200, 429]` for the same identity.
   Production installs this middleware at `maistro_server/main.py:648`;
   `api/rate_limit.py:92-100` constructs an independent in-memory limiter.
   Passing backpressure/security tests establish their narrower contracts only.
6. **Production metrics with thresholds: UNVERIFIED.** Profile defines
   thresholds, but driver loop lag is not application event-loop lag and
   long-window pool/worker/leak observations remain absent (profile:167-183).
7. **Active-work restart/drain/fencing/recovery: UNVERIFIED.** Boot/probe tests
   and historical process rejoin do not show physical work surviving a fresh
   production RC kill/restart without duplication or loss.
8. **Long-running exact RC: NOT MET by supplied evidence.** Executed evaluator
   rejects both duration and artifact checks. `run_soak.py:744-755` explicitly
   cannot attest a production Compose artifact. No immutable promotion RC and
   normalized runtime configuration were supplied for this round.
9. **Findings filed/reclassified: UNVERIFIED.** Local findings recorded here;
   GitHub mutations prohibited and none performed. No remote closure claimed.
10. **Machine/human evidence bound to promoted hashes: UNVERIFIED.** Round30
    names an older head and preflight configuration, not this head's promoted
    image/package/configuration. No replacement artifact was fabricated.

## Handoff

**BLOCKED; no implementation or integration approval.** Only this report changed.
No new tests, inventory notes, debt-ledger edits, production changes, or evidence
artifact rewrites. Exact-debt-ledger repair was checked and needs no amendment.
The inventory failure and missing promotion evidence remain unresolved.

Next work requires a selected immutable RC/configuration, a representative
production-path workload and instrumentation, resolution of the replica-budget
acceptance mismatch, and a fresh ≥4-hour soak with physical-work/recovery
observations. Use the existing accepted reclaim/recovery contracts, not the
obsolete assumption that no reclaim contract exists. Any subsequent code or
runtime-config change invalidates that soak. Repeating clean scans or short
preflights cannot establish these missing criteria.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: inventory provenance and production RC soak prerequisites}`.
