# Issue #860 — fresh validation at dispatched head

This is a validation-only checkpoint for issue #860 on `auto-860`. Starting
HEAD was `05edbd067632356cb265367983ee585eb10b0901`; worktree was clean. The
assigned job directory had no `check-*.log` files, so no driver check was
credited. No production code, tests, inventory, ledger, or grant was changed.
Relevant accepted execution contract remains ADR-081226-a66b: the canonical
Run → NodeRun → Attempt lifecycle is preserved; the requested physical-work
and recovery claims cannot be inferred from process counts alone. ADR-082
requires trace/correlation propagation but does not supply evidence of the
required deployed telemetry.

## Fresh checks

- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — **84 passed**.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -q -x`
  — **26 passed**, one Starlette deprecation warning.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py`
  — passed.
- `uv run python -c '...failed_promotion_checks(...m3a-round109-shakedown.json)'`
  — returned `['sustain_duration', 'exact_rc_artifact']`.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — **1321 reviewed identities
  == 1321 findings**, unclassified 0; no ledger edit warranted.

## Acceptance disposition

- Existing harness tests, admission/backpressure and rate-limit behaviors: the
  targeted suites above pass. They are not deployment/load evidence.
- Representative workload: **UNVERIFIED / gap remains**. The profile at
  `docs/testing/soak/m3a-load-profile.md` still records missing concurrent
  users/Workspaces and Graph fan-out, successful tool/model, Design/Canvas and
  background reconciliation traffic, absent an RC-specific applicability
  decision.
- Multi-replica exact-RC and sustained soak: **NOT MET**. The committed
  round-109 pack reports 420.05 seconds vs the 14,400-second floor and
  `host-uvicorn-preflight`, not the promoted Compose artifact; live gate
  evaluation rejects `sustain_duration` and `exact_rc_artifact`.
- Physical-work uniqueness/fencing and recovery, production telemetry and
  hash-bound exact-RC promotion evidence: **UNVERIFIED**. These require
  representative deployed work, supported restart/recovery assertions and the
  designated immutable RC; a short local harness run cannot establish them.

No tests were added, so no suite-inventory delta note is required. Disposition:
**BLOCKED** on production/release-owner evidence, not on a reproducible in-repo
test or vulture failure. No sync conflict was evidenced and no merge was
attempted.
