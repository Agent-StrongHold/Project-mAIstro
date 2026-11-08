# Issue #860 — bounded repair checkpoint (job 10e5498a)

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`e617596ed7137efdc72c8bfcc02586f15e6c18f1`, base
`e20e9f52ea94b393184f210cc9379f9f693f13d0`. The worktree was clean. The
job directory contains no `check-*.log` files; prior result JSON is historical
evidence only. This is writer handoff; no production RC or deployment was
available to execute here.

## Validation executed

- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — 84 passed.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed (3,366 files).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — passed: 1,326 reviewed identities / findings, zero unclassified or never-allowlist findings; no ledger change warranted.

The test suite is production-middleware/gate testing, not deployed multi-replica
or sustained soak evidence. Existing result/check records reported in the
supplied prior result include the rate-limit replica-switch reproduction; this
run independently revalidated the gate test suite, not that deployed behavior.

## Architecture reconciliation

Preserve canonical execution authority `Goal -> Graph -> Run -> NodeRun ->
Attempt`; admission receipts and schedule occurrence claims are not proof of
physical Attempt fencing/recovery. Accepted ADR-085 requires principal-scoped
rate limits but does not define distributed request-budget storage. ADR-082426-
82c7 makes occurrence identity a durable Run claim but explicitly does not
claim live scheduler convergence. Neither ADR waives #860's production soak or
replica-selection criterion. `rate_limit.py` explicitly documents independent
per-process request budgets (N replicas yield N× allowance); that behavior is
incompatible with treating a successful direct-per-replica burst as proof that
aggregate budgets cannot be bypassed. No second scheduler, store, event
authority, or authorization path was introduced.

## Acceptance status

| Criterion | Evidence / status |
|---|---|
| Representative release profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md` states one API key and omits concurrent Workspace users, Graph fan-out, successful tool/model calls, Design/Canvas, and Goal/background reconciliation. |
| At least two production replicas | **UNVERIFIED.** Profile calls current runner a host-process preflight rather than the exact Compose RC. |
| Long saturation, queues, lease reclaim, retries, leaks | **UNVERIFIED.** Evidence `m3a-round109-shakedown.json` records 420.05s; profile requires 14,400s and the exact RC. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED.** Schedule admission uniqueness does not execute the queued Run/Attempt; profile explicitly identifies physical fencing and sustained reconciliation as gaps. |
| Security and rate-limit non-bypass | **NOT SATISFIED by current implementation.** `rate_limit.py` documents independent per-replica budgets. The local middleware tests cannot prove a coordinated aggregate budget; resolving this while preserving the accepted principal policy requires a separate, explicitly coordinated design, not a documentation waiver. |
| Required telemetry and thresholds | **PARTIAL / UNVERIFIED.** Historical profile captures driver loop lag, not application event-loop lag, and lacks promotion-grade worker/pool/physical-work observations. |
| Kill/restart active work with drain/fencing/recovery | **UNVERIFIED.** Process rejoin or terminal Run counts do not prove physical Attempt recovery. |
| Four-hour exact-RC soak | **UNVERIFIED.** Current preflight rejects exact artifact evidence; historical run is far below duration floor. |
| Findings filed/reclassified | **UNVERIFIED externally.** Findings are recorded locally; no GitHub mutations were made. |
| Machine/human evidence bound to exact RC hashes | **UNVERIFIED.** Historical host-run evidence cannot bind the promoted image/configuration. |

## Handoff

**NEEDS-REPAIR / production acceptance blocked.** Validation passes do not close
#860. No product behavior or tests were changed because the gaps require an
identified immutable RC, production deployment and long-running physical-work
observations; inventing evidence or weakening thresholds would be invalid. No
tests were added, so no inventory delta is required. Next: resolve the
replica-budget mismatch against an accepted distributed enforcement design,
provide the exact promotion artifact/configuration, then run the representative
multi-replica soak and record machine/human evidence. This local commit is a
handoff only, not integration approval.
