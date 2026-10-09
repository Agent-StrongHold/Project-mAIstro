# Issue #860 — round 21 validation checkpoint

**BLOCKED for promotion acceptance; this round resolves the previous
"worker requested attention: BLOCKED" request by producing new
production-artifact evidence and revalidating at the merged head. Not
promotion evidence or integration approval.**

## Frozen scope

Only issue #860 and the explicitly assigned vulture per-identity gate, in
`/home/dev/Git/wt/auto-860`, starting at clean HEAD
`20c975f3b617ac5caa8ac97a04c510ee21bbfdce` (matches the assigned job head;
working tree was clean). Assigned develop base `1e640df17c8a` is now an
ancestor of HEAD: commit `20c975f3b` merges `1e640df17c` (M9-C3
extension/Gauntlet/dependency work) into this branch. The merge touches none
of this issue's surfaces — `git diff --stat
56332162cf..1e640df17c -- scripts/soak/ docs/testing/soak/
packages/maistro-server/src/maistro_server/api/rate_limit.py
tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py
deploy/ packages/maistro-server/tests/api/test_rate_limit.py` is empty — but
it does change `quality/vulture-baseline.json` upstream (4 lines), so the
per-identity ledger was re-verified after the merge per
`docs/quality-gates.md`.

The job directory again contains no `check-*.log` files, so all deterministic
checks were executed locally. The prior lane job
(`ab2f3bc48bf04c74a2c3a037d0c3e3d0`) died on a provider timeout with no
report and no checks; there was nothing to salvage from it beyond this
worktree's committed state. The previous round's block was an acceptance
block, not a develop sync conflict; the develop head was merged cleanly by
the assigned head itself and no conflict resolution was needed.

## Fresh validation at 20c975f3b

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3047 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI args) | PASS (exit 0): 1332 reviewed identities / 1332 findings, 0 unclassified, 0 never-allowlist; baseline base `1e640df17c8a`, candidate `20c975f3b617`. The develop merge updated the ledger upstream and the merged tree still matches it (`git diff --numstat origin/develop -- quality/` is empty). No ledger amendment warranted. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_rate_limit.py -q` | 82 passed in 3.12 s |
| `git diff --check 56332162cf...HEAD` | PASS: whitespace clean (the earlier blank-line-at-EOF findings in `issue-860-13ec34d7-repair.md:97`, `issue-860-62822668-repair.md:106`, `m3a-round16-handoff.md:112` are fixed) |

## New production-artifact evidence: extended sustained observation round C

The `m3a860` production Compose stack (deployed from this worktree's
`deploy/docker-compose.prod.yml` by the round-7 worker, up since
2026-10-06T11:05Z) was still running at this round's start. Its two server
replicas run the **same image IDs recorded by round 7B**
(`m3a-round7-prodstack-observation-round-b.json` hashes:
`sha256:ef3698e0…`, `sha256:e1952541…` — verified live via
`docker inspect`), so the new round is directly comparable.

This round ran a third sustained observation window on that artifact,
extending the longest production-stack observation from 360 s to 1200 s
(schema `m3a860.production-sustained-round/v1`, driver kept out of the tree;
only its JSON evidence is committed):

- Profile: the production-limit-aware mix of round 7B unchanged
  (health_ready 0.3 / health_live 14 / task_submit 0.8 / run_get 0.4 /
  metrics_unauth 1.5 rps through the nginx LB at 127.0.0.1:18080).
- Totals: 20,094 requests in 1200 s, **0 client transport errors**;
  health_live 16497×200; task_submit 959×202; run_get 480×404;
  metrics_unauth 1797×401 + 1×429 (the shared-IP limiter engaged once under
  sustained unauthenticated load — enforcement, not bypass);
  health_ready 356×503 + 4×200 (see recovery below).
- Kill window at t=600.4: `docker restart -t 20` (SIGTERM drain) of replica
  2 completed in **2.25 s** with **zero client-visible errors in the window**
  (no 5xx, no transport errors; nginx passive failover served everything).
  Worst-case latency across all kinds is bounded by the drain window
  (~2.30 s max vs p50 3.8–25 ms), i.e. in-flight requests drained instead of
  failing.
