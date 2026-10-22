---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
---

# 1420 — acceptance-evidence repair

Starting head: `5466ec26d3a4bc8921b5dc1ed15244d90c7afa3a`.

The existing browser receipt test asserted merely that some IDs were stored,
not that any captured observation was stored or grouped under its build.
It now checks the actual emitted events against operator read-back, correlates
IDs with observed responses, requires the configured build in summary groups,
and attaches the queried receipts to the Playwright result.

Three Playwright cases added to `rum-client-off-switches.spec.ts` bundle the
real shared client alongside the real reporter (no synthetic durations or
outcomes): success/HTTP error/text/204 parsing plus wire-field privacy;
offline network error and rejected unload beacon with no replay on reconnect;
and the existing 30-second timeout with no fabricated server ID. Request
bodies, headers, response/error bodies, resource IDs and query/fragment tokens
are deliberately secret-shaped and excluded from the outgoing event fields.
These cases are not pytest-collected; the backend inventory delta is zero.

Relevant accepted ADRs: ADR-083026-1cb1 (reuse server request correlation),
ADR-068 (reuse AuthMiddleware for operator read-back). No scheduler, execution,
authorization or event authority changes; the canonical Goal → Graph → Run →
NodeRun → Attempt model is unaffected. No ADR reconciliation required.

## Executed validation (2026-10-09)

Historical green claims are not acceptance evidence for this round. The
supplied driver logs passed sync, ruff check/format, 84 focused backend tests
and inventory (3581). Independently executed:

- `uv run ruff check .` / `uv run ruff format --check .`: pass.
- `uv run python3 scripts/check-frontend-api-routes.py`: pass, 181 calls in
  70 files resolve to 233 routes. The prior comment-path defect was already
  repaired at this starting head.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: pass, 1326 reviewed
  findings, zero unclassified. No unbanked identity exists, so no ledger
  amendment is appropriate.
- `uv run pytest packages/hive-conductor/backend/tests/test_rum_routes.py
  packages/hive-conductor/backend/tests/test_auth_middleware.py
  packages/hive-conductor/backend/tests/test_request_id_middleware.py
  tests/test_check_frontend_api_routes.py -x -q`: **147 passed**.
- `uv run pytest packages/hive-conductor/backend/tests -x -q`:
  **3562 passed, 19 skipped**, six existing warnings, 147.88 seconds.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: pass, 3581 collected, no delta.
- `uv run python scripts/` gates `check-route-permissions.py`,
  `check-frontend-typed-client.py`, `check-shipped-surface-truth.py`,
  `check_enumerations.py`, `check-enumerations-provenance.py`: all pass.
- Production `npm run build` with `VITE_DEBUG_API=false`,
  `VITE_RUM_ENABLED=true`, `VITE_RUM_SAMPLE_RATE=1`,
  `VITE_RUM_BUILD_ID=repair-1420`: pass (TypeScript and Vite).
- Both RUM Playwright specs, `CI=true` (zero retries): **15 passed**, zero
  skipped/flaky/failed, against that bundle served by the real backend
  (`RUM_INGEST_ENABLED=true`, isolated temporary data, loopback HTTP cookie
  configuration matching compose). A foreground-owned uvicorn thread was
  stopped and joined after the browser subprocess; no server was left running.
- Final eight-case browser matrix re-run after adding the pre-deadline
  assertion (not settled at 29,999 ms, timeout at 30,000 ms): **8 passed**.
  Final ruff check/format, `check-doc-links.py` (1981 documents, zero broken
  links), and `git diff --check`: pass.
- Mutation sensitivity: copied the shipped source into a disposable directory
  and removed only api.ts's reporter calls. The new success/error privacy
  test failed at the nonempty API-event assertion (received 0), as intended.
  The production files were never changed. The mutation wrapper's extra
  plain-text assertion also failed because ANSI escape codes split its search
  string; this does not obscure the actual expected Playwright failure.

## Acceptance evidence

1. **Production load and API receipt:** queried 12 stored observations / 9
   groups. Build `repair-1420`, `/agents` load 39.39999997615814 ms, LCP 84 ms;
   API `/v1/agents` 18.699999928474426 ms. Each captured event is asserted in
   read-back, with the configured build required in summary groups.
2. **Correlation and API semantics:** stored GET request ID `db3e871b6b37`
   matches the backend request log and captured response header. The real
   client browser matrix preserves JSON/text/204 responses and `ApiError`
   detail/status/path, emits HTTP-error correlation, and distinguishes offline
   from the existing 30-second abort with null server IDs.
3. **Privacy:** new browser cases put secrets in the URL, request headers/body,
   response body and HTTP error detail, then assert the exact outgoing event
   keys and absence of those values. Existing schema tests also verify final
   envelope projection, direct identifiers and foreign URLs.
4. **Failure bounds:** disabled and sampled-out sessions send nothing; three
   rejected sends trip the breaker; batch size/pending conservation is pinned;
   missing PerformanceObserver falls back to finite load; offline request and
   rejected unload beacon preserve rendering, and the dropped batch is not
   replayed after reconnect/30 seconds of virtual time.
5. **Repeatable smoke/evidence:** `packages/hive-conductor/docs/RUM.md` now
   includes Docker-independent production smoke commands, expected build
   configuration, representative redacted receipt and observed values. The
   Playwright `collector-receipts` attachment contains the actual query result;
   ignored local artifacts are `test-results/1420-live-report.json` and
   `test-results/1420-receipts.json`. Existing build-group comparison instructions
   remain; no timing SLO is inferred from this run.

## Residual limits

`DOCKER_HOST=unix:///var/run/docker.sock docker info` fails (no daemon), so
container packaging is UNVERIFIED this round. The local production path is
verified, not a dev-server substitute. Optional design/evolve modules and model
router credentials were unavailable; they did not prevent the RUM/auth/SPA
smoke. The dispatch snapshot's integration-scope check was still in progress
with no failure output. Its workflow aggregates remote specialized jobs, not a
standalone local gate; remote integration approval remains UNVERIFIED. No gates,
grants or ledgers were changed, and no remote mutations were performed.
