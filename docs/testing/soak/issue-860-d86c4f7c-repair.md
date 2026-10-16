# Issue #860 — d86c4f7c repair checkpoint

## Frozen scope

- Issue #860 only; branch `auto-860`, clean starting HEAD
  `c4ed276ed7e9c6f4e674fd0b94c74954312d2437`, base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb` (both resolved locally).
- Evidence: supplied dispatch-context.json, previous result a3fd32c5,
  previous check-3.log from 98a11313. No check-*.log supplied in current job.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  adjacent production `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `quality/vulture-baseline.json` only if exact scan identifies reviewed debt,
  corresponding inventory note, and this report.
- Acceptance inspection: existing `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, soak profile, relevant ADRs and CI gates.
  No GitHub changes, no deployment/promotion authority changes.

## Initial evidence and assumptions

The historical check-3.log reports 24 DDL statements versus 21 expected.
This is not yet reproduced on the assigned HEAD. The previous result reports
BLOCKED, not successful production acceptance. The branch contains extensive
prior evidence; it is preserved. Exact RC deployment identity/configuration is
not supplied by this lane: local shakedown cannot stand in for production soak.

## Reproduction checkpoint

- Required exact vulture command: exit 0; 1322 findings / 1322 reviewed
  identities, no unclassified or never-allowlist identities. Ledger amendment
  is not justified. Log: `/tmp/860-d86-vulture.log`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical failure does not reproduce: lines 173–175
  already include all three additional schema columns. Production executes
  the upgrades inside the transaction/advisory lock at lines 215–222.
  Log: `/tmp/860-d86-pg-tests.log`. No test weakening or code repair warranted.
- Workflow exact arguments confirmed at `.github/workflows/quality.yml:1079`
  and `.github/workflows/vulture-ratchet.yml:82`.

## Additional executed validation

| Command | Result | Local log |
|---|---|---|
| `uv run ruff check .` | passed | `/tmp/860-d86-ruff.log` |
| `uv run ruff format --check .` | 3301 files already formatted | `/tmp/860-d86-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 72 passed | `/tmp/860-d86-soak-tests.log` |
| `uv run python scripts/check-ratchet-provenance.py` | passed; 53 consumers | `/tmp/860-d86-provenance.log` |

Provenance reports trusted base `321cbdb8fe9b`; no candidate ledger edits.
The provenance gate emitted non-fatal invalid-escape SyntaxWarnings. Six
PostgreSQL integration cases were skipped; unit tests are not live DB proof.

## Architecture and evidence reconciliation

Read repository AGENTS.md, accepted ADR-081226-69ee (Graph/NodeRun/Attempt),
ADR-081626-f383 (durable fencing), and ADR-082526-b36a (renewal/reclaim).
The latter supplies the reclaim contract that the original fencing ADR deferred;
absence of a live soak is not evidence that reclaim is unimplemented. It still
needs observed active-work failure/recovery evidence for #860. ADR-081, cited
by the load profile, is **Proposed**, not overriding accepted authority.
No competing execution, authorization, event, or Goal authority was introduced.

The tests execute the production rate middleware on two ASGI instances:
`tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently
for the same identity on each replica. This proves local allowances, not
cluster-wide protection or deployed ingress bypass. At line 564 the production
task router on queues sharing canonical admission gives owner 200 / peer 404.
These are meaningful falsification probes, not deployed two-replica traffic.

`scripts/soak/run_soak.py:744` always rejects exact-RC equivalence for its
host-process boot path. Executed tests include the CLI rejection even with
synthetic four-hour evidence. Do not remove that guard to manufacture promotion.

## All ten acceptance criteria

| Criterion | Executed evidence or explicit limitation |
|---|---|
| Representative RC workload | **UNVERIFIED**: inspected `m3a-load-profile.md`; one API key, no concurrent Workspace population, successful model/tool traffic, Graph fan-out or Design/Canvas coverage. |
| At least two deployed application replicas | **UNVERIFIED**: executed two-ASGI-instance tests are not production deployment evidence. |
| Sustained pool/queue/reclaim/retry/leak observations | **UNVERIFIED**: no long live load in this round; unit tests do not establish saturation or leak behavior. |
| No duplicate physical work | **UNVERIFIED**: the documented schedule admission probe cancels the queued Run without executing it. Identity uniqueness is not physical-work uniqueness. |
| Replica-resistant rate/security/degraded enforcement | **UNVERIFIED** for deployment; production middleware tests positively reproduce independent per-replica allowances. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**: profile has thresholds but driver query/loop probes do not measure application query/loop latency; process groups exclude detached workers. No new deployed telemetry captured. |
| Active-work kill/restart/drain/fencing/recovery | **UNVERIFIED**: process rejoin and terminal Run counts do not prove physical Attempt recovery. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED / BLOCKED**: CLI rejection verified; no immutable promoted image/configuration supplied and no exact-RC soak executed. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED** for completeness; no GitHub mutations permitted or performed. |
| Human/machine evidence bound to exact hashes | **UNVERIFIED** for promotion: this handoff records source HEAD and deterministic checks, not a new deployed-image/config-bound evidence pack. |

## Final disposition

**BLOCKED** on production acceptance, not on the reported CI failure. The
historical failure is already repaired at the assigned HEAD and the exact debt
scan is clean. No cosmetic production/test changes or fabricated ledger repair.
Only changed file is this report. No tests added, so no inventory delta required.

Next: release owner supplies immutable RC artifact/configuration; complete the
representative workload and application telemetry, resolve replica enforcement
and receipt visibility at existing authorities, then execute a fresh >=4-hour
production soak including physical-Attempt failure/recovery. Repeating these
green deterministic checks cannot discharge that requirement.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC production acceptance evidence}.
Local commit required; no push or integration approval.