- Exactly-once admission held over the longer window: 959/959 distinct
  run_ids, **0 duplicate rows** in `canonical_runs`, all 959 terminal
  (`failed` — the documented no-provider degraded path), 0 non-terminal
  after the 90 s settle. Whole spine before/after: `{failed: 681, queued: 2}`
  → `{failed: 1640, queued: 2}`; the 2 `queued` rows pre-date this window
  (earlier rounds' probes) and were not touched by it.
- New observed recovery semantics: LB-visible `/health/ready` returned
  **200 for ~15 s after the restart** (t=617.7–633.1 sampler window; 4
  client-side 200s) because the restarted process registers no LLM circuits
  until first use (`api/health.py` readiness treats "no circuits registered"
  as ready), then re-degraded to 503 once failing tasks re-tripped the
  circuit. This is the per-replica readiness recovery shape, recorded as
  observed behavior of the artifact — a replica restart temporarily clears
  its own readiness signal while the provider dependency is still absent.
- Resource trends over 84 samples (15 s interval): srv1 RSS
  146.9→150.5 MiB (max 150.6), FDs 18→16 (max 20), procs 5 constant; srv2
  RSS 147.1→148.9 MiB, FDs 18→15 (max 19), procs 5 constant; PG 13–15
  sessions, 0 waiting locks at every sample, 1 streaming walsender
  throughout. No leak signal in the window.
- Latency p50/p95 (ms): health_live 3.76/5.80, metrics_unauth 3.96/8.00,
  run_get 5.49/25.43, task_submit 15.6/43.18, health_ready 25.3/35.0.
- Honest gate status: `failed_promotion_checks` replayed against the new
  pack rejects it on all 10 gates (`exactly_once_task_admission`,
  `exactly_once_schedule_occurrence`, `rate_limit_enforced`,
  `lb_failover_bounded`, `replica_2_rejoined`, `nonterminal_runs_after_settle`,
  `task_admission_availability`, `sustain_duration` (1200 s vs 14400 s),
  `exact_rc_artifact`, `graceful_drain`) — the pack is observation evidence
  carrying only the two thresholds it can honestly evaluate, not a promotion
  pack. Evidence:
  `docs/testing/soak/evidence/m3a-round8-prodstack-extended.json` +
  `…-metrics.jsonl`, tied to git head `20c975f3b617…`, both server image
  IDs, the LB image ID, and the compose file sha256
  (`74fdc174732c…`).

## Acceptance audit (updated)

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | PARTIAL: profile defines users/mix/thresholds (`m3a-load-profile.md:46-69`); its own gaps section declares concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal/background activity unverified. Needs the RC designation to finalize. |
| Two application replicas | PARTIAL→STRONGER: prod Compose declares 2 replicas; now 360 s (round 7 A/B) **and 1200 s (this round)** of both replicas driven through nginx with live container identity evidence. Still not RC-designated promotion evidence. |
| Sustained saturation/leak/restart observation | NOT MET for the RC gate; EXTENDED for observation: longest production-artifact window now 1200 s with flat RSS/FD/procs, 0 lock waits, seamless mid-window drain restart. Frozen soak packs still record 90.17 s / 90.43 s vs 14400 s. |
| Exactly-once admission / no duplicate physical work | PARTIAL→STRONGER: 959/959 distinct run_ids, 0 duplicate rows over 1200 s (up from 177/360 s); schedule-occurrence race (1 Run, `already_fired`) proven in round 7; sustained Goal desired-state reconciliation and physical Attempt fencing under load remain UNVERIFIED. |
| Rate limiting not bypassable by replica selection | NOT MET for aggregate allowance: per-process design is documented and deliberate (`rate_limit.py:25-34`); middleware regression reproduces fresh allowance on replica 2. This round additionally observed the limiter *engaging* under sustained unauthenticated load (1×429). Coordinated-store decision belongs to the owning lane (#842). |
| Telemetry with explicit thresholds | PARTIAL→STRONGER: PG sessions/lock-waits/replication, per-replica RSS/FD/procs over 1200 s with no drift; latency p50–max recorded. Application-loop latency and worker census beyond container process counts remain UNVERIFIED (ADR-083026-a91e: absent, not zero). |
| Kill/restart with drain/fencing/recovery | PARTIAL→STRONGER: second drain-restart probe (2.25 s, zero client errors, bounded latency, readiness-recovery window recorded); exactly-once admission across the restart held. Active-work fencing beyond the degraded-path window remains UNVERIFIED (no provider credentials). |
| >=4-hour soak of exact RC artifact/config | BLOCKED (unchanged): no designated immutable RC image/configuration exists in the tree or job; the harness deliberately rejects host-process equivalence (`run_soak.py:635-647`, no CLI override); 1200 s << 14400 s. Cannot be executed under no-background-command constraints even ignoring the RC gap. |
| Findings filed/reclassified to earliest milestone | PARTIAL: F11/F12 and the round-7/round-8 degraded-path findings classified to M3-A in the local record; GitHub mutations are prohibited, so no external filing. |
| Machine+human evidence tied to exact hashes | PARTIAL: this round adds a third machine-readable pack tied to head/image/compose hashes; no qualifying promotion pack exists (all packs mechanically rejected on replay). |

## Handoff

External prerequisites unchanged: (1) release owner designates the immutable
RC image/configuration; (2) owning lane resolves the aggregate rate-budget
contract (#842 vs #860); (3) production-path workloads with credentials plus
physical-effect and application-telemetry oracles; (4) then a >=4-hour soak
on that exact artifact/topology, published with hashes. Any code or
runtime-config change before that requires a new soak. A green ledger and
clean CI cannot remove these blockers, and no gate was weakened to produce
this round's results.

Changed files this round: the round-C evidence pack (JSON + metrics.jsonl)
and this checkpoint (docs-only; no inventory delta — no test suites changed,
`check-suite-inventory.py` scope untouched).

Progress: `{checked: 1, done: 1, skipped: 0, errors: 0, next: designated RC,
aggregate-rate ownership decision, provider-credentialed production-path
soak}`. Focused validation completed; issue acceptance remains blocked, with
the strongest local evidence yet recorded for the two-replica sustained
observation criterion.
