# Issue #860 — round 164 acceptance validation

## Scope and disposition

Validated only the assigned issue #860 on branch `auto-860`, starting head
`323dc1cd9fc5fabc24f1b637a547888bb150e5f7`. The job directory contained no
`check-*.log` files, so no driver verification claim was treated as evidence.
This validation found no basis for speculative production-code or gate changes.
No exact release-candidate artifact/configuration or production deployment was
provided; no promotion-grade soak was performed. The issue remains **BLOCKED**.

## Fresh validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — 143 passed.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed (3533 files).
- `uv run python scripts/check-suite-inventory.py` — passed (21 suites, 34845
  unique test identities).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — passed: 1256 reviewed identities / 1256 findings; zero unclassified or
  never-allowlisted findings. No ledger edit is justified.

These are code-quality and regression checks, not production soak acceptance.
No tests were added, so no inventory-delta note is applicable.

## Acceptance evidence

1. **Representative profile:** profile exists, but
   `docs/testing/soak/m3a-load-profile.md` explicitly reports missing population,
   Graph/node, tool/model, Design/Canvas, Goal/background-worker and other
   representative coverage. Not demonstrated.
2. **At least two production replicas:** previous artifacts describe local
   preflight replicas, not deployed replicas running the selected production RC.
   Not demonstrated at promotion grade.
3. **Sustained saturation/recovery/leak observations:** `scripts/soak/run_soak.py`
   sets `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (line 74). The supplied
   evidence/profile documents no four-hour RC run and calls pool saturation,
   lease reclaim, and long-window leak/error evidence blockers. Not demonstrated.
4. **Exactly-once/fenced physical work:** profile says terminal Run counts do
   not prove physical-work fencing/recovery and identifies physical Attempt
   fencing and Goal reconciliation as gaps. Not demonstrated.
5. **Rate-limit non-bypass:**
   `packages/maistro-server/src/maistro_server/api/rate_limit.py` implements a
   process-local limiter; its budget is not shared across replica selection.
   ADR-085 specifies per-principal rate limits but does not establish that
   enforcement is cluster-wide. The acceptance remains unproven; no competing
   security/authorization authority was introduced.
6. **Required telemetry and thresholds:** profile documents driver loop lag,
   not application event-loop lag, and says worker counts, pool saturation and
   long-window observations remain unverified. Not demonstrated at promotion
   grade.
7. **Active-work kill/restart with drain/fencing/recovery:** prior shakedowns
   are preflight-grade; profile says process exit/rejoin and terminal Run
   counts alone do not prove physical-work recovery. Not demonstrated at
   promotion grade.
8. **Exact RC artifact/configuration and four-hour soak:**
   `scripts/soak/run_soak.py:753-763` hard-codes the host preflight artifact
   check to `ok: false`; the 14,400-second floor is at line 74. No exact RC
   designation/configuration was supplied. Unmet.
9. **Findings filed/reclassified to earliest invariant:**
   `docs/testing/soak/m3a-soak-evidence.md` marks F3 unresolved and records that
   no external finding was filed. Unmet.
10. **Machine/human evidence bound to artifact/config hashes:** historical
    machine-readable and human-readable evidence exists, but is preflight and
    not bound to a designated exact RC artifact/configuration. Not met for the
    release candidate.

## Result

The harness regressions and quality gates pass; they do not prove acceptance.
Do not weaken the fail-closed exact-RC check or reinterpret preflight evidence
as promotion proof. Remaining work requires an owner-designated immutable RC
and configuration, production-topology multi-replica run covering the stated
profile and recovery/fencing claims, appropriate disposition of the
process-local rate-limit mismatch, and filing/reclassification of load findings.
No GitHub actions were taken.
