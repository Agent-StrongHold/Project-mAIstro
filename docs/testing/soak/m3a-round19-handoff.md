# Issue #860 — round 19 validation checkpoint

**BLOCKED; not promotion evidence or integration approval.**

## Frozen scope

Only issue #860 and the explicitly assigned vulture per-identity gate, in
`/home/dev/Git/wt/auto-860`, starting at clean HEAD
`1e8009778f6b90b6f25725ad05d17f1933a3bdd8` (matches the assigned job head;
working tree was clean, no incoming diff to salvage). Assigned develop base
`a9a27b06361f` is the current `origin/develop` head. The branch sync point is
`ecb9cc562` (merge of `56332162cf`); the 12 commits on `origin/develop` since
the merge base are M9 extension/Gauntlet work and dependency bumps and touch
none of this issue's surfaces (soak harness, evidence, rate middleware,
promotion gates). The previous block was an acceptance block, not a develop
sync conflict; no merge was required and none was performed.

The job directory contains no `check-*.log` files, so all deterministic checks
were re-executed locally. Prior-round claims were re-verified against the tree
at this head rather than trusted.

Read-only inspection scope: repository instructions; ADR-081426-1f7c (runtime),
ADR-082126-f69c (recurrence), ADR-085 (cost/quota/rate), ADR-083026-a91e
(unmeasured is absent, not zero); `scripts/soak/run_soak.py`;
`docs/testing/soak/m3a-load-profile.md` and evidence packs;
`tests/test_soak_promotion_gates.py`;
`packages/maistro-server/src/maistro_server/api/rate_limit.py`;
`deploy/docker-compose.prod.yml`; `packages/maistro-server/tests/api/test_rate_limit.py`.
Planned edit scope: this checkpoint only. No source, runtime configuration,
ledger, or test changed; no test inventory delta is required.

## Fresh validation at 1e8009778

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3003 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI args) | PASS: 1336 reviewed identities / 1336 findings, 0 unclassified, 0 never-allowlist; baseline base `56332162cf63`, candidate `1e8009778f6b`. No ledger amendment warranted. |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py -q` | 74 passed in 2.75 s |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS: 4783 tests, 0 duplicates |
| `git diff --check 56332162cf...HEAD` | PASS: whitespace clean (the round-16 EOF findings were fixed in `ad9b17cb9`) |

Inline replay of the promotion-gate evaluator at this head:
`preflight_artifact_check()['ok']` is `False` ("not the exact production
Compose image and configuration"), and `failed_promotion_checks` rejects every
frozen pack — `m3a-soak-evidence.json` and `m3a-repair-validation.json` fail
7 gates each; `m3a-round5-final.json` fails `rate_limit_enforced`,
`sustain_duration` (90.17 s / 14400 s), `exact_rc_artifact`;
`m3a-round6-shakedown.json` fails `sustain_duration` (90.43 s / 14400 s) and
`exact_rc_artifact`. This replays evidence rejection; it is not a new soak.

Re-verified structural facts: `deploy/docker-compose.prod.yml` declares 2
stateless maistro-server replicas behind nginx (line 3);
`rate_limit.py:25-34` documents deliberate process-local enforcement (N x
configured aggregate) with no cluster store; the production-middleware
regression (`tests/test_soak_promotion_gates.py:439-489`) observes
`[200, 200, 429]` independently on both replicas for one principal,
falsifying the old shared-store claim; no immutable RC image/configuration
designation exists anywhere in the tree (only absence records). ADR-085
covers per-scope cost quota (Sentinel BUDGET veto) and does not mandate a
cluster-wide HTTP limiter, so the per-process contract from #842 stands and
the #860 aggregate-bypass criterion is owning-lane work, not a local edit.
No provider keys are present in the environment (no successful tool/model
traffic is possible here).

## Acceptance audit

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | PARTIAL: profile defines users/mix/thresholds (`m3a-load-profile.md:46-69`) but its own gaps section (`:150-166`) declares concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal/background activity unverified — "blockers, not acceptance waivers". |
| Two application replicas | PARTIAL: prod Compose declares 2 replicas; 360 s rounds A/B drove both through nginx with live container identity evidence. Not RC-designated promotion evidence. |
| Sustained saturation/leak/restart observation | NOT MET: longest observation 360 s; frozen soak packs 90.17 s / 90.43 s vs 14400 s minimum; `sustain_duration` correctly fails. |
| Exactly-once admission / no duplicate physical work | PARTIAL: 12->1 distinct run_id and cross-replica schedule-occurrence race (1 Run, `already_fired`) proven; sustained Goal desired-state reconciliation and physical Attempt fencing UNVERIFIED (probe cancels the queued Run without executing it). |
| Rate limiting not bypassable by replica selection | NOT MET for aggregate allowance: per-process design is documented and deliberate (`rate_limit.py:25-34`); middleware regression reproduces fresh allowance on replica 2. Needs a coordinated-store change in the owning lane. |
| Telemetry with explicit thresholds | PARTIAL: PG round-trip/latency/RSS/FD recorded in round B with S3/S4 budgets; application-loop latency, worker/process census and long windows UNVERIFIED (ADR-083026-a91e: absent, not zero). |
| Kill/restart with drain/fencing/recovery | PARTIAL: 360 s SIGTERM drain restart of replica 2 with zero client errors and clean spine audit in-window; active-work fencing beyond that window UNVERIFIED. |
| >=4-hour soak of exact RC artifact/config | BLOCKED: no designated immutable RC image/configuration in the tree or job; the harness deliberately rejects host-process equivalence (`scripts/soak/run_soak.py:635-647`, no CLI override); any code/runtime-config change forces a new soak. Cannot be executed under no-background-command constraints even ignoring the RC gap. |
| Findings filed/reclassified to earliest milestone | PARTIAL: F11/F12 classified to M3-A in the local record; GitHub mutations are prohibited, so no external filing. |
| Machine+human evidence tied to exact hashes | PARTIAL: observation rounds carry identity/per-round git_head/image/config hashes; no qualifying promotion pack exists (all packs mechanically rejected above). |

## Handoff

The only changed file is this checkpoint (docs-only; no inventory delta).
External prerequisites remain: release owner designates the immutable RC
image/configuration; the owning lane resolves the aggregate rate-budget
contract; production-path workloads with credentials plus physical-effect and
application-telemetry oracles are implemented; then a >=4-hour soak runs on
that exact artifact/topology and is published with hashes. Any code or
runtime-config change before that requires a new soak. A green ledger and
clean CI cannot remove these blockers, and no gate was weakened to produce
this round's PASS results.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC,
aggregate-rate ownership decision, and production-path sustained evidence}`.
Focused validation completed; issue acceptance remains blocked. This
checkpoint is committed locally.
